"""§7.1 REST kontrakti."""

from django.urls import reverse
from django.utils import timezone

from apps.practice.models import Session, SessionStatus
from apps.progress.models import TopicProgress, TopicStatus
from apps.users import quota


def test_me_returns_profile_and_quota(auth_client, user):
    response = auth_client.get(reverse("me"))
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == user.email
    assert body["quota"]["remaining"] == 1
    assert body["quota"]["duration_seconds"] == 300


def test_topics_are_one_flat_list(auth_client, topic, topic2):
    """Darajalar yo'q — barcha grammatik mavzular bitta tartibda keladi."""
    body = auth_client.get(reverse("topics")).json()

    assert [t["order"] for t in body["topics"]] == [1, 2]
    assert "levels" not in body
    assert all("level" not in t for t in body["topics"])


def test_topics_expose_progress_status(auth_client, user, topic, topic2):
    body = auth_client.get(reverse("topics")).json()
    statuses = {t["order"]: t["status"] for t in body["topics"]}

    assert statuses[1] == "active"  # birinchi mavzu avtomatik ochiladi
    assert statuses[2] == "locked"


def test_material_endpoint_returns_rule_examples_and_chunks(auth_client, topic):
    body = auth_client.get(reverse("topic-material", args=[topic.id])).json()
    assert body["rule"]
    assert body["examples"][0]["en"]
    assert body["examples"][0]["tr"]
    assert body["chunks"][0]["text"] == "every day"
    assert body["accessible"] is True


def test_material_falls_back_to_uzbek_when_russian_is_missing(auth_client, user, topic):
    """Ruscha matn hali yozilmagan bo'lsa, o'quvchi bo'sh ekran ko'rmaydi."""
    user.language_code = "ru"
    user.save(update_fields=["language_code"])

    body = auth_client.get(reverse("topic-material", args=[topic.id])).json()
    assert body["rule"] == topic.material.rule_uz
    assert body["examples"][0]["tr"] == topic.material.examples[0]["uz"]


def test_material_is_served_in_the_learner_language(auth_client, user, topic):
    material = topic.material
    material.rule_ru = "Правило по-русски."
    material.examples = [
        {"en": "I live here.", "uz": "Men shu yerda yashayman.", "ru": "Я живу здесь."}
    ]
    material.save(update_fields=["rule_ru", "examples"])
    topic.title_ru = "Тема по-русски"
    topic.save(update_fields=["title_ru"])
    chunk = topic.chunks.first()
    chunk.translation_ru = "каждый день"
    chunk.save(update_fields=["translation_ru"])

    user.language_code = "ru"
    user.save(update_fields=["language_code"])

    body = auth_client.get(reverse("topic-material", args=[topic.id])).json()
    assert body["title"] == "Тема по-русски"
    assert body["rule"] == "Правило по-русски."
    assert body["examples"][0]["tr"] == "Я живу здесь."
    assert body["chunks"][0]["translation"] == "каждый день"

    topics = auth_client.get(reverse("topics")).json()["topics"]
    assert topics[0]["title"] == "Тема по-русски"


def test_start_session_returns_ws_url_and_limit(auth_client, user, topic):
    response = auth_client.post(reverse("sessions-start"), {"topic_id": topic.id}, format="json")
    assert response.status_code == 201
    body = response.json()

    assert body["ws_url"].endswith(f"/ws/session/{body['session_id']}/")
    assert body["time_limit_s"] == 300
    assert body["mode"] == "anticipation_drill"
    assert body["quota"]["remaining"] == 0
    assert Session.objects.get(pk=body["session_id"]).status == SessionStatus.ACTIVE


def test_start_session_blocked_when_quota_exhausted(auth_client, user, topic):
    quota.consume(user)
    response = auth_client.post(reverse("sessions-start"), {"topic_id": topic.id}, format="json")
    assert response.status_code == 402
    body = response.json()
    assert body["error"] == "quota_exceeded"
    assert body["next_available_at"]


def test_start_session_blocked_for_locked_topic(auth_client, user, topic, topic2):
    response = auth_client.post(reverse("sessions-start"), {"topic_id": topic2.id}, format="json")
    assert response.status_code == 403
    assert response.json()["error"] == "topic_locked"


def test_start_session_rejects_topic_without_approved_questions(auth_client, user):
    from conftest import make_topic

    empty = make_topic(order=5, questions=0)
    TopicProgress.objects.create(user=user, topic=empty, status=TopicStatus.ACTIVE)

    response = auth_client.post(reverse("sessions-start"), {"topic_id": empty.id}, format="json")
    assert response.status_code == 409
    assert response.json()["error"] == "no_questions"


def test_start_session_requires_topic_id(auth_client):
    response = auth_client.post(reverse("sessions-start"), {}, format="json")
    assert response.status_code == 400


def test_feedback_reports_processing_until_pipeline_finishes(auth_client, user, topic):
    session = Session.objects.create(
        user=user, topic=topic, mode="anticipation_drill", status=SessionStatus.PROCESSING
    )
    body = auth_client.get(reverse("sessions-feedback", args=[session.id])).json()
    assert body["status"] == "processing"


def test_feedback_returns_metrics_when_ready(auth_client, user, topic):
    from apps.practice.models import SessionMetrics

    session = Session.objects.create(
        user=user,
        topic=topic,
        mode="anticipation_drill",
        status=SessionStatus.DONE,
        duration_seconds=300,
    )
    SessionMetrics.objects.create(
        session=session,
        talk_time_seconds=150,
        talk_time_pct=50.0,
        wpm=42.5,
        avg_response_latency_ms=1800,
        questions_total=8,
        correct_total=7,
        first_attempt_correct=6,
        filler_count=3,
        feedback_summary_uz="Zo'r ish!",
        errors=[
            {"utterance": f"err {i}", "correction": f"fix {i}", "severity": "medium"}
            for i in range(8)
        ],
    )

    body = auth_client.get(reverse("sessions-feedback", args=[session.id])).json()
    assert body["status"] == "ready"
    assert body["metrics"]["first_attempt_accuracy"] == 75
    assert body["summary_uz"] == "Zo'r ish!"
    assert len(body["errors"]) == 5  # §4.10 — maksimum 5 ta


