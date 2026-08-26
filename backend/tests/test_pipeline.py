"""§4.6 — post-session pipeline: metrikalar, idempotentlik, ErrorLog."""

import json

import pytest
from django.utils import timezone

from apps.practice import metrics as metrics_mod
from apps.practice.models import (
    EndReason,
    Evaluation,
    Session,
    SessionMetrics,
    SessionStatus,
    SessionTurn,
)
from apps.practice.tasks import process_session
from apps.progress.models import ErrorLog, TopicProgress

# --- deterministik metrikalar (§4.6.2) ------------------------------------


def test_talk_time_and_wpm_from_timestamps():
    turns = [
        {"speaker": "ai", "text": "What do you do?", "started_at_ms": 0, "ended_at_ms": 2000},
        {
            "speaker": "learner",
            "text": "I work in a shop every day",  # 7 so'z
            "started_at_ms": 3000,
            "ended_at_ms": 9000,  # 6 soniya
            "prev_ai_end_ms": 2000,
        },
    ]
    m = metrics_mod.compute_from_turns(turns, session_duration_seconds=20)

    assert m.talk_time_seconds == 6
    assert m.talk_time_pct == 30.0
    assert m.wpm == 70.0  # 7 so'z / 0.1 daqiqa
    assert m.avg_response_latency_ms == 1000  # 3000 - 2000


def test_latency_averages_across_turns_and_ignores_outliers():
    turns = [
        {
            "speaker": "learner",
            "started_at_ms": 1000,
            "ended_at_ms": 2000,
            "prev_ai_end_ms": 0,
            "text": "one",
        },
        {
            "speaker": "learner",
            "started_at_ms": 5000,
            "ended_at_ms": 6000,
            "prev_ai_end_ms": 2000,
            "text": "two",
        },
        # 60 soniyalik pauza — o'lchovga kirmaydi.
        {
            "speaker": "learner",
            "started_at_ms": 90000,
            "ended_at_ms": 91000,
            "prev_ai_end_ms": 20000,
            "text": "three",
        },
    ]
    m = metrics_mod.compute_from_turns(turns, session_duration_seconds=120)
    assert m.avg_response_latency_ms == 2000  # (1000 + 3000) / 2


def test_filler_words_are_counted_with_examples():
    turns = [
        {
            "speaker": "learner",
            "text": "um I think like you know it is um good",
            "started_at_ms": 0,
            "ended_at_ms": 5000,
        }
    ]
    m = metrics_mod.compute_from_turns(turns, session_duration_seconds=10)
    assert m.filler_count == 4
    assert "um" in m.filler_examples


def test_accuracy_uses_first_attempt_per_question():
    evaluations = [
        {"question_id": 1, "attempt": 1, "verdict": "correct"},
        {"question_id": 2, "attempt": 1, "verdict": "incorrect"},
        {"question_id": 2, "attempt": 2, "verdict": "correct"},
        {"question_id": 3, "attempt": 1, "verdict": "incorrect"},
        {"question_id": 3, "attempt": 2, "verdict": "incorrect"},
    ]
    m = metrics_mod.apply_evaluations(metrics_mod.ComputedMetrics(), evaluations)

    assert m.questions_total == 3
    assert m.correct_total == 2  # 1 va 2
    assert m.first_attempt_correct == 1  # faqat 1
    assert metrics_mod.first_attempt_accuracy(m) == pytest.approx(1 / 3)


def test_zero_questions_yields_zero_accuracy():
    m = metrics_mod.apply_evaluations(metrics_mod.ComputedMetrics(), [])
    assert metrics_mod.first_attempt_accuracy(m) == 0.0


# --- to'liq pipeline ------------------------------------------------------


def seed_redis_session(fake_redis, session, *, turns, evals, meta=None):
    key = f"sess:{session.id}"
    for turn in turns:
        fake_redis.rpush(f"{key}:turns", json.dumps(turn))
    for ev in evals:
        fake_redis.rpush(f"{key}:evals", json.dumps(ev))
    payload = {
        "target_structure": session.topic.target_structure,
        "mode": session.mode,
        **(meta or {}),
    }
    fake_redis.hset(f"{key}:meta", mapping={k: json.dumps(v) for k, v in payload.items()})


