"""Real vaqtdagi coach (§Faza 2) — `apps/practice/coach.py`.

Diqqat markazi: coach hech qachon sessiyani yiqitmasligi kerak. LLM nima
qaytarsa ham (bo'sh, buzuq, o'ylab topilgan maydonlar) natija ishonchli
shaklga keltiriladi.
"""

from __future__ import annotations

import json

import httpx
import pytest

from apps.practice import coach, llm


class FakeResponse:
    def __init__(self, body, status=200):
        self._body = body
        self.status_code = status

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("xato", request=None, response=None)


def chat_body(content: str, prompt_tokens=400, completion_tokens=120):
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }


GOOD_ANSWER = {
    "verdict": "incorrect",
    "target_structure_used": False,
    "errors": [
        {
            "span": "I go yesterday",
            "fix": "I went yesterday",
            "type": "wrong_tense",
            "severity": "medium",
        }
    ],
    "fluency": 2,
    "reaction": "Ooh, the bazaar!",
    "hint": 'Start with: "I went to..."',
    "model_answer": "I went to the bazaar yesterday.",
    "next_question": "What did you buy there?",
    "tone": "slow_encouraging",
}


@pytest.fixture
def coach_api(settings):
    settings.COACH_API_KEY = "k"
    settings.COACH_API_BASE = "https://llm.test/v1"
    settings.COACH_MODEL = "test-coach"
    settings.COACH_TIMEOUT_SECONDS = 5
    settings.COACH_REASONING_EFFORT = "low"
    settings.COACH_MAX_TOKENS = 700
    return settings


def patch_post(monkeypatch, handler):
    async def fake_post(self, url, **kwargs):
        return handler(url, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)


def ctx(**overrides) -> coach.CoachContext:
    base = {
        "register": 2,
        "target_structure": "past_simple_affirmative",
        "mode": "anticipation_drill",
        "question_text": "What did you do yesterday?",
        "canonical_answer": "I went to the bazaar.",
        "attempt": 1,
        "learner_utterance": "I go yesterday to bazaar",
    }
    base.update(overrides)
    return coach.CoachContext(**base)


# --- baxtli yo'l -----------------------------------------------------------


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_full_result_is_parsed(self, coach_api, monkeypatch):
        patch_post(monkeypatch, lambda url, **kw: FakeResponse(chat_body(json.dumps(GOOD_ANSWER))))
        result = await coach.evaluate(ctx())

        assert result.ok
        assert result.verdict == "incorrect"
        assert result.target_structure_used is False
        assert result.errors[0]["type"] == "wrong_tense"
        assert result.error_type == "wrong_tense"
        assert result.next_question == "What did you buy there?"
        assert result.tone == "slow_encouraging"

    @pytest.mark.asyncio
    async def test_usage_is_reported_for_costing(self, coach_api, monkeypatch):
        patch_post(monkeypatch, lambda url, **kw: FakeResponse(chat_body(json.dumps(GOOD_ANSWER))))
        result = await coach.evaluate(ctx())
        assert result.usage == {"model": "test-coach", "in": 400, "out": 120}

    @pytest.mark.asyncio
    async def test_request_shape(self, coach_api, monkeypatch):
        seen = {}

        def handler(url, **kw):
            seen["url"] = url
            seen["json"] = kw["json"]
            seen["headers"] = kw["headers"]
            return FakeResponse(chat_body(json.dumps(GOOD_ANSWER)))

        patch_post(monkeypatch, handler)
        await coach.evaluate(ctx())

        assert seen["url"] == "https://llm.test/v1/chat/completions"
        assert seen["headers"]["Authorization"] == "Bearer k"
        assert seen["json"]["model"] == "test-coach"
        assert seen["json"]["response_format"] == {"type": "json_object"}
        assert seen["json"]["reasoning_effort"] == "low"
        # O'quvchi javobi promptga tushgan bo'lishi shart.
        assert "I go yesterday to bazaar" in seen["json"]["messages"][1]["content"]


# --- ishonchsiz chiqishlar -------------------------------------------------


