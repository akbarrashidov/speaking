"""Tahlil LLM'ining HTTP qatlami — so'rov shakli va javob parsingi.

Pipeline testlarida `analyse_transcript` mock qilinadi, ya'ni sim ustidagi
so'rov hech qachon tekshirilmasdi. Provayder yoki model almashganda shu yer
yiqilishi kerak.
"""

import json

import httpx
import pytest

from apps.practice import analysis, llm


class FakeResponse:
    def __init__(self, body: dict, status: int = 200):
        self._body = body
        self.status_code = status

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("xato", request=None, response=None)


GOOD_JSON = json.dumps(
    {
        "errors": [
            {
                "utterance": "I go to school yesterday",
                "error_type": "wrong_tense",
                "correction": "I went to school yesterday",
                "severity": "medium",
            }
        ],
        "filler_examples": ["um"],
        "summary_uz": "Yaxshi ish. O'tgan zamon shakliga e'tibor bering.",
    }
)


def chat_body(content, *, reasoning=None):
    message = {"role": "assistant", "content": content}
    if reasoning is not None:
        message["reasoning_content"] = reasoning
    return {"choices": [{"message": message}]}


@pytest.fixture
def capture(monkeypatch, settings):
    """`httpx.post` ni ushlaydi va yuborilgan so'rovni qaytaradi."""
    settings.ANALYSIS_API_KEY = "test-key"
    sent = {}

    def fake_post(url, **kwargs):
        sent["url"] = url
        sent["headers"] = kwargs.get("headers") or {}
        sent["payload"] = kwargs.get("json") or {}
        return FakeResponse(sent.pop("_response", None) or chat_body(GOOD_JSON))

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    return sent


def test_request_targets_the_configured_openai_compatible_endpoint(capture, settings):
    settings.ANALYSIS_API_BASE = "https://api.fireworks.ai/inference/v1"
    settings.ANALYSIS_MODEL = "accounts/fireworks/models/gpt-oss-120b"

    analysis.analyse_transcript("LEARNER: I go yesterday", "past_simple", "A2")

    assert capture["url"] == "https://api.fireworks.ai/inference/v1/chat/completions"
    assert capture["headers"]["Authorization"] == "Bearer test-key"
    payload = capture["payload"]
    assert payload["model"] == "accounts/fireworks/models/gpt-oss-120b"
    assert payload["response_format"] == {"type": "json_object"}
    assert [m["role"] for m in payload["messages"]] == ["system", "user"]
    assert "past_simple" in payload["messages"][1]["content"]


def test_trailing_slash_in_base_url_does_not_double_up(capture, settings):
    settings.ANALYSIS_API_BASE = "https://api.fireworks.ai/inference/v1/"
    analysis.analyse_transcript("LEARNER: hi", "greetings")
    assert capture["url"] == "https://api.fireworks.ai/inference/v1/chat/completions"


def test_reasoning_effort_is_sent_when_configured(capture, settings):
    settings.ANALYSIS_REASONING_EFFORT = "low"
    analysis.analyse_transcript("LEARNER: hi", "greetings")
    assert capture["payload"]["reasoning_effort"] == "low"


def test_reasoning_effort_is_omitted_when_empty(capture, settings):
    """Buni qo'llab-quvvatlamaydigan provayder noma'lum maydondan 400 beradi."""
    settings.ANALYSIS_REASONING_EFFORT = ""
    analysis.analyse_transcript("LEARNER: hi", "greetings")
    assert "reasoning_effort" not in capture["payload"]


def test_result_is_parsed_and_normalised(capture):
    result = analysis.analyse_transcript("LEARNER: I go yesterday", "past_simple")

    assert result["ok"] is True
    assert result["errors"][0]["error_type"] == "wrong_tense"
    assert result["errors"][0]["correction"] == "I went to school yesterday"
    assert result["summary_uz"].startswith("Yaxshi ish")


def test_json_wrapped_in_a_code_fence_is_still_read(capture, monkeypatch):
    monkeypatch.setattr(
        llm.httpx,
        "post",
        lambda url, **kw: FakeResponse(chat_body(f"```json\n{GOOD_JSON}\n```")),
    )
    result = analysis.analyse_transcript("LEARNER: I go yesterday", "past_simple")
    assert result["ok"] is True
    assert result["errors"][0]["error_type"] == "wrong_tense"


def test_reasoning_content_is_used_when_content_is_empty(capture, monkeypatch):
    """gpt-oss ba'zan javobni faqat reasoning oqimida qaytaradi."""
    monkeypatch.setattr(
        llm.httpx,
        "post",
        lambda url, **kw: FakeResponse(chat_body("", reasoning=f"Let me think.\n{GOOD_JSON}")),
    )
    result = analysis.analyse_transcript("LEARNER: I go yesterday", "past_simple")
    assert result["ok"] is True
    assert result["errors"][0]["error_type"] == "wrong_tense"


def test_unparseable_answer_falls_back_without_raising(capture, monkeypatch):
    monkeypatch.setattr(
        llm.httpx, "post", lambda url, **kw: FakeResponse(chat_body("kechirasiz, JSON yo'q"))
    )
    result = analysis.analyse_transcript("LEARNER: hi", "greetings")
    assert result["ok"] is False
    assert result["errors"] == []
    assert result["summary_uz"] == analysis.FALLBACK_SUMMARY_UZ


def test_http_error_falls_back_without_raising(capture, monkeypatch):
    def boom(url, **kw):
        raise httpx.ConnectError("ulanmadi")

    monkeypatch.setattr(llm.httpx, "post", boom)
    result = analysis.analyse_transcript("LEARNER: hi", "greetings")
    assert result["ok"] is False
    assert result["summary_uz"] == analysis.FALLBACK_SUMMARY_UZ


def test_missing_api_key_skips_the_call_entirely(monkeypatch, settings):
    settings.ANALYSIS_API_KEY = ""

    def boom(url, **kw):
        raise AssertionError("kalitsiz so'rov yuborilmasligi kerak")

    monkeypatch.setattr(llm.httpx, "post", boom)
    result = analysis.analyse_transcript("LEARNER: hi", "greetings")
    assert result["ok"] is False


# --- kesilgan JSON'ni qutqarish --------------------------------------------
#
# Real hodisa: gpt-oss o'ylash tokenlarini ham `completion` hisobiga yozadi va
# `max_tokens` ga urilib javobni gap o'rtasida uzadi. Ilgari bu butun coach
# natijasini yo'q qilardi — har 5 chaqiruvdan biri `bad_json` edi.


def test_truncated_json_keeps_the_fields_that_arrived():
    raw = '{"verdict": "incorrect", "fluency": 2, "reaction": "Nice one!", "hint": "Start wi'
    data = llm.parse_json(raw)
    assert data == {"verdict": "incorrect", "fluency": 2, "reaction": "Nice one!"}


def test_truncated_nested_list_is_closed():
    raw = (
        '{"verdict": "incorrect", "errors": [{"span": "go", "fix": "went", "type": "t"},'
        ' {"span": "at monday"'
    )
    data = llm.parse_json(raw)
    assert data["verdict"] == "incorrect"
    assert data["errors"] == [{"span": "go", "fix": "went", "type": "t"}]


def test_truncation_inside_the_first_value_is_not_salvageable():
    assert llm.parse_json('{"verdict": "incor') is None


def test_prose_without_any_json_stays_unparseable():
    assert llm.parse_json("I think the learner did well today.") is None


def test_complete_json_is_untouched_by_the_salvage_path():
    data = llm.parse_json('{"verdict": "correct", "errors": []}')
    assert data == {"verdict": "correct", "errors": []}