def make_finished_session(user, topic):
    return Session.objects.create(
        user=user,
        topic=topic,
        mode=topic.effective_mode,
        status=SessionStatus.PROCESSING,
        end_reason=EndReason.COMPLETED,
        started_at=timezone.now(),
        ended_at=timezone.now(),
        duration_seconds=300,
    )


SAMPLE_TURNS = [
    {"idx": 1, "speaker": "ai", "text": "What do you do?", "started_at_ms": 0, "ended_at_ms": 2000},
    {
        "idx": 2,
        "speaker": "learner",
        "text": "I work in a shop",
        "started_at_ms": 3000,
        "ended_at_ms": 8000,
        "prev_ai_end_ms": 2000,
    },
]


def sample_evals(question_ids):
    return [
        {
            "question_id": question_ids[0],
            "attempt": 1,
            "verdict": "correct",
            "learner_utterance": "I work in a shop",
        },
        {
            "question_id": question_ids[1],
            "attempt": 1,
            "verdict": "incorrect",
            "error_type": "wrong_tense",
            "learner_utterance": "I go yesterday",
        },
        {
            "question_id": question_ids[1],
            "attempt": 2,
            "verdict": "correct",
            "learner_utterance": "I went yesterday",
        },
    ]


def test_pipeline_persists_transcript_and_metrics(fake_redis, user, topic):
    session = make_finished_session(user, topic)
    qids = list(topic.questions.values_list("id", flat=True))
    seed_redis_session(fake_redis, session, turns=SAMPLE_TURNS, evals=sample_evals(qids))

    process_session.apply(args=[str(session.id)])

    session.refresh_from_db()
    assert session.status == SessionStatus.DONE
    assert SessionTurn.objects.filter(session=session).count() == 2
    assert Evaluation.objects.filter(session=session).count() == 3

    # Consumer bergan raqamlar saqlanadi — jonli va saqlangan suhbat bir xil.
    saved = SessionTurn.objects.filter(session=session).order_by("idx")
    assert [t.idx for t in saved] == [1, 2]
    assert [t.text for t in saved] == ["What do you do?", "I work in a shop"]

    metrics = SessionMetrics.objects.get(session=session)
    assert metrics.questions_total == 2
    assert metrics.correct_total == 2
    assert metrics.first_attempt_correct == 1
    assert metrics.talk_time_seconds == 5
    assert metrics.feedback_summary_uz  # LLM bo'lmasa ham fallback matn bor


def test_pipeline_is_idempotent(fake_redis, user, topic):
    """§4.6 — qayta ishga tushirilsa qatorlar dublikat bo'lmaydi."""
    session = make_finished_session(user, topic)
    qids = list(topic.questions.values_list("id", flat=True))
    seed_redis_session(fake_redis, session, turns=SAMPLE_TURNS, evals=sample_evals(qids))

    process_session.apply(args=[str(session.id)])
    first_progress = TopicProgress.objects.get(user=user, topic=topic)
    first_errors = ErrorLog.objects.filter(user=user).count()

    # Redis tozalangan bo'lsa ham qayta ishga tushirish xato bermasligi kerak.
    seed_redis_session(fake_redis, session, turns=SAMPLE_TURNS, evals=sample_evals(qids))
    process_session.apply(args=[str(session.id)])

    assert SessionTurn.objects.filter(session=session).count() == 2
    assert Evaluation.objects.filter(session=session).count() == 3
    assert SessionMetrics.objects.filter(session=session).count() == 1

    progress = TopicProgress.objects.get(user=user, topic=topic)
    assert progress.sessions_count == first_progress.sessions_count  # ikki marta sanalmadi
    assert ErrorLog.objects.filter(user=user).count() == first_errors


def test_pipeline_updates_topic_progress(fake_redis, user, topic):
    session = make_finished_session(user, topic)
    qids = list(topic.questions.values_list("id", flat=True))
    seed_redis_session(fake_redis, session, turns=SAMPLE_TURNS, evals=sample_evals(qids))

    process_session.apply(args=[str(session.id)])

    progress = TopicProgress.objects.get(user=user, topic=topic)
    assert progress.sessions_count == 1
    assert progress.last_accuracy == pytest.approx(0.5)