class TestNormalisation:
    def test_unknown_verdict_becomes_unintelligible(self):
        assert coach.normalize({"verdict": "brilliant"}).verdict == "unintelligible"

    def test_unknown_tone_falls_back_to_warm(self):
        assert coach.normalize({"tone": "sarcastic"}).tone == "warm"

    def test_fluency_is_clamped(self):
        assert coach.normalize({"fluency": 99}).fluency == 4
        assert coach.normalize({"fluency": -3}).fluency == 0
        assert coach.normalize({"fluency": "yo'q"}).fluency == 0

    def test_errors_are_capped_at_five(self):
        """Uchta edi — gapirish platformasida aytilmagan xato yillar qoladi."""
        raw = {
            "errors": [{"span": f"s{i}", "fix": f"f{i}", "type": "wrong_tense"} for i in range(9)]
        }
        assert len(coach.normalize(raw).errors) == 5

    def test_error_without_a_real_correction_is_dropped(self):
        """`span == fix` — model xato o'ylab topgan, o'quvchiga ko'rsatilmaydi."""
        raw = {
            "errors": [
                {"span": "I went", "fix": "I went", "type": "wrong_tense"},
                {"span": "", "fix": "something", "type": "x"},
                {"span": "at monday", "fix": "on Monday", "type": "wrong_preposition"},
            ]
        }
        errors = coach.normalize(raw).errors
        assert len(errors) == 1
        assert errors[0]["fix"] == "on Monday"

    def test_error_type_is_slugified(self):
        raw = {"errors": [{"span": "a", "fix": "b", "type": "Wrong Tense!"}]}
        assert coach.normalize(raw).errors[0]["type"] == "wrong_tense"

    def test_missing_error_type_gets_a_label(self):
        raw = {"errors": [{"span": "a", "fix": "b"}]}
        assert coach.normalize(raw).errors[0]["type"] == "unclassified"

    def test_bad_severity_becomes_medium(self):
        raw = {"errors": [{"span": "a", "fix": "b", "type": "t", "severity": "catastrophic"}]}
        assert coach.normalize(raw).errors[0]["severity"] == "medium"

    def test_multiline_text_is_flattened(self):
        """Direktivga bir qatorli matn ketadi — yangi qatorlar buzadi."""
        out = coach.normalize({"reaction": "Nice!\n\n  Really nice.  "})
        assert out.reaction == "Nice! Really nice."

    def test_empty_payload_is_safe(self):
        out = coach.normalize({})
        assert out.verdict == "unintelligible"
        assert out.errors == []
        assert out.error_type == ""
        assert out.tone == "warm"

    def test_non_dict_errors_are_ignored(self):
        assert coach.normalize({"errors": ["nope", 42, None]}).errors == []


class TestAnswerOptions:
    """Qotib qolgan o'quvchi ekrandan o'qib aytadigan javoblar (§Faza 4)."""

    def test_options_are_parsed_with_their_translation(self):
        raw = {
            "options": [
                {"en": "I went to the bazaar.", "uz": "Men bozorga bordim."},
                {"en": "I stayed at home.", "uz": "Men uyda qoldim."},
            ]
        }
        options = coach.normalize(raw).options
        assert options == [
            {"en": "I went to the bazaar.", "uz": "Men bozorga bordim."},
            {"en": "I stayed at home.", "uz": "Men uyda qoldim."},
        ]

    def test_options_are_capped_at_three(self):
        raw = {"options": [{"en": f"Answer {i}.", "uz": f"Javob {i}."} for i in range(9)]}
        assert len(coach.normalize(raw).options) == 3

    def test_option_without_english_is_dropped(self):
        """O'quvchi aytadigan gap inglizcha — tarjimasiz ham ishlaydi, aksi yo'q."""
        raw = {"options": [{"uz": "Men uyda qoldim."}, {"en": "I stayed at home."}]}
        assert coach.normalize(raw).options == [{"en": "I stayed at home.", "uz": ""}]

    def test_missing_options_is_an_empty_list(self):
        assert coach.normalize({}).options == []


# --- fallback: sessiya hech qachon to'xtamaydi -----------------------------