def test_feedback_is_not_visible_to_other_users(auth_client, topic):
    from apps.users.models import User

    stranger = User.objects.create_user(email="stranger@example.com")
    session = Session.objects.create(
        user=stranger, topic=topic, mode="anticipation_drill", status=SessionStatus.DONE
    )
    response = auth_client.get(reverse("sessions-feedback", args=[session.id]))
    assert response.status_code == 404


def test_end_session_marks_it_for_processing(auth_client, user, topic):
    session = Session.objects.create(
        user=user, topic=topic, mode="anticipation_drill", status=SessionStatus.ACTIVE
    )
    response = auth_client.post(reverse("sessions-end", args=[session.id]))
    assert response.status_code == 200
    session.refresh_from_db()
    assert session.status in (SessionStatus.PROCESSING, SessionStatus.DONE)


def test_progress_endpoint_lists_topics(auth_client, user, topic):
    TopicProgress.objects.create(user=user, topic=topic, status=TopicStatus.ACTIVE)
    body = auth_client.get(reverse("progress")).json()
    assert body["active_topic_id"] == topic.id
    assert body["topics"][0]["title"] == topic.title_uz


# --- saqlangan suhbat -----------------------------------------------------


def make_done_session(user, topic, *, turns=(), started_at=None, questions_total=0, correct=0):
    """Yakunlangan sessiya + ixtiyoriy transkript."""
    from apps.practice.models import SessionMetrics, SessionTurn

    session = Session.objects.create(
        user=user,
        topic=topic,
        mode="anticipation_drill",
        status=SessionStatus.DONE,
        duration_seconds=120,
        started_at=started_at or timezone.now(),
    )
    SessionMetrics.objects.create(
        session=session,
        questions_total=questions_total,
        first_attempt_correct=correct,
    )
    SessionTurn.objects.bulk_create(
        SessionTurn(
            session=session,
            idx=i + 1,
            speaker=speaker,
            text=text,
            started_at_ms=i * 1000,
            ended_at_ms=(i + 1) * 1000,
        )
        for i, (speaker, text) in enumerate(turns)
    )
    return session


def test_feedback_includes_the_saved_transcript(auth_client, user, topic):
    session = make_done_session(
        user,
        topic,
        turns=[("ai", "What do you do?"), ("learner", "I work in a bank"), ("ai", "Nice!")],
    )

    body = auth_client.get(reverse("sessions-feedback", args=[session.id])).json()
    assert [t["speaker"] for t in body["transcript"]] == ["ai", "learner", "ai"]
    assert body["transcript"][1]["text"] == "I work in a bank"
    assert body["transcript"][0]["idx"] == 1


def test_transcript_skips_turns_without_text(auth_client, user, topic):
    """Audio bor-u matn yo'q turn suhbatda bo'sh pufak yaratmasligi kerak."""
    session = make_done_session(
        user, topic, turns=[("ai", "Hello"), ("learner", "   "), ("ai", "")]
    )

    body = auth_client.get(reverse("sessions-feedback", args=[session.id])).json()
    assert len(body["transcript"]) == 1
    assert body["transcript"][0]["text"] == "Hello"


def test_session_history_is_newest_first_with_counts(auth_client, user, topic, topic2):
    from datetime import timedelta

    now = timezone.now()
    make_done_session(
        user,
        topic,
        turns=[("ai", "eski")],
        started_at=now - timedelta(days=1),
        questions_total=4,
        correct=2,
    )
    newer = make_done_session(
        user,
        topic2,
        turns=[("ai", "yangi"), ("learner", "javob")],
        started_at=now,
        questions_total=5,
        correct=5,
    )

    body = auth_client.get(reverse("sessions-list")).json()
    assert len(body["sessions"]) == 2

    first = body["sessions"][0]
    assert first["session_id"] == str(newer.id)
    assert first["title"] == topic2.title_uz
    assert first["turns_count"] == 2
    assert first["accuracy"] == 100
    assert body["sessions"][1]["accuracy"] == 50


def test_session_history_hides_unfinished_and_other_users_sessions(auth_client, user, topic):
    from apps.users.models import User

    make_done_session(user, topic, turns=[("ai", "meniki")])
    Session.objects.create(
        user=user, topic=topic, mode="anticipation_drill", status=SessionStatus.ACTIVE
    )
    stranger = User.objects.create_user(email="stranger2@example.com")
    make_done_session(stranger, topic, turns=[("ai", "begona")])

    body = auth_client.get(reverse("sessions-list")).json()
    assert len(body["sessions"]) == 1
    assert body["sessions"][0]["topic_id"] == topic.id


def test_session_history_survives_a_session_without_metrics(auth_client, user, topic):
    """Pipeline yiqilgan sessiya ro'yxatni buzmasligi kerak."""
    Session.objects.create(
        user=user,
        topic=topic,
        mode="anticipation_drill",
        status=SessionStatus.DONE,
        started_at=timezone.now(),
    )
    body = auth_client.get(reverse("sessions-list")).json()
    assert len(body["sessions"]) == 1
    assert body["sessions"][0]["accuracy"] is None
    assert body["sessions"][0]["questions_total"] == 0
