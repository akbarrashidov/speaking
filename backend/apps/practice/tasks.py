"""Sessiyadan keyingi Celery pipeline'i (§4.6). Idempotent."""

from __future__ import annotations

import logging
from decimal import Decimal

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.content.models import SessionMode
from apps.progress import services as progress_services
from apps.progress import spaced_repetition
from apps.progress.models import ErrorLog

from . import analysis, cost, placement
from . import metrics as metrics_mod
from .models import (
    EndReason,
    Evaluation,
    Session,
    SessionMetrics,
    SessionStatus,
    SessionTurn,
    Speaker,
)
from .store import SyncSessionStore

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def process_session(self, session_id: str):
    """Transkriptni saqlaydi, metrikalarni hisoblaydi, feedbackni tayyorlaydi."""
    session = Session.objects.select_related("user", "topic").filter(pk=session_id).first()
    if session is None:
        logger.warning("process_session: sessiya topilmadi %s", session_id)
        return

    log_ctx = f"session_id={session_id}"
    already_done = session.status == SessionStatus.DONE
    store = SyncSessionStore(session_id)

    raw_turns = store.get_turns()
    raw_evals = store.get_evaluations()
    raw_coach = store.get_coach()
    meta = store.get_meta()
    state = store.load_state()

    # Coach topgan xatolarni tegishli baholashga bog'lash uchun indeks.
    by_attempt = {
        (r.get("question_id"), r.get("attempt")): (r.get("errors") or []) for r in raw_coach
    }

    # 1. Transkriptni Redis'dan PostgreSQL'ga ko'chirish (idempotent).
    with transaction.atomic():
        SessionTurn.objects.filter(session=session).delete()
        Evaluation.objects.filter(session=session).delete()

        SessionTurn.objects.bulk_create(
            [
                SessionTurn(
                    session=session,
                    # Consumer bergan raqam saqlanadi — jonli suhbat va keyin
                    # o'qiladigan suhbat bir xil raqamlansin.
                    idx=int(t.get("idx") or i + 1),
                    speaker=(Speaker.AI if t.get("speaker") == "ai" else Speaker.LEARNER),
                    text=(t.get("text") or "")[:8000],
                    started_at_ms=int(t.get("started_at_ms") or 0),
                    ended_at_ms=int(t.get("ended_at_ms") or 0),
                    question_id=t.get("question_id"),
                )
                for i, t in enumerate(raw_turns)
            ]
        )
        Evaluation.objects.bulk_create(
            [
                Evaluation(
                    session=session,
                    question_id=e.get("question_id"),
                    attempt=int(e.get("attempt") or 1),
                    verdict=e.get("verdict") or "unintelligible",
                    target_structure_used=bool(e.get("target_structure_used")),
                    error_type=(e.get("error_type") or "")[:64],
                    errors=by_attempt.get((e.get("question_id"), e.get("attempt")), []),
                    learner_utterance=(e.get("learner_utterance") or "")[:4000],
                    recovered_after_model=bool(e.get("recovered_after_model")),
                )
                for e in raw_evals
            ]
        )

    # 2. Deterministik metrikalar.
    computed = metrics_mod.compute_from_turns(raw_turns, session.duration_seconds)
    computed = metrics_mod.apply_evaluations(computed, raw_evals)

    # 3. Feedback: xatolarni coach allaqachon topgan, LLM faqat izohlaydi.
    transcript = metrics_mod.transcript_text(raw_turns)
    target_structure = meta.get("target_structure") or session.topic.target_structure
    result = analysis.analyse_session(
        coach_records=raw_coach,
        transcript=transcript,
        target_structure=target_structure,
        register=session.user.speaking_register,
        accuracy_pct=round(metrics_mod.first_attempt_accuracy(computed) * 100),
        # Tahlil o'quvchi tilida yoziladi. Meta'da bo'lmasa (eski sessiyalar) —
        # profildan olinadi (§users.language_code).
        language=meta.get("learner_language") or session.user.language_code or "uz",
    )

    summary = result.get("summary_uz") or analysis.fallback_summary(
        meta.get("learner_language") or session.user.language_code or "uz"
    )
    errors = result.get("errors") or []

    # 3b. Sessiya narxi: Live audio/matn + barcha matn LLM chaqiruvlari.
    llm_calls = store.get_llm_calls()
    if result.get("usage"):
        llm_calls.append(result["usage"])
    breakdown = cost.session_breakdown(
        meta.get("usage") or session.usage,
        meta.get("live_model") or settings.GEMINI_LIVE_MODEL,
        llm_calls,
    )
    logger.info(cost.log_line(session_id, breakdown))

    SessionMetrics.objects.update_or_create(
        session=session,
        defaults={
            "cost_usd": Decimal(str(breakdown.total_usd)),
            "usage_breakdown": breakdown.to_dict(),
            "talk_time_seconds": computed.talk_time_seconds,
            "talk_time_pct": computed.talk_time_pct,
            "wpm": computed.wpm,
            "avg_response_latency_ms": computed.avg_response_latency_ms,
            "questions_total": computed.questions_total,
            "correct_total": computed.correct_total,
            "first_attempt_correct": computed.first_attempt_correct,
            "filler_count": computed.filler_count,
            "feedback_summary_uz": summary,
            "errors": errors,
            "feedback": {
                "patterns": result.get("patterns") or [],
                "growth_point_uz": result.get("growth_point_uz") or "",
                "next_drills": result.get("next_drills") or [],
                "strengths_uz": result.get("strengths_uz") or [],
            },
            "stuck_count": int(state.stuck_count) if state else 0,
            "analysis_ok": bool(result.get("ok")),
        },
    )

    if session.usage != (meta.get("usage") or {}):
        session.usage = meta.get("usage") or {}
        session.save(update_fields=["usage"])

    # 4–5. Progress, ErrorLog, spaced repetition — faqat birinchi ishlovda.
    if not already_done and session.mode == SessionMode.PLACEMENT:
        # Daraja aniqlash — dars emas: mavzu progressi ham, xato jurnali ham
        # yozilmaydi. Uning yagona natijasi — o'quvchi qaysi registrdan va
        # qaysi mavzudan boshlashi (§placement.py).
        _apply_placement(session, raw_coach)
    elif not already_done:
        accuracy = metrics_mod.first_attempt_accuracy(computed)
        update = progress_services.update_topic_progress(session.user, session.topic, accuracy)
        _write_error_logs(session, errors, target_structure)
        _update_spaced_repetition(session, meta, errors)
        logger.info(
            "session_processed %s accuracy=%.2f status=%s mastered=%s wpm=%.1f "
            "talk_time_pct=%.1f latency=%dms",
            log_ctx,
            accuracy,
            update.status,
            update.mastered_now,
            computed.wpm,
            computed.talk_time_pct,
            computed.avg_response_latency_ms,
        )

    session.status = SessionStatus.DONE
    if not session.ended_at:
        session.ended_at = timezone.now()
    session.save(update_fields=["status", "ended_at"])

    store.purge()
    return {"session_id": session_id, "questions": computed.questions_total}


