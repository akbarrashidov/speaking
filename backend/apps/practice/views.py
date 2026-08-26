import logging

from django.db.models import Count
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.content.models import ContentStatus, Topic, TopicTrack, localized
from apps.progress import services as progress_services

from .models import EndReason, Session, SessionStatus
from .services import SessionStartError, finalize_session, start_session

logger = logging.getLogger(__name__)

# Tarixda ko'rsatiladigan sessiyalar soni. Suhbat matni bazada butunlay
# saqlanadi — bu faqat ro'yxat uzunligi.
SESSION_HISTORY_LIMIT = 50

_START_ERROR_STATUS = {
    "quota_exceeded": status.HTTP_402_PAYMENT_REQUIRED,
    "cost_cap_reached": status.HTTP_402_PAYMENT_REQUIRED,
    "topic_locked": status.HTTP_403_FORBIDDEN,
    "topic_not_found": status.HTTP_404_NOT_FOUND,
    "no_questions": status.HTTP_409_CONFLICT,
    "mode_not_implemented": status.HTTP_409_CONFLICT,
}


@api_view(["POST"])
def sessions_start(request):
    """POST /api/sessions/start — kvota va kirish tekshiruvi, so'ng WS URL."""
    topic_id = request.data.get("topic_id")
    if not topic_id:
        return Response({"error": "topic_id_required"}, status=status.HTTP_400_BAD_REQUEST)
    try:
        payload = start_session(request.user, int(topic_id))
    except (TypeError, ValueError):
        return Response({"error": "topic_id_invalid"}, status=status.HTTP_400_BAD_REQUEST)
    except SessionStartError as exc:
        return Response(
            {"error": exc.code, "detail": exc.detail, **exc.extra},
            status=_START_ERROR_STATUS.get(exc.code, status.HTTP_400_BAD_REQUEST),
        )
    return Response(payload, status=status.HTTP_201_CREATED)


