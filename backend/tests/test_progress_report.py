"""Sessiyalararo umumiy tahlil (§Faza 7).

Asosiy da'vo: agregatsiya SQL'da bo'ladi (tekin va aniq), LLM esa faqat
o'zbekcha matn yozadi va natija keshlanadi.
"""

from __future__ import annotations

import itertools
import json
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone

from apps.practice import llm
from apps.practice.models import Session, SessionMetrics, SessionStatus
from apps.progress import report as report_mod
from apps.progress.models import ErrorLog


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


_session_seq = itertools.count()


def make_session(user, topic, *, accuracy=(4, 5)):
    correct, total = accuracy
    now = timezone.now()
    session = Session.objects.create(
        user=user,
        topic=topic,
        mode="anticipation_drill",
        status=SessionStatus.DONE,
        duration_seconds=120,
        started_at=now,
        ended_at=now,
    )
    # `created_at` (auto_now_add) soat aniqligiga bog'liq: bitta testda ketma-ket
    # yaratilgan ikki sessiya bir xil vaqt tamg'asini olishi va trend tartibi
    # beqaror bo'lib qolishi mumkin. Sekundlab ajratamiz.
    Session.objects.filter(pk=session.pk).update(
        created_at=now + timedelta(seconds=next(_session_seq))
    )
    SessionMetrics.objects.create(
        session=session, questions_total=total, first_attempt_correct=correct
    )
    return session


def log_error(user, topic, error_type, *, said="I go yesterday", better="I went yesterday"):
    return ErrorLog.objects.create(
        user=user,
        topic=topic,
        error_type=error_type,
        learner_utterance=said,
        correction=better,
    )


def patch_llm(monkeypatch, payload=None, *, fail=False):
    calls = []

    def fake_post(url, **kwargs):
        calls.append(kwargs)
        if fail:
            raise llm.httpx.ConnectError("tarmoq yo'q")

        class R:
            status_code = 200

            @staticmethod
            def json():
                return {
                    "choices": [{"message": {"content": json.dumps(payload or {})}}],
                    "usage": {"prompt_tokens": 200, "completion_tokens": 80},
                }

            @staticmethod
            def raise_for_status():
                return None

        return R()

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    return calls


GOOD = {
    "headline_uz": "O'tgan zamon shakli asosiy o'sish nuqtangiz.",
    "patterns_uz": ["Kecha haqida gapirganda 'went' deb ayting."],
    "encouragement_uz": "Aniqligingiz oshib bormoqda.",
    "focus_next_uz": "Keyingi sessiyada har javobni 'I went' bilan boshlang.",
}


# --- agregatsiya -----------------------------------------------------------


@pytest.mark.django_db
class TestAggregate:
    def test_counts_repeated_error_types(self, user, topic):
        make_session(user, topic)
        for _ in range(3):
            log_error(user, topic, "wrong_tense")
        log_error(user, topic, "missing_article")

        report = report_mod.aggregate(user)
        assert [(p["type"], p["count"]) for p in report.patterns] == [
            ("wrong_tense", 3),
            ("missing_article", 1),
        ]

    def test_example_comes_from_the_learners_own_words(self, user, topic):
        make_session(user, topic)
        log_error(user, topic, "wrong_tense", said="I go bazaar", better="I went to the bazaar")

        pattern = report_mod.aggregate(user).patterns[0]
        assert pattern["example"] == {"said": "I go bazaar", "better": "I went to the bazaar"}

    def test_accuracy_trend_is_per_session(self, user, topic):
        make_session(user, topic, accuracy=(2, 4))
        make_session(user, topic, accuracy=(4, 4))

        assert report_mod.aggregate(user).accuracy_trend == [50, 100]

    def test_session_without_questions_is_skipped_in_the_trend(self, user, topic):
        make_session(user, topic, accuracy=(0, 0))
        assert report_mod.aggregate(user).accuracy_trend == []

    def test_no_sessions_gives_an_empty_report(self, user):
        report = report_mod.aggregate(user)
        assert report.sessions == 0
        assert report.patterns == []