def _apply_placement(session, coach_records: list[dict]) -> None:
    """Daraja aniqlash xulosasini profilga va progressga yozadi.

    Ikki natija chiqadi va ikkalasi ham SHU YERDA qotiriladi, chunki bu
    o'quvchi uchun eng qimmat qaror: keyingi sessiyalar shundan boshlanadi.

    Qoidalarning o'zi `placement.py` da — sof funksiya, testlar bilan. Bu yerda
    faqat natijani saqlash bor.
    """
    result = placement.outcome(coach_records)
    user = session.user
    user.speaking_register = result.register
    user.placement_done = True
    user.save(update_fields=["speaking_register", "placement_done"])

    opened = []
    if result.back_to_start:
        opened = progress_services.reset_to_first_topic(user)

    logger.info(
        "placement_done session=%s user=%s register=%s reason=%s turns=%s "
        "fluency=%.2f accuracy=%.2f back_to_start=%s opened=%s",
        session.id,
        user.id,
        result.register,
        result.reason,
        result.graded_turns,
        result.avg_fluency,
        result.accuracy,
        result.back_to_start,
        opened,
    )


def _write_error_logs(session: Session, errors: list[dict], target_structure: str):
    """§4.6.5 — ErrorLog qatorlari spaced repetition manbai bo'ladi."""
    rows = []
    for err in errors:
        if err.get("severity") == "low":
            continue
        row = ErrorLog(
            user=session.user,
            topic=session.topic,
            session=session,
            target_structure=target_structure or "",
            error_type=(err.get("error_type") or "")[:64],
            learner_utterance=err.get("utterance") or "",
            correction=err.get("correction") or "",
        )
        spaced_repetition.schedule_new(row)
        rows.append(row)
    if rows:
        ErrorLog.objects.bulk_create(rows)


def _update_spaced_repetition(session: Session, meta: dict, errors: list[dict]):
    """Kiritilgan elementlar to'g'ri qaytarildimi — zinapoyani yangilaydi (§4.8)."""
    injected_ids = meta.get("injected_error_log_ids") or []
    if not injected_ids:
        return
    repeated_types = {
        (e.get("error_type") or "").strip().lower() for e in errors if e.get("error_type")
    }
    for item in ErrorLog.objects.filter(id__in=injected_ids, user=session.user):
        success = (item.error_type or "").strip().lower() not in repeated_types
        spaced_repetition.mark_reviewed(item, success)


@shared_task
def finalize_if_abandoned(session_id: str):
    """§5.3 — grace oynasi tugadi: client qaytmasa sessiya yopiladi."""
    session = Session.objects.filter(pk=session_id).first()
    if session is None or session.status != SessionStatus.ACTIVE:
        return
    from .services import finalize_session

    if SyncSessionStore(session_id).has_active_consumer():
        # Client qaytib ulangan — yangi consumer ishlayapti.
        return

    duration = None
    if session.started_at:
        duration = int((timezone.now() - session.started_at).total_seconds())
    finalize_session(session, EndReason.DISCONNECT, duration)
    logger.info("session_abandoned session_id=%s", session_id)


# Sessiya yaratilgandan keyin WS ulanishi uchun beriladigan vaqt.
CONNECT_GRACE_SECONDS = 120


@shared_task
def abort_if_never_started(session_id: str, grace_seconds: int = CONNECT_GRACE_SECONDS):
    """WS umuman ulanmagan sessiyani bekor qiladi va kvotani qaytaradi.

    Client `/sessions/start` ni chaqirib, WS ochmasa (masalan mikrofon rad etildi
    yoki ilova yopildi) — o'quvchi kunlik kvotasini behuda yo'qotmasligi kerak.
    """
    from .services import abort_unstarted_session

    session = Session.objects.select_related("user").filter(pk=session_id).first()
    if session is None or session.status != SessionStatus.ACTIVE:
        return
    if session.started_at is not None:
        return
    # Eager rejimda (testlar) countdown e'tiborga olinmaydi — vaqtni o'zimiz
    # tekshiramiz, aks holda hozirgina yaratilgan sessiya bekor qilinardi.
    if (timezone.now() - session.created_at).total_seconds() < grace_seconds:
        return

    abort_unstarted_session(session)
    logger.info("session_never_started session_id=%s kvota qaytarildi", session_id)