@api_view(["POST"])
def placement_start(request):
    """POST /api/placement/start — daraja aniqlash suhbatini boshlaydi.

    Alohida endpoint, chunki klient mavzu raqamini BILMASLIGI kerak: daraja
    aniqlash mavzusi kontent emas, infratuzilma (§content migration 0012) va u
    hech qaysi ro'yxatda ko'rinmaydi. Klient shunchaki "boshla" deydi.

    Qayta o'tish taqiqlanmagan: o'quvchi uzoq tanaffusdan keyin qaytsa yoki
    birinchi urinish uzilib qolsa, o'lchovni yangilash to'g'ri ish. Klient uni
    faqat `placement_done` false bo'lganda ko'rsatadi.
    """
    topic = (
        Topic.objects.filter(track=TopicTrack.PLACEMENT, status=ContentStatus.PUBLISHED)
        .order_by("order")
        .first()
    )
    if topic is None:
        # Migratsiya o'tmagan yoki mavzu qo'lda o'chirilgan. Jimgina xato
        # emas: busiz yangi foydalanuvchi hech qayerga bora olmaydi.
        logger.error("placement_topic_missing user=%s", request.user.id)
        return Response(
            {"error": "placement_unavailable", "detail": "Daraja aniqlash mavzusi topilmadi"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return sessions_start_for(request, topic.id)


def sessions_start_for(request, topic_id: int):
    """`sessions_start` ning ichki qismi — xato xaritasi bir joyda qolsin."""
    try:
        payload = start_session(request.user, int(topic_id))
    except SessionStartError as exc:
        return Response(
            {"error": exc.code, "detail": exc.detail, **exc.extra},
            status=_START_ERROR_STATUS.get(exc.code, status.HTTP_400_BAD_REQUEST),
        )
    return Response(payload, status=status.HTTP_201_CREATED)


@api_view(["POST"])
def sessions_end(request, session_id):
    """POST /api/sessions/{id}/end — client tomonidan erta yakunlash."""
    session = get_object_or_404(Session, pk=session_id, user=request.user)
    if session.status == SessionStatus.ACTIVE:
        finalize_session(session, EndReason.COMPLETED)
    return Response({"status": session.status, "session_id": str(session.id)})


def _transcript(session: Session) -> list[dict]:
    """Saqlangan suhbat. Bo'sh gaplar tashlab yuboriladi (audio bor, matn yo'q)."""
    return [
        {"idx": turn.idx, "speaker": turn.speaker, "text": turn.text}
        for turn in session.turns.order_by("idx")
        if turn.text.strip()
    ]


@api_view(["GET"])
def sessions_list(request):
    """GET /api/sessions — o'tgan suhbatlar, eng yangisi birinchi (§4.10)."""
    sessions = (
        Session.objects.filter(user=request.user, status=SessionStatus.DONE)
        .select_related("topic", "metrics")
        .annotate(turns_count=Count("turns"))
        .order_by("-started_at", "-created_at")[:SESSION_HISTORY_LIMIT]
    )

    language = request.user.language_code or ""
    items = []
    for session in sessions:
        metrics = getattr(session, "metrics", None)
        accuracy = None
        if metrics and metrics.questions_total:
            accuracy = round(metrics.first_attempt_correct / metrics.questions_total * 100)
        items.append(
            {
                "session_id": str(session.id),
                "topic_id": session.topic_id,
                "title": localized(session.topic, "title", language),
                "started_at": session.started_at,
                "duration_seconds": session.duration_seconds,
                "questions_total": metrics.questions_total if metrics else 0,
                "accuracy": accuracy,
                "turns_count": session.turns_count,
            }
        )
    return Response({"sessions": items, "limit": SESSION_HISTORY_LIMIT})


@api_view(["GET"])
def sessions_feedback(request, session_id):
    """GET /api/sessions/{id}/feedback — processing → ready (§4.10)."""
    session = get_object_or_404(
        Session.objects.select_related("topic"),
        pk=session_id,
        user=request.user,
    )

    if session.status in (SessionStatus.ACTIVE, SessionStatus.PROCESSING):
        return Response({"status": "processing", "session_id": str(session.id)})

    metrics = getattr(session, "metrics", None)
    if session.status == SessionStatus.FAILED and metrics is None:
        return Response(
            {"status": "failed", "session_id": str(session.id)},
            status=status.HTTP_200_OK,
        )
    if metrics is None:
        return Response({"status": "processing", "session_id": str(session.id)})

    progress = progress_services.progress_map(request.user).get(session.topic_id)
    next_action = "repeat_topic"
    if progress and progress.status == "mastered":
        next_action = "next_topic"

    return Response(
        {
            "status": "ready",
            "session_id": str(session.id),
            "topic": {
                "id": session.topic_id,
                "title": localized(session.topic, "title", request.user.language_code or ""),
            },
            "duration_seconds": session.duration_seconds,
            "end_reason": session.end_reason,
            "metrics": {
                "talk_time_seconds": metrics.talk_time_seconds,
                "talk_time_pct": round(metrics.talk_time_pct, 1),
                "wpm": round(metrics.wpm, 1),
                "avg_response_latency_ms": metrics.avg_response_latency_ms,
                "questions_total": metrics.questions_total,
                "correct_total": metrics.correct_total,
                "first_attempt_correct": metrics.first_attempt_correct,
                "first_attempt_accuracy": round(metrics.first_attempt_accuracy * 100),
                "filler_count": metrics.filler_count,
            },
            "errors": metrics.errors[:5],  # §4.10 — maksimum 5 ta
            # §Faza 7 — takrorlanuvchi naqshlar va keyingi qadam.
            "patterns": (metrics.feedback or {}).get("patterns", [])[:3],
            "growth_point_uz": (metrics.feedback or {}).get("growth_point_uz", ""),
            "next_drills": (metrics.feedback or {}).get("next_drills", []),
            "strengths_uz": (metrics.feedback or {}).get("strengths_uz", []),
            "summary_uz": metrics.feedback_summary_uz,
            "transcript": _transcript(session),
            "topic_status": progress.status if progress else "active",
            "next_action": next_action,
            "struggling_hint": progress_services.struggling_hint(request.user, session.topic),
        }
    )
