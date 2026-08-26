"""Sessiya yaratish/yakunlash xizmatlari (§4.4, §4.9, §5.2)."""

from __future__ import annotations

import json
import logging
import os

from django.db import transaction
from django.utils import timezone

from apps.content.models import FREE_FLOW_MODES, IMPLEMENTED_MODES, SessionMode, Topic
from apps.progress import services as progress_services
from apps.progress import spaced_repetition
from apps.users import quota

from . import adaptive
from .models import EndReason, Session, SessionStatus
from .prompts import PROMPT_VERSION, build_system_prompt, prompt_fingerprint
from .state import SessionState
from .store import SyncSessionStore, sync_client
from .tasks import CONNECT_GRACE_SECONDS, abort_if_never_started

logger = logging.getLogger(__name__)


class SessionStartError(Exception):
    def __init__(self, code: str, detail: str = "", **extra):
        self.code = code
        self.detail = detail or code
        self.extra = extra
        super().__init__(code)


@transaction.atomic
def start_session(user, topic_id: int) -> dict:
    """Sessiyani tayyorlaydi: kvota, kirish huquqi, holat, system prompt."""
    try:
        topic = Topic.objects.get(pk=topic_id)
    except Topic.DoesNotExist as exc:
        raise SessionStartError("topic_not_found") from exc

    mode = topic.effective_mode
    if mode not in {m.value if hasattr(m, "value") else m for m in IMPLEMENTED_MODES}:
        raise SessionStartError("mode_not_implemented", f"'{mode}' rejimi MVP'da mavjud emas")

    if not progress_services.is_topic_accessible(user, topic):
        raise SessionStartError("topic_locked", "Bu mavzu hali ochilmagan")

    bank = list(
        topic.approved_questions().values_list("id", "question_text")[: topic.max_questions]
    )
    question_ids = [qid for qid, _ in bank]
    if not question_ids:
        raise SessionStartError("no_questions", "Bu mavzuda tasdiqlangan savollar yo'q")

    # Kvota — sessiya yozuvidan oldin (§4.9).
    try:
        qstatus = quota.consume(user)
    except quota.QuotaExceeded as exc:
        detail = (
            "Bugungi sarf chegarasiga yetildi — ertaga davom eting"
            if exc.reason == "cost_cap_reached"
            else "Bugungi bepul sessiya limiti tugadi"
        )
        raise SessionStartError(
            exc.reason,
            detail,
            next_available_at=exc.next_available_at.isoformat(),
        ) from exc

    session = Session.objects.create(
        user=user,
        topic=topic,
        mode=mode,
        prompt_version=PROMPT_VERSION,
        time_limit_seconds=qstatus.duration_seconds,
        status=SessionStatus.ACTIVE,
    )

    # Spaced repetition kiritmasi (§4.8) — suhbat rejimlarida (§5.2.5).
    injected = []
    sr_block = ""
    # Daraja aniqlashda YO'Q: o'tgan xatolarni qaytarish o'lchovni buzadi —
    # o'quvchi tayyorlangan gapni aytadi va u bilgani bo'lib ko'rinadi.
    if mode != SessionMode.PLACEMENT and (mode == "guided_conversation" or mode in FREE_FLOW_MODES):
        injected = spaced_repetition.due_items(user, topic=topic)
        sr_block = spaced_repetition.build_injection_block(injected)

    # Daraja tanlanmaydi: AI o'quvchi o'tgan safar qanday gapirgan bo'lsa,
    # shu registrdan boshlaydi va suhbat davomida unga qarab yuradi.
    register = adaptive.clamp(user.speaking_register)

    # Shadowing rejasi: har gap videoning qaysi oralig'ida turadi. Klient shu
    # ro'yxat bo'yicha klip o'ynatadi, backend esa aynan shu gapga qarab
    # baholaydi (§shadow.py).
    media_src = topic.media_src
    shadow_lines = []
    if mode == "shadowing":
        shadow_lines = [
            {
                "idx": i,
                "question_id": q.id,
                "text": q.canonical_answer.strip() or q.question_text.strip(),
                "start_ms": q.clip_start_ms,
                "end_ms": q.clip_end_ms,
            }
            for i, q in enumerate(topic.approved_questions()[: topic.max_questions])
        ]

    system_prompt = build_system_prompt(
        mode=mode,
        register=register,
        target_structure=topic.target_structure,
        topic_title_en=topic.title_en,
        focus_phrase=topic.focus_phrase,
        persona=topic.persona_en,
        setting=topic.setting_en,
        has_media=bool(media_src),
        chunks=list(topic.chunks.values("text", "translation_uz")),
        spaced_repetition_block=sr_block,
        # Faqat adaptive rejimda ishlatiladi — u yerda savollar GOALS ro'yxati.
        questions=[text for _, text in bank],
        # Xato shu tilda tushuntiriladi (§prompts._explanation_language_block).
        learner_language=user.language_code or "uz",
        # Daraja aniqlash zinapoyasi qaysi pog'onadan boshlanishini tanlaydi
        # (§prompts._placement_ladder_block). Boshqa rejimlarda ishlatilmaydi.
        declared_level=user.get_declared_level_display() if user.declared_level else "",
        learning_background=(user.learning_background or "").strip()[:400],
    )

    state = SessionState(
        session_id=str(session.id),
        mode=mode,
        register=register,
        question_ids=question_ids,
        max_questions=min(topic.max_questions, len(question_ids)),
        injected_error_log_ids=spaced_repetition.error_log_ids(injected),
    )

    client = sync_client()
    ttl = session.time_limit_seconds + 3600
    client.set(f"sess:{session.id}:state", json.dumps(state.to_dict()), ex=ttl)
    client.hset(
        f"sess:{session.id}:meta",
        mapping={
            k: json.dumps(v)
            for k, v in {
                "system_prompt": system_prompt,
                "prompt_version": PROMPT_VERSION,
                "prompt_fingerprint": prompt_fingerprint(system_prompt),
                "user_id": user.id,
                "topic_id": topic.id,
                # AI gapining tarjimasi va sessiya yakunidagi tahlil shu tilda
                # yoziladi (§translate.py, §analysis.py).
                "learner_language": user.language_code or "uz",
                "target_structure": topic.target_structure,
                # Ibora yo'nalishida coach aynan shu iborani izlaydi.
                "focus_phrase": topic.focus_phrase,
                "mode": mode,
                "track": topic.track,
                # Rol suhbat muhiti: klient fonni va sahnani shundan quradi,
                # Live esa shu ovoz bilan gapiradi.
                "persona": topic.persona_en,
                "setting": topic.setting_en,
                "ambience": topic.ambience,
                "voice": topic.voice,
                "media_src": media_src,
                "media_kind": topic.media_kind,
                "media_ref": topic.media_ref,
                "shadow_lines": shadow_lines,
                "time_limit_seconds": session.time_limit_seconds,
                "injected_error_log_ids": state.injected_error_log_ids,
            }.items()
        },
    )
    client.expire(f"sess:{session.id}:meta", ttl)

    logger.info(
        "session_started session_id=%s user_id=%s topic_id=%s mode=%s prompt=%s questions=%d",
        session.id,
        user.id,
        topic.id,
        mode,
        PROMPT_VERSION,
        len(question_ids),
    )

    # Client WS ochmasa kvota qaytariladi (masalan mikrofonga ruxsat berilmadi).
    transaction.on_commit(
        lambda: abort_if_never_started.apply_async(
            args=[str(session.id)], countdown=CONNECT_GRACE_SECONDS
        )
    )

    return {
        "session_id": str(session.id),
        "ws_url": ws_url_for(session.id),
        "time_limit_s": session.time_limit_seconds,
        "mode": mode,
        "questions_total": len(question_ids),
        "quota": {
            "remaining": qstatus.remaining,
            "limit": qstatus.limit,
            "plan": qstatus.plan,
        },
    }


