"""§4.8 — spaced repetition zinapoyasi: 1 → 3 → 7 kun."""

from datetime import timedelta

from django.utils import timezone

from apps.progress import spaced_repetition as sr
from apps.progress.models import ErrorLog


def make_error(user, topic, **kwargs):
    row = ErrorLog(
        user=user,
        topic=topic,
        target_structure="present_simple_affirmative",
        error_type=kwargs.pop("error_type", "wrong_tense"),
        learner_utterance=kwargs.pop("learner_utterance", "I go yesterday"),
        correction=kwargs.pop("correction", "I went yesterday"),
        **kwargs,
    )
    sr.schedule_new(row)
    row.save()
    return row


def test_new_error_is_scheduled_one_day_later(user, topic):
    now = timezone.now()
    row = make_error(user, topic)
    assert row.review_count == 0
    delta = row.next_review_at - now
    assert timedelta(hours=23) < delta < timedelta(hours=25)


def test_ladder_advances_1_3_7_then_resolves(user, topic):
    row = make_error(user, topic)
    now = timezone.now()

    sr.mark_reviewed(row, success=True, now=now)
    assert row.review_count == 1
    assert (row.next_review_at - now).days == 3

    sr.mark_reviewed(row, success=True, now=now)
    assert row.review_count == 2
    assert (row.next_review_at - now).days == 7

    sr.mark_reviewed(row, success=True, now=now)
    assert row.resolved is True
    assert row.next_review_at is None


def test_failure_resets_the_ladder(user, topic):
    row = make_error(user, topic)
    now = timezone.now()
    sr.mark_reviewed(row, success=True, now=now)
    sr.mark_reviewed(row, success=True, now=now)
    assert row.review_count == 2

    sr.mark_reviewed(row, success=False, now=now)
    assert row.review_count == 0
    assert (row.next_review_at - now).days == 1
    assert row.resolved is False


def test_only_due_items_are_returned(user, topic):
    due = make_error(user, topic, error_type="due_one")
    due.next_review_at = timezone.now() - timedelta(hours=1)
    due.save()

    make_error(user, topic, error_type="not_due")  # ertaga

    items = sr.due_items(user, topic=topic)
    assert [i.error_type for i in items] == ["due_one"]


def test_resolved_items_are_never_injected(user, topic):
    row = make_error(user, topic)
    row.next_review_at = timezone.now() - timedelta(days=1)
    row.resolved = True
    row.save()
    assert sr.due_items(user, topic=topic) == []


def test_injection_is_capped_at_three_items(user, topic):
    for i in range(6):
        row = make_error(user, topic, error_type=f"error_{i}")
        row.next_review_at = timezone.now() - timedelta(hours=i + 1)
        row.save()

    assert len(sr.due_items(user, topic=topic)) == 3


def test_injection_block_contains_learner_words(user, topic):
    row = make_error(user, topic)
    block = sr.build_injection_block([row])
    assert "I go yesterday" in block
    assert "I went yesterday" in block
    assert "Do not announce" in block


def test_empty_injection_block_for_no_items():
    assert sr.build_injection_block([]) == ""
