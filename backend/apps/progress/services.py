"""Progress va routing logikasi (§4.7)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.conf import settings

from apps.content.models import LEARNER_TRACKS, ContentStatus, Topic, TopicTrack

from .models import TopicProgress, TopicStatus

logger = logging.getLogger(__name__)


def published_topics(track: str = ""):
    """Nashr qilingan mavzular. `track` berilsa — faqat o'sha yo'nalish.

    Yo'nalishlar mustaqil: iboralar ro'yxati grammatika qanchalik o'tilganiga
    qaramaydi, o'z birinchi mavzusidan boshlanadi.
    """
    qs = Topic.objects.filter(status=ContentStatus.PUBLISHED)
    if track:
        qs = qs.filter(track=track)
    return qs.order_by("track", "order") if not track else qs.order_by("order")


def reset_to_first_topic(user) -> list[str]:
    """O'quvchini har yo'nalishning BIRINCHI mavzusiga qaytaradi (§placement.py).

    Daraja aniqlash suhbati "gapirolmaydi" degan xulosa bergan holat. Faqat
    STATUS qaytariladi: urinishlar tarixi, aniqlik va xato jurnali joyida
    qoladi — ular haqiqatan bo'lgan va o'chirilmasligi kerak.

    Qaytarilgan ro'yxat — nima ochilgani, log va test uchun.
    """
    opened = []
    for track in LEARNER_TRACKS:
        topics = list(published_topics(track))
        if not topics:
            continue
        first = topics[0]
        TopicProgress.objects.filter(user=user, topic__in=topics).exclude(topic=first).update(
            status=TopicStatus.LOCKED
        )
        TopicProgress.objects.update_or_create(
            user=user, topic=first, defaults={"status": TopicStatus.ACTIVE}
        )
        opened.append(f"{track}:{first.order}")
    logger.info("progress_reset_to_first user=%s opened=%s", user.id, opened)
    return opened


def ensure_bootstrapped(user) -> None:
    """Har yo'nalishning birinchi mavzusini ochadi (hali ochilmagan bo'lsa).

    `placement` bu yerda yo'q: u ketma-ketlikning bir qismi emas, ya'ni uning
    `TopicProgress` yozuvi ham bo'lmasligi kerak — aks holda o'quvchining
    progressida "o'tilmagan mavzu" bo'lib turardi (§is_topic_accessible).
    """
    for track in LEARNER_TRACKS:
        topics = list(published_topics(track))
        if not topics:
            continue
        existing = TopicProgress.objects.filter(user=user, topic__in=topics)
        if existing.exclude(status=TopicStatus.LOCKED).exists():
            continue
        TopicProgress.objects.get_or_create(
            user=user, topic=topics[0], defaults={"status": TopicStatus.ACTIVE}
        )
        TopicProgress.objects.filter(user=user, topic=topics[0], status=TopicStatus.LOCKED).update(
            status=TopicStatus.ACTIVE
        )


def progress_map(user) -> dict[int, TopicProgress]:
    qs = TopicProgress.objects.filter(user=user).select_related("topic")
    return {p.topic_id: p for p in qs}


def is_topic_accessible(user, topic: Topic) -> bool:
    """Mavzu ochiqmi? Faqat active/mastered mavzularda sessiya boshlanadi."""
    if topic.status != ContentStatus.PUBLISHED:
        return False
    # Daraja aniqlash hech qanday ketma-ketlikka kirmaydi: u BIRINCHI ish va
    # uni ochib beradigan oldingi mavzu yo'q.
    if topic.track == TopicTrack.PLACEMENT:
        return True
    if settings.DEV_UNLOCK_ALL:
        return True
    ensure_bootstrapped(user)
    p = TopicProgress.objects.filter(user=user, topic=topic).first()
    return bool(p and p.status in (TopicStatus.ACTIVE, TopicStatus.MASTERED))


def unlock_next_topic(user, topic: Topic) -> Topic | None:
    """Mavzu mastered bo'lganda O'SHA YO'NALISHDAGI keyingisini ochadi (§4.7)."""
    nxt = published_topics(topic.track).filter(order__gt=topic.order).first()
    if not nxt:
        return None
    p, created = TopicProgress.objects.get_or_create(
        user=user, topic=nxt, defaults={"status": TopicStatus.ACTIVE}
    )
    if not created and p.status == TopicStatus.LOCKED:
        p.status = TopicStatus.ACTIVE
        p.save(update_fields=["status", "updated_at"])
    return nxt