def ws_url_for(session_id) -> str:
    base = os.getenv("PUBLIC_WS_BASE", "").rstrip("/")
    path = f"/ws/session/{session_id}/"
    return f"{base}{path}" if base else path


def finalize_session(session: Session, reason: str, duration_seconds: int | None = None):
    """Sessiyani yopadi va post-session pipeline'ni ishga tushiradi (§4.6)."""
    from .tasks import process_session

    if session.status not in (SessionStatus.ACTIVE,):
        # Allaqachon yakunlangan — idempotent.
        return session

    now = timezone.now()
    session.ended_at = now
    session.end_reason = reason or EndReason.COMPLETED
    if duration_seconds is not None:
        session.duration_seconds = duration_seconds
    elif session.started_at:
        session.duration_seconds = int((now - session.started_at).total_seconds())
    session.status = SessionStatus.PROCESSING
    session.save(update_fields=["ended_at", "end_reason", "duration_seconds", "status"])

    logger.info(
        "session_finalized session_id=%s reason=%s duration=%ss",
        session.id,
        session.end_reason,
        session.duration_seconds,
    )
    process_session.delay(str(session.id))
    return session


def abort_unstarted_session(session: Session) -> None:
    """WS umuman ulanmagan sessiya — kvota qaytariladi."""
    if session.started_at is not None or session.status != SessionStatus.ACTIVE:
        return
    session.status = SessionStatus.FAILED
    session.end_reason = EndReason.ERROR
    session.ended_at = timezone.now()
    session.save(update_fields=["status", "end_reason", "ended_at"])
    quota.refund(session.user)
    SyncSessionStore(str(session.id)).purge()