def test_pipeline_writes_error_logs_from_analysis(fake_redis, user, topic, monkeypatch):
    from apps.practice import analysis

    monkeypatch.setattr(
        analysis,
        "analyse_session",
        lambda *a, **kw: {
            "errors": [
                {
                    "utterance": "I go yesterday",
                    "error_type": "wrong_tense",
                    "correction": "I went yesterday",
                    "severity": "high",
                },
                {
                    "utterance": "very small mistake",
                    "error_type": "article",
                    "correction": "a very small mistake",
                    "severity": "low",  # low → ErrorLog'ga yozilmaydi
                },
            ],
            "filler_examples": ["um"],
            "summary_uz": "Yaxshi ish!",
            "ok": True,
        },
    )

    session = make_finished_session(user, topic)
    qids = list(topic.questions.values_list("id", flat=True))
    seed_redis_session(fake_redis, session, turns=SAMPLE_TURNS, evals=sample_evals(qids))

    process_session.apply(args=[str(session.id)])

    logs = ErrorLog.objects.filter(user=user)
    assert logs.count() == 1
    row = logs.first()
    assert row.error_type == "wrong_tense"
    assert row.next_review_at is not None
    assert SessionMetrics.objects.get(session=session).feedback_summary_uz == "Yaxshi ish!"


def test_pipeline_marks_injected_errors_reviewed(fake_redis, user, topic, monkeypatch):
    """§4.8 — kiritilgan xato takrorlanmasa, zinapoya oldinga siljiydi."""
    from apps.practice import analysis
    from apps.progress import spaced_repetition as sr

    old = ErrorLog(user=user, topic=topic, error_type="wrong_tense", correction="I went yesterday")
    sr.schedule_new(old)
    old.save()

    monkeypatch.setattr(
        analysis,
        "analyse_session",
        lambda *a, **kw: {"errors": [], "filler_examples": [], "summary_uz": "Zo'r!", "ok": True},
    )

    session = make_finished_session(user, topic)
    qids = list(topic.questions.values_list("id", flat=True))
    seed_redis_session(
        fake_redis,
        session,
        turns=SAMPLE_TURNS,
        evals=sample_evals(qids),
        meta={"injected_error_log_ids": [old.id]},
    )

    process_session.apply(args=[str(session.id)])

    old.refresh_from_db()
    assert old.review_count == 1  # muvaffaqiyatli takrorlash


def test_pipeline_survives_missing_session(db, fake_redis):
    result = process_session.apply(args=["00000000-0000-0000-0000-000000000000"])
    assert result.successful()


def test_pipeline_handles_empty_transcript(fake_redis, user, topic):
    session = make_finished_session(user, topic)
    seed_redis_session(fake_redis, session, turns=[], evals=[])

    process_session.apply(args=[str(session.id)])

    metrics = SessionMetrics.objects.get(session=session)
    assert metrics.questions_total == 0
    assert metrics.talk_time_seconds == 0
    session.refresh_from_db()
    assert session.status == SessionStatus.DONE


# --- ulanmagan sessiya kvotasi --------------------------------------------


def test_unstarted_session_refunds_quota_after_grace(fake_redis, user, topic):
    """Client WS ochmasa, kunlik kvota behuda yo'qolmaydi."""
    from apps.practice.services import start_session
    from apps.practice.tasks import abort_if_never_started
    from apps.users import quota

    payload = start_session(user, topic.id)
    assert quota.get_status(user).remaining == 0

    # Grace tugamagan — hech narsa qilinmaydi.
    abort_if_never_started.apply(args=[payload["session_id"]])
    assert quota.get_status(user).remaining == 0
    assert Session.objects.get(pk=payload["session_id"]).status == SessionStatus.ACTIVE

    # Grace tugadi va WS hech qachon ulanmadi.
    abort_if_never_started.apply(args=[payload["session_id"], 0])

    assert quota.get_status(user).remaining == 1
    assert Session.objects.get(pk=payload["session_id"]).status == SessionStatus.FAILED


def test_started_session_is_never_aborted(fake_redis, user, topic):
    from apps.practice.services import start_session
    from apps.practice.tasks import abort_if_never_started
    from apps.users import quota

    payload = start_session(user, topic.id)
    Session.objects.filter(pk=payload["session_id"]).update(started_at=timezone.now())

    abort_if_never_started.apply(args=[payload["session_id"], 0])

    assert quota.get_status(user).remaining == 0
    assert Session.objects.get(pk=payload["session_id"]).status == SessionStatus.ACTIVE