# --- o'zbekcha matn --------------------------------------------------------


@pytest.mark.django_db
class TestBuild:
    def test_too_few_sessions_says_so_without_calling_the_llm(
        self, user, topic, monkeypatch, settings
    ):
        settings.ANALYSIS_API_KEY = "k"
        calls = patch_llm(monkeypatch, GOOD)
        make_session(user, topic)
        log_error(user, topic, "wrong_tense")

        data = report_mod.build(user)
        assert calls == []
        assert "yana bir-ikki sessiya" in data["headline_uz"]

    def test_clean_history_is_celebrated_without_the_llm(self, user, topic, monkeypatch, settings):
        settings.ANALYSIS_API_KEY = "k"
        calls = patch_llm(monkeypatch, GOOD)
        make_session(user, topic)
        make_session(user, topic)

        data = report_mod.build(user)
        assert calls == []
        assert "Takrorlanadigan xato topilmadi" in data["headline_uz"]

    def test_uzbek_text_is_attached_to_the_counted_patterns(
        self, user, topic, monkeypatch, settings
    ):
        settings.ANALYSIS_API_KEY = "k"
        patch_llm(monkeypatch, GOOD)
        make_session(user, topic)
        make_session(user, topic)
        for _ in range(2):
            log_error(user, topic, "wrong_tense")

        data = report_mod.build(user)
        assert data["ok"] is True
        assert data["headline_uz"] == GOOD["headline_uz"]
        assert data["patterns"][0]["count"] == 2
        assert data["patterns"][0]["explain_uz"] == GOOD["patterns_uz"][0]

    def test_result_is_cached_so_the_llm_runs_once(self, user, topic, monkeypatch, settings):
        settings.ANALYSIS_API_KEY = "k"
        calls = patch_llm(monkeypatch, GOOD)
        make_session(user, topic)
        make_session(user, topic)
        log_error(user, topic, "wrong_tense")

        report_mod.build(user)
        report_mod.build(user)
        assert len(calls) == 1

    def test_new_data_invalidates_the_cache_by_itself(self, user, topic, monkeypatch, settings):
        """Kesh kaliti ma'lumot barmoq izidan — qo'lda tozalash kerak emas."""
        settings.ANALYSIS_API_KEY = "k"
        calls = patch_llm(monkeypatch, GOOD)
        make_session(user, topic)
        make_session(user, topic)
        log_error(user, topic, "wrong_tense")
        report_mod.build(user)

        log_error(user, topic, "wrong_tense")
        report_mod.build(user)
        assert len(calls) == 2

    def test_llm_failure_still_returns_the_counts(self, user, topic, monkeypatch, settings):
        settings.ANALYSIS_API_KEY = "k"
        patch_llm(monkeypatch, fail=True)
        make_session(user, topic)
        make_session(user, topic)
        log_error(user, topic, "wrong_tense")

        data = report_mod.build(user)
        assert data["ok"] is False
        assert data["patterns"][0]["type"] == "wrong_tense"
        assert data["headline_uz"] == report_mod.FALLBACK_HEADLINE

    def test_missing_api_key_does_not_crash(self, user, topic, settings):
        settings.ANALYSIS_API_KEY = ""
        make_session(user, topic)
        make_session(user, topic)
        log_error(user, topic, "wrong_tense")

        data = report_mod.build(user)
        assert data["headline_uz"] == report_mod.FALLBACK_HEADLINE


# --- endpoint --------------------------------------------------------------


@pytest.mark.django_db
def test_report_endpoint(auth_client, user, topic, monkeypatch, settings):
    settings.ANALYSIS_API_KEY = "k"
    patch_llm(monkeypatch, GOOD)
    make_session(user, topic)
    make_session(user, topic)
    log_error(user, topic, "wrong_tense")

    response = auth_client.get("/api/progress/report")
    assert response.status_code == 200
    assert response.json()["headline_uz"] == GOOD["headline_uz"]


@pytest.mark.django_db
def test_report_endpoint_requires_auth(client):
    assert client.get("/api/progress/report").status_code in (401, 403)
