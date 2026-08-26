"""So'zma-so'z transkript (§asr.py).

Bu modul mavjud bo'lishining yagona sababi: Gemini Live'ning o'z transkripti
o'quvchi gapini jimgina TO'G'RILAB beradi. "I from Uzbekistan" transkriptga
"I'm from Uzbekistan." bo'lib tushadi va grammatik xato butun zanjirdan
ko'rinmay o'tib ketadi. Shuning uchun bu yerdagi da'volar prompt matnigacha
qat'iy — u yumshasa, platforma grammatikani o'rgatishni bas qiladi.
"""

from __future__ import annotations

import base64
import json
import struct

import httpx
import pytest

from apps.practice import asr


class FakeResponse:
    def __init__(self, body: dict, status: int = 200):
        self._body = body
        self.status_code = status

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("xato", request=None, response=None)


def gemini_body(text: str, *, tokens=(120, 8)) -> dict:
    return {
        "candidates": [{"content": {"parts": [{"text": json.dumps({"text": text})}]}}],
        "usageMetadata": {"promptTokenCount": tokens[0], "candidatesTokenCount": tokens[1]},
    }


def speech(seconds: float = 2.0) -> bytes:
    """16 kHz, 16-bit mono — uzunlik va BALANDLIK ostonasidan o'tadigan signal.

    Amplituda muhim: nutqsiz bo'lak modelga umuman yuborilmaydi
    (§asr.is_silence), shuning uchun "nutq" namunasi jimlikdan baland.
    """
    return b"\x00\x40" * int(16000 * seconds)  # 16384 — nutq darajasi


@pytest.fixture
def capture(monkeypatch, settings):
    """`generateContent` so'rovini ushlaydi."""
    settings.ASR_ENABLED = True
    settings.GEMINI_API_KEY = "test-key"
    sent = {}

    class FakeClient:
        async def post(self, url, **kwargs):
            sent["url"] = url
            sent["params"] = kwargs.get("params") or {}
            sent["payload"] = kwargs.get("json") or {}
            sent["timeout"] = kwargs.get("timeout")
            return sent.pop("_response", None) or FakeResponse(gemini_body("I from Uzbekistan"))

    def fake_client():
        return FakeClient()

    monkeypatch.setattr(asr, "client", fake_client)
    return sent


class TestWavHeader:
    """`generateContent` xom PCM qabul qilmaydi — sarlavha qo'shiladi."""

    def test_header_declares_mono_16bit_at_the_given_rate(self):
        wav = asr.pcm16_to_wav(b"\x00\x01" * 100, 16000)
        assert wav[:4] == b"RIFF"
        assert wav[8:12] == b"WAVE"
        channels, rate, _, _, bits = struct.unpack("<HIIHH", wav[22:36])
        assert channels == 1
        assert rate == 16000
        assert bits == 16

    def test_sizes_match_the_payload(self):
        pcm = b"\x00\x01" * 100
        wav = asr.pcm16_to_wav(pcm, 16000)
        assert struct.unpack("<I", wav[4:8])[0] == 36 + len(pcm)
        assert struct.unpack("<I", wav[40:44])[0] == len(pcm)
        assert wav[44:] == pcm


class TestPrompt:
    """Ro'yxat to'liq bo'lishi shart — bitta shaklga moslash boshqasini yo'qotadi."""

    def test_prompt_forbids_any_smoothing(self):
        prompt = " ".join(asr.PROMPT.split())
        assert "NEVER add, remove or change a single word" in prompt
        assert "I from Uzbekistan" in prompt
        assert "every mistake you smooth over is a mistake they will never be taught" in prompt

    def test_every_error_family_is_named(self):
        prompt = " ".join(asr.PROMPT.split()).lower()
        for family in (
            "am, is, are",  # to be
            "do, does, did",  # yordamchi fe'llar
            "a, an, the",  # artikllar
            'plural "-s"',  # ko'plik
            'third-person "-s"',  # uchinchi shaxs
            'past "-ed"',  # o'tgan zamon
            "irregular forms",  # noto'g'ri fe'llar
            "prepositions",  # predloglar
            "missing subject",  # ega tushib qolishi
            "word order",  # so'z tartibi
            "subject-verb agreement",
        ):
            assert family.lower() in prompt, family

    def test_capitalisation_is_explicitly_not_the_learners(self):
        """Bosh harf eshitilmaydi — uni xato deb ko'rsatish o'quvchini chalg'itadi."""
        assert "cannot be heard" in asr.PROMPT


