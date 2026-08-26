"""§5.1 Gemini Live protokolining sim ustidagi shakli.

Bu testlar aynan JSON kalitlarini qotiradi. Sabab: `realtimeInput.mediaChunks`
eskirgani sababli server ulanishni 1007 bilan uzardi, mock klient ishlatgan
testlar esa buni sezmagan edi.
"""

import json

import pytest

from apps.practice.gemini import GeminiLiveClient, strip_director_leak


class FakeSocket:
    """Yuborilgan xabarlarni yig'adigan minimal WS o'rnini bosuvchi."""

    def __init__(self):
        self.sent = []

    async def send(self, raw):
        self.sent.append(json.loads(raw))


@pytest.fixture
def client():
    c = GeminiLiveClient("system prompt", api_key="k", model="m", voice="v")
    c._ws = FakeSocket()
    return c


@pytest.mark.asyncio
async def test_audio_chunk_uses_realtime_input_audio_blob(client, settings):
    settings.GEMINI_INPUT_SAMPLE_RATE = 16000
    await client.send_audio_chunk("QUJD")

    message = client._ws.sent[0]
    assert set(message) == {"realtimeInput"}

    realtime = message["realtimeInput"]
    assert "mediaChunks" not in realtime, "eskirgan maydon — server 1007 bilan uzadi"
    assert realtime["audio"] == {
        "mimeType": "audio/pcm;rate=16000",
        "data": "QUJD",
    }


@pytest.mark.asyncio
async def test_audio_stream_end_signal(client):
    await client.send_audio_stream_end()
    assert client._ws.sent[0] == {"realtimeInput": {"audioStreamEnd": True}}


@pytest.mark.asyncio
async def test_send_text_uses_client_content(client):
    await client.send_text("salom")
    assert client._ws.sent[0] == {
        "clientContent": {
            "turns": [{"role": "user", "parts": [{"text": "salom"}]}],
            "turnComplete": True,
        }
    }


# --- setup shakli (Faza 1) -------------------------------------------------


def setup_of(model: str, settings) -> dict:
    return GeminiLiveClient("sp", api_key="k", model=model, voice="v")._setup_message()["setup"]


def test_setup_enables_sliding_window_compression(settings):
    settings.GEMINI_COMPRESSION_TRIGGER_TOKENS = 8000
    setup = setup_of("gemini-3.1-flash-live-preview", settings)
    # Kontekst cheksiz o'smasin: aks holda uzun sessiyada har navbat qimmatlashadi.
    assert setup["contextWindowCompression"] == {
        "slidingWindow": {},
        "triggerTokens": "8000",
    }


def test_setup_requests_session_resumption(settings):
    setup = setup_of("gemini-3.1-flash-live-preview", settings)
    assert setup["sessionResumption"] == {}


def test_setup_passes_existing_resumption_handle(settings):
    client = GeminiLiveClient("sp", api_key="k", model="m", resumption_handle="h-42")
    assert client._setup_message()["setup"]["sessionResumption"] == {"handle": "h-42"}


def test_affective_dialog_only_on_native_audio(settings):
    """3.1 Flash Live bu bayroqni bilmaydi — yuborilsa ulanish rad etiladi."""
    settings.GEMINI_AFFECTIVE_DIALOG = True
    assert "enableAffectiveDialog" not in setup_of("gemini-3.1-flash-live-preview", settings)
    assert setup_of("gemini-2.5-flash-native-audio-preview-12-2025", settings)[
        "enableAffectiveDialog"
    ]


def test_affective_dialog_can_be_switched_off(settings):
    settings.GEMINI_AFFECTIVE_DIALOG = False
    assert "enableAffectiveDialog" not in setup_of(
        "gemini-2.5-flash-native-audio-preview-12-2025", settings
    )


def test_model_name_is_normalised(settings):
    client = GeminiLiveClient("sp", api_key="k", model="models/gemini-3.1-flash-live-preview")
    assert client.model == "gemini-3.1-flash-live-preview"
    assert client._setup_message()["setup"]["model"] == "models/gemini-3.1-flash-live-preview"


# --- direktiv kanali -------------------------------------------------------


@pytest.mark.asyncio
async def test_directive_uses_realtime_text_on_gemini_3():
    """3.x da `clientContent` faqat boshlang'ich kontekst uchun."""
    client = GeminiLiveClient("sp", api_key="k", model="gemini-3.1-flash-live-preview")
    client._ws = FakeSocket()
    await client.send_directive('Say exactly: "Nice."', tone="excited")
    assert client._ws.sent[0] == {
        "realtimeInput": {"text": '[DIRECTOR|tone=excited] Say exactly: "Nice."'}
    }


@pytest.mark.asyncio
async def test_directive_uses_client_content_on_gemini_25():
    client = GeminiLiveClient("sp", api_key="k", model="gemini-2.5-flash-native-audio")
    client._ws = FakeSocket()
    await client.send_directive("Ask the next question.")
    turn = client._ws.sent[0]["clientContent"]["turns"][0]
    assert turn["parts"][0]["text"] == "[DIRECTOR] Ask the next question."


@pytest.mark.asyncio
async def test_resumption_handle_is_captured_from_stream():
    client = GeminiLiveClient("sp", api_key="k", model="m")
    events = client._normalize({"sessionResumptionUpdate": {"newHandle": "abc"}})
    assert events == [{"type": "resumption_handle", "handle": "abc"}]
    assert client.resumption_handle == "abc"


# --- direktiv sizib chiqishi -----------------------------------------------
#
# Real regressiya: `realtimeInput.text` orqali kelgan ko'rsatmani model
# o'quvchi gapi deb qabul qilib, ovoz chiqarib o'qib yubordi. Ovozni ortga
# qaytarib bo'lmaydi, lekin ekran toza qolishi va logda signal chiqishi shart.


def test_clean_turn_passes_through_untouched():
    text, leaked = strip_director_leak("Nice introduction! Where are you from?")
    assert leaked is False
    assert text == "Nice introduction! Where are you from?"


def test_leaked_directive_is_cut_and_the_spoken_line_survives():
    spoken = (
        '[DIRECTOR] Say, "Okay." Then ask, "Where are you from?" word for word. '
        "Guidance: The learner should produce 'I am from...' Okay. Where are you from?"
    )
    text, leaked = strip_director_leak(spoken)
    assert leaked is True
    assert text == "Okay. Where are you from?"
    assert "DIRECTOR" not in text


def test_a_turn_that_is_only_a_directive_becomes_empty():
    text, leaked = strip_director_leak("[DIRECTOR|tone=warm] Ask the next question.")
    assert leaked is True
    assert text == ""
