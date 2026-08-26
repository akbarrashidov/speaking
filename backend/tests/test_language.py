"""Ikki tillilik: interfeys emas, MAZMUN tili (§translate.py, §analysis.py).

Rus tilini tanlagan o'quvchi AI gapining tarjimasini ham, sessiya yakunidagi
xulosani ham ruscha ko'rishi kerak — aks holda tanlov yarim qoladi.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from apps.practice import analysis, translate
from apps.practice.services import start_session


@pytest.mark.django_db
class TestLanguageEndpoint:
    def test_language_is_saved_on_the_profile(self, auth_client, user):
        response = auth_client.post(reverse("me-language"), {"language": "ru"}, format="json")
        assert response.status_code == 200
        user.refresh_from_db()
        assert user.language_code == "ru"
        assert response.data["user"]["language_code"] == "ru"

    def test_unsupported_language_is_rejected(self, auth_client, user):
        response = auth_client.post(reverse("me-language"), {"language": "de"}, format="json")
        assert response.status_code == 400
        assert response.data["error"] == "unsupported_language"
        user.refresh_from_db()
        assert user.language_code != "de"


@pytest.mark.django_db
def test_session_carries_the_learner_language(user, topic):
    """Sessiya boshlanganda til meta'ga yoziladi — consumer shundan o'qiydi."""
    from apps.practice.store import SyncSessionStore

    user.language_code = "ru"
    user.save(update_fields=["language_code"])

    payload = start_session(user, topic.id)
    meta = SyncSessionStore(payload["session_id"]).get_meta()
    assert meta["learner_language"] == "ru"


class TestTranslationTarget:
    def test_russian_prompt_asks_for_russian(self):
        prompt = translate.system_prompt("ru")
        assert "Russian" in prompt
        assert "Uzbek" not in prompt

    def test_uzbek_stays_the_default(self):
        assert "Uzbek" in translate.system_prompt("uz")
        assert "Uzbek" in translate.system_prompt("")


class TestAnalysisLanguage:
    def test_feedback_prompt_follows_the_learner(self):
        russian = analysis._prompt(analysis._INTERPRET_PROMPT, "ru")
        assert "Russian-speaking learner" in russian
        assert 'addressed to the learner as "вы"' in russian

    def test_json_shape_survives_the_substitution(self):
        """Shablonda JSON qavslari bor — almashtirish ularni buzmasligi kerak."""
        uzbek = analysis._prompt(analysis._INTERPRET_PROMPT, "uz")
        assert '"patterns": [' in uzbek
        assert "{language}" not in uzbek and "{you}" not in uzbek