@pytest.mark.asyncio
class TestTranscribe:
    async def test_verbatim_text_is_returned_with_usage(self, capture, settings):
        text, usage = await asr.transcribe(speech())
        assert text == "I from Uzbekistan"
        # Model nomi sozlamadan olinadi — u o'zgarganda test yolg'on qizarmasin.
        assert usage == {"model": settings.ASR_MODEL, "in": 120, "out": 8}

    async def test_request_carries_the_audio_and_the_key(self, capture, settings):
        settings.ASR_MODEL = "gemini-2.5-flash"
        pcm = speech()
        await asr.transcribe(pcm)

        assert capture["url"].endswith("/v1beta/models/gemini-2.5-flash:generateContent")
        assert capture["params"] == {"key": "test-key"}

        parts = capture["payload"]["contents"][0]["parts"]
        assert "NEVER add, remove or change a single word" in parts[0]["text"]
        assert parts[1]["inlineData"]["mimeType"] == "audio/wav"
        assert base64.b64decode(parts[1]["inlineData"]["data"])[44:] == pcm

    async def test_thinking_is_switched_off(self, capture):
        """Bu eshitish vazifasi va har navbatda ishlaydi — o'ylash kechikish."""
        await asr.transcribe(speech())
        config = capture["payload"]["generationConfig"]
        assert config["thinkingConfig"]["thinkingBudget"] == 0
        assert config["temperature"] == 0
        assert config["responseMimeType"] == "application/json"

    async def test_disabled_flag_skips_the_call_entirely(self, capture, settings):
        settings.ASR_ENABLED = False
        assert await asr.transcribe(speech()) == ("", {})
        assert "url" not in capture

    async def test_missing_key_skips_the_call(self, capture, settings):
        settings.GEMINI_API_KEY = ""
        assert await asr.transcribe(speech()) == ("", {})
        assert "url" not in capture

    async def test_audio_shorter_than_half_a_second_is_noise(self, capture):
        assert await asr.transcribe(speech(0.2)) == ("", {})
        assert "url" not in capture

    async def test_http_error_falls_back_to_silence(self, capture, monkeypatch):
        class FailingClient:
            async def post(self, *args, **kwargs):
                raise httpx.ConnectError("tarmoq yo'q")

        monkeypatch.setattr(asr, "client", lambda: FailingClient())
        assert await asr.transcribe(speech()) == ("", {})

    async def test_unparseable_answer_falls_back_to_silence(self, capture):
        capture["_response"] = FakeResponse(
            {"candidates": [{"content": {"parts": [{"text": "hmm, I think they said..."}]}}]}
        )
        text, _ = await asr.transcribe(speech())
        assert text == ""

    async def test_empty_candidates_do_not_raise(self, capture):
        capture["_response"] = FakeResponse({"candidates": []})
        assert (await asr.transcribe(speech()))[0] == ""


class TestStructureFocus:
    """Mavzuga qaratilgan tinglash — "I from" / "I'm from" farqi shu yerda hal bo'ladi."""

    def test_to_be_lesson_gets_a_second_pass_on_that_form(self):
        prompt = asr.build_prompt("to_be_affirmative")
        assert "check that part of the audio twice" in prompt
        assert "am, is, are" in prompt
        assert "If you do not CLEARLY hear it, leave it out" in prompt

    def test_the_focus_does_not_replace_the_full_checklist(self):
        """Regressiya: bitta mavzuga moslash qolgan xatolarni ko'r qilardi."""
        prompt = asr.build_prompt("to_be_affirmative")
        assert "does not lower your attention on everything else" in prompt
        assert "a, an, the" in prompt
        assert "Word order exactly as spoken" in prompt

    def test_past_simple_lesson_points_at_the_ed_ending(self):
        assert '"-ed" ending' in asr.build_prompt("past_simple_affirmative")

    def test_unknown_structure_falls_back_to_the_plain_instruction(self):
        prompt = asr.build_prompt("something_we_have_not_mapped")
        assert "check that part of the audio twice" not in prompt
        assert "NEVER add, remove or change a single word" in prompt

    def test_no_structure_still_gets_the_full_checklist(self):
        prompt = asr.build_prompt("")
        assert "NEVER add, remove or change a single word" in prompt
        assert "a, an, the" in prompt


@pytest.mark.asyncio
async def test_target_structure_reaches_the_transcription_prompt(capture):
    await asr.transcribe(speech(), "to_be_affirmative")
    prompt = capture["payload"]["contents"][0]["parts"][0]["text"]
    assert "am, is, are" in prompt


class TestSilenceGate:
    """Nutqsiz bo'lak modelga umuman bormaydi — u javob TO'QIB beradi.

    O'lchangan xatti-harakat: jimlikka ham, shovqinga ham barcha sinalgan
    modellar "I am from Uzbekistan." kabi gap qaytardi. Bunday to'qima gap
    baholanadi va AI o'quvchi aytmagan gapni "tuzatadi" — shuning uchun
    chegara LLM'da emas, kodda.
    """

    def test_silence_is_detected(self):
        assert asr.is_silence(b"\x00\x00" * 24000)

    def test_empty_buffer_is_silence(self):
        assert asr.is_silence(b"")

    def test_room_noise_is_still_silence(self):
        """Mikrofon fon shovqini — ostonadan past."""
        assert asr.is_silence(b"\x0a\x00" * 24000)

    def test_speech_is_not_silence(self):
        assert not asr.is_silence(speech())

    @pytest.mark.asyncio
    async def test_silent_audio_never_reaches_the_model(self, capture):
        assert await asr.transcribe(b"\x00\x00" * 24000) == ("", {})
        assert "url" not in capture, "jimlik modelga yuborildi"