class TestFallback:
    @pytest.mark.asyncio
    async def test_no_api_key_skips_the_call(self, coach_api, monkeypatch):
        coach_api.COACH_API_KEY = ""

        def boom(url, **kw):
            raise AssertionError("kalitsiz so'rov yuborilmasligi kerak")

        patch_post(monkeypatch, boom)
        result = await coach.evaluate(ctx())
        assert result.ok is False
        assert result.error == "no_api_key"

    @pytest.mark.asyncio
    async def test_timeout_returns_usable_fallback(self, coach_api, monkeypatch):
        async def fake_post(self, url, **kwargs):
            raise httpx.ReadTimeout("juda sekin")

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        result = await coach.evaluate(ctx())

        assert result.ok is False
        assert result.verdict == "unintelligible"
        # Podkaska baribir bo'lishi kerak — o'quvchi jimlikda qolmasin.
        assert result.hint
        assert result.tone == "slow_encouraging"

    @pytest.mark.asyncio
    async def test_http_error_does_not_raise(self, coach_api, monkeypatch):
        patch_post(monkeypatch, lambda url, **kw: FakeResponse({}, status=500))
        result = await coach.evaluate(ctx())
        assert result.ok is False

    @pytest.mark.asyncio
    async def test_unparseable_answer_does_not_raise(self, coach_api, monkeypatch):
        patch_post(monkeypatch, lambda url, **kw: FakeResponse(chat_body("kechirasiz, JSON yo'q")))
        result = await coach.evaluate(ctx())
        assert result.ok is False
        assert result.error == "bad_json"

    @pytest.mark.asyncio
    async def test_code_fenced_json_is_recovered(self, coach_api, monkeypatch):
        fenced = "```json\n" + json.dumps(GOOD_ANSWER) + "\n```"
        patch_post(monkeypatch, lambda url, **kw: FakeResponse(chat_body(fenced)))
        result = await coach.evaluate(ctx())
        assert result.ok
        assert result.verdict == "incorrect"

    @pytest.mark.asyncio
    async def test_reasoning_content_is_used_when_content_is_empty(self, coach_api, monkeypatch):
        body = {
            "choices": [{"message": {"content": "", "reasoning_content": json.dumps(GOOD_ANSWER)}}],
            "usage": {},
        }
        patch_post(monkeypatch, lambda url, **kw: FakeResponse(body))
        result = await coach.evaluate(ctx())
        assert result.ok


# --- kontekst prompti ------------------------------------------------------


class TestContextPrompt:
    def test_recent_turns_are_trimmed(self):
        turns = [{"speaker": "learner", "text": f"turn {i}"} for i in range(20)]
        prompt = ctx(recent_turns=turns).to_user_prompt()
        assert "turn 19" in prompt
        assert "turn 0" not in prompt

    def test_blank_turns_are_dropped(self):
        prompt = ctx(recent_turns=[{"speaker": "ai", "text": "   "}]).to_user_prompt()
        assert json.loads(prompt)["recent_conversation"] == []

    def test_silent_mode_asks_for_scaffolding(self):
        prompt = json.loads(ctx(silent=True, learner_utterance="").to_user_prompt())
        assert prompt["learner_said"] == ""
        assert "silent" in prompt["note"]

    def test_structure_miss_streak_reaches_the_model(self):
        prompt = json.loads(ctx(structure_miss_streak=2).to_user_prompt())
        assert prompt["structure_miss_streak"] == 2


# --- umumiy llm klienti ----------------------------------------------------


class TestSharedClient:
    def test_reasoning_effort_omitted_when_blank(self):
        payload = llm.build_payload(model="m", system="s", user="u", reasoning_effort="")
        assert "reasoning_effort" not in payload

    def test_max_tokens_omitted_when_zero(self):
        payload = llm.build_payload(model="m", system="s", user="u", max_tokens=0)
        assert "max_tokens" not in payload

    def test_parse_json_survives_prose_around_the_object(self):
        assert llm.parse_json('bu javob: {"a": 1} rahmat') == {"a": 1}

    def test_parse_json_rejects_a_list(self):
        assert llm.parse_json("[1, 2, 3]") is None

    def test_parse_json_rejects_nonsense(self):
        assert llm.parse_json("umuman JSON emas") is None
