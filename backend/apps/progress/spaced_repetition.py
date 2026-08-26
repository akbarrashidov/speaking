"""Yengil spaced repetition (§4.8).

Zinapoya: 1 kun → 3 kun → 7 kun. Har muvaffaqiyatli qayta tekshiruvdan keyin
keyingi pog'onaga o'tiladi; oxirgi pog'onadan keyin yozuv `resolved` bo'ladi.
Muvaffaqiyatsiz bo'lsa zinapoya boshiga qaytariladi.
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import ErrorLog

LADDER = settings.SPACED_REPETITION_LADDER


def _interval_days(review_count: int) -> int:
    idx = min(review_count, len(LADDER) - 1)
    return LADDER[idx]


def schedule_new(error_log: ErrorLog, now=None) -> ErrorLog:
    """Yangi xato yozuvi uchun birinchi takrorlash vaqtini o'rnatadi."""
    now = now or timezone.now()
    error_log.review_count = 0
    error_log.next_review_at = now + timedelta(days=LADDER[0])
    return error_log


def due_items(user, topic=None, limit: int | None = None, now=None):
    """Muddati kelgan xatolar (eng eskisi birinchi)."""
    now = now or timezone.now()
    limit = limit or settings.SPACED_REPETITION_MAX_INJECT
    qs = ErrorLog.objects.filter(user=user, resolved=False, next_review_at__lte=now).select_related(
        "topic"
    )
    if topic is not None:
        # Avval shu mavzuga tegishlilari, keyin qolganlari.
        qs = qs.order_by("-topic_id", "next_review_at")
    else:
        qs = qs.order_by("next_review_at")
    return list(qs[:limit])


def mark_reviewed(error_log: ErrorLog, success: bool, now=None) -> ErrorLog:
    """Kiritilgan element to'g'ri qaytarildimi — zinapoyani yangilaydi."""
    now = now or timezone.now()
    if success:
        error_log.review_count += 1
        if error_log.review_count >= len(LADDER):
            error_log.resolved = True
            error_log.next_review_at = None
        else:
            error_log.next_review_at = now + timedelta(days=_interval_days(error_log.review_count))
    else:
        error_log.review_count = 0
        error_log.next_review_at = now + timedelta(days=LADDER[0])
    error_log.save(update_fields=["review_count", "next_review_at", "resolved"])
    return error_log


def build_injection_block(items: list[ErrorLog]) -> str:
    """System promptga qo'shiladigan matn (§4.8). Bo'sh bo'lsa — bo'sh qator."""
    if not items:
        return ""
    lines = []
    for it in items:
        wrong = (it.learner_utterance or "").strip()
        right = (it.correction or "").strip()
        if wrong and right:
            lines.append(f'- said "{wrong}" — should be "{right}" ({it.error_type})')
        elif right:
            lines.append(f'- target form: "{right}" ({it.error_type})')
        elif it.error_type:
            lines.append(f"- recurring error: {it.error_type}")
    if not lines:
        return ""
    return (
        "This learner has previously made these mistakes:\n"
        + "\n".join(lines)
        + "\nNaturally check one or two of them during the session. "
        "Do not announce that you are testing them."
    )


def error_log_ids(items: list[ErrorLog]) -> list[int]:
    return [i.id for i in items]
