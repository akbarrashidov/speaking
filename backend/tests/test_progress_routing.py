"""§4.7 — mastery, qiynalish va daraja ko'tarish thresholdlari."""

from django.utils import timezone

from apps.practice.models import EndReason, Session, SessionMetrics, SessionStatus
from apps.progress import services
from apps.progress.models import TopicProgress, TopicStatus


def add_session(user, topic, *, correct, total, latency_ms=1500, offset_minutes=0):
    """Yakunlangan sessiya + metrikalarini yaratadi (eng yangisi oxirgi qo'shilgani)."""
    session = Session.objects.create(
        user=user,
        topic=topic,
        mode=topic.effective_mode,
        status=SessionStatus.DONE,
        end_reason=EndReason.COMPLETED,
        started_at=timezone.now() + timezone.timedelta(minutes=offset_minutes),
        duration_seconds=300,
    )
    SessionMetrics.objects.create(
        session=session,
        questions_total=total,
        correct_total=correct,
        first_attempt_correct=correct,
        avg_response_latency_ms=latency_ms,
    )
    return session


# --- mavzu o'zlashtirish --------------------------------------------------


def test_topic_becomes_mastered_after_two_sessions_above_80(user, topic, topic2):
    add_session(user, topic, correct=9, total=10, offset_minutes=1)
    add_session(user, topic, correct=8, total=10, offset_minutes=2)

    update = services.update_topic_progress(user, topic, 0.8)

    assert update.mastered_now is True
    assert update.status == TopicStatus.MASTERED
    # Keyingi mavzu ochiladi.
    assert update.unlocked_topic_id == topic2.id
    assert TopicProgress.objects.get(user=user, topic=topic2).status == TopicStatus.ACTIVE


def test_one_good_session_is_not_enough_for_mastery(user, topic):
    add_session(user, topic, correct=10, total=10, offset_minutes=1)
    update = services.update_topic_progress(user, topic, 1.0)
    assert update.mastered_now is False
    assert update.status == TopicStatus.ACTIVE


def test_mastery_requires_both_recent_sessions_above_threshold(user, topic):
    add_session(user, topic, correct=9, total=10, offset_minutes=1)
    add_session(user, topic, correct=5, total=10, offset_minutes=2)  # oxirgisi past

    update = services.update_topic_progress(user, topic, 0.5)
    assert update.mastered_now is False


def test_progress_row_tracks_last_and_best_accuracy(user, topic):
    services.update_topic_progress(user, topic, 0.4)
    services.update_topic_progress(user, topic, 0.9)
    services.update_topic_progress(user, topic, 0.6)

    row = TopicProgress.objects.get(user=user, topic=topic)
    assert row.sessions_count == 3
    assert row.last_accuracy == 0.6
    assert row.best_accuracy == 0.9


# --- qiynalish ------------------------------------------------------------


def test_two_weak_sessions_flag_struggling(user, topic):
    add_session(user, topic, correct=3, total=10, offset_minutes=1)
    add_session(user, topic, correct=4, total=10, offset_minutes=2)

    update = services.update_topic_progress(user, topic, 0.4)
    assert update.struggling is True

    hint = services.struggling_hint(user, topic)
    assert hint["review_material"] is True
    assert "Materialni" in hint["message"]


def test_struggling_hint_points_at_previous_topic(user, topic, topic2):
    add_session(user, topic2, correct=2, total=10, offset_minutes=1)
    add_session(user, topic2, correct=3, total=10, offset_minutes=2)

    hint = services.struggling_hint(user, topic2)
    assert hint["suggested_topic_id"] == topic.id


def test_no_struggling_hint_when_accuracy_is_fine(user, topic):
    add_session(user, topic, correct=7, total=10, offset_minutes=1)
    add_session(user, topic, correct=8, total=10, offset_minutes=2)
    assert services.struggling_hint(user, topic) is None


# --- mavzular ketma-ketligi ----------------------------------------------


def test_first_topic_unlocks_automatically(user, topic, topic2):
    services.ensure_bootstrapped(user)

    assert services.is_topic_accessible(user, topic) is True
    assert services.is_topic_accessible(user, topic2) is False


def test_bootstrap_does_not_reopen_after_progress_exists(user, topic, topic2):
    TopicProgress.objects.create(user=user, topic=topic2, status=TopicStatus.ACTIVE)
    services.ensure_bootstrapped(user)
    assert not TopicProgress.objects.filter(user=user, topic=topic).exists()


def test_draft_topic_is_never_accessible(user):
    from apps.content.models import ContentStatus
    from conftest import make_topic

    draft = make_topic(order=9, status=ContentStatus.DRAFT)
    assert services.is_topic_accessible(user, draft) is False