@dataclass
class ProgressUpdate:
    status: str
    mastered_now: bool
    struggling: bool
    unlocked_topic_id: int | None


def recent_first_attempt_accuracies(user, topic: Topic, limit: int) -> list[float]:
    """Oxirgi N sessiyaning birinchi urinishdagi aniqligi (yangi → eski)."""
    from apps.practice.models import SessionMetrics, SessionStatus

    rows = (
        SessionMetrics.objects.filter(
            session__user=user,
            session__topic=topic,
            session__status=SessionStatus.DONE,
        )
        .filter(questions_total__gt=0)
        .order_by("-session__started_at", "-session__created_at")
        .values_list("first_attempt_correct", "questions_total")[:limit]
    )
    return [c / t for c, t in rows if t]


def update_topic_progress(user, topic: Topic, accuracy: float) -> ProgressUpdate:
    """Sessiyadan keyin chaqiriladi. `accuracy` — birinchi urinishdagi aniqlik."""
    p, _ = TopicProgress.objects.get_or_create(
        user=user, topic=topic, defaults={"status": TopicStatus.ACTIVE}
    )
    p.sessions_count += 1
    p.last_accuracy = accuracy
    p.best_accuracy = max(p.best_accuracy or 0.0, accuracy)
    if p.status == TopicStatus.LOCKED:
        p.status = TopicStatus.ACTIVE

    recent = recent_first_attempt_accuracies(user, topic, settings.MASTERY_SESSIONS)
    mastered_now = False
    if (
        len(recent) >= settings.MASTERY_SESSIONS
        and all(a >= settings.MASTERY_ACCURACY for a in recent)
        and p.status != TopicStatus.MASTERED
    ):
        p.status = TopicStatus.MASTERED
        mastered_now = True

    struggling_window = recent_first_attempt_accuracies(user, topic, settings.STRUGGLING_SESSIONS)
    struggling = len(struggling_window) >= settings.STRUGGLING_SESSIONS and all(
        a < settings.STRUGGLING_ACCURACY for a in struggling_window
    )

    p.save(
        update_fields=[
            "sessions_count",
            "last_accuracy",
            "best_accuracy",
            "status",
            "updated_at",
        ]
    )

    unlocked = unlock_next_topic(user, topic) if mastered_now else None
    return ProgressUpdate(
        status=p.status,
        mastered_now=mastered_now,
        struggling=struggling,
        unlocked_topic_id=unlocked.id if unlocked else None,
    )


def previous_topic(topic: Topic) -> Topic | None:
    return published_topics(topic.track).filter(order__lt=topic.order).order_by("-order").first()


# Matn o'quvchi tilida — ruscha interfeysdagi odam yagona o'zbekcha jumlaga
# duch kelmasligi kerak.
STRUGGLING_MESSAGE = {
    "uz": (
        "Bu mavzu hozircha qiyin ko'rinyapti. Materialni qayta o'qib chiqing "
        "yoki oldingi mavzuni takrorlang — shoshilmang."
    ),
    "ru": (
        "Эта тема пока даётся трудно. Перечитайте материал или повторите "
        "предыдущую тему — спешить некуда."
    ),
}


def struggling_hint(user, topic: Topic) -> dict | None:
    """Qiynalayotgan o'quvchiga yumshoq taklif (§4.7). Hech qachon majburiy emas."""
    recent = recent_first_attempt_accuracies(user, topic, settings.STRUGGLING_SESSIONS)
    if len(recent) < settings.STRUGGLING_SESSIONS:
        return None
    if not all(a < settings.STRUGGLING_ACCURACY for a in recent):
        return None
    prev = previous_topic(topic)
    return {
        "topic_id": topic.id,
        "review_material": True,
        "suggested_topic_id": prev.id if prev else None,
        "message": STRUGGLING_MESSAGE.get(user.language_code or "uz", STRUGGLING_MESSAGE["uz"]),
    }
