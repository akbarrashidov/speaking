"""O'quvchi gapirmaganda hech narsa bo'lmasligi kerak.

Kuzatilgan xatti-harakat: o'quvchi jim turgan bo'lsa ham AI "eshitgan" gapini
tuzatib ketardi. Sababi quvurdagi teshik edi — `asr` jimlikni rad etardi-yu,
baholash Live'ning O'Z transkriptiga qaytardi, Live esa shovqinni ham matnga
aylantiradi. Bu yerda o'sha teshikning yopiqligi tekshiriladi.
"""

import asyncio
import base64
import json

import pytest
from channels.db import database_sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator

from apps.practice.consumer import MIN_TRUSTED_WORDS
from apps.practice.routing import websocket_urlpatterns
from apps.practice.services import start_session
from apps.users.jwt_utils import issue_token

application = URLRouter(websocket_urlpatterns)

# 1 soniya 16 kHz PCM16 jimlik.
SILENCE = base64.b64encode(b"\x00" * 32000).decode()


async def connect(user, topic):
    payload = await database_sync_to_async(start_session)(user, topic.id)
    token, _ = await database_sync_to_async(issue_token)(user)
    communicator = WebsocketCommunicator(
        application, f"/ws/session/{payload['session_id']}/?token={token}"
    )
    connected, _ = await communicator.connect()
    assert connected
    return communicator


async def settle(seconds=0.4):
    """Baholash quvuri (fon vazifasi) tugashini kutadi."""
    await asyncio.sleep(seconds)


@pytest.mark.django_db(transaction=True)
async def test_silence_is_never_graded(fake_gemini, fake_coach, user, adaptive_topic):
    """Mikrofonga faqat jimlik tushdi — model umuman chaqirilmaydi."""
    communicator = await connect(user, adaptive_topic)
    try:
        await settle(0.3)
        gemini = fake_gemini.instances[-1]
        before = len(gemini.directives)

        await communicator.send_to(text_data=json.dumps({"type": "speech_start"}))
        for _ in range(3):
            await communicator.send_to(
                text_data=json.dumps({"type": "audio_chunk", "data": SILENCE})
            )
        # Live shovqindan "gap" to'qidi — aynan shu holat xatoni keltirardi.
        await gemini.emit({"type": "input_transcript", "text": "the"})
        await communicator.send_to(text_data=json.dumps({"type": "speech_end"}))
        await asyncio.sleep(0.4)

        assert fake_coach.calls == [], "jimlik uchun coach chaqirildi"
        assert len(gemini.directives) == before, "jimlikdan keyin modelga ko'rsatma ketdi"
    finally:
        await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_cancelled_turn_leaves_no_trace(fake_gemini, fake_coach, user, adaptive_topic):
    """Klient VAD'i yanglishdi — navbat bekor qilinadi, hech narsa baholanmaydi."""
    communicator = await connect(user, adaptive_topic)
    try:
        await settle(0.3)
        gemini = fake_gemini.instances[-1]
        before = len(gemini.directives)

        await communicator.send_to(text_data=json.dumps({"type": "speech_start"}))
        await communicator.send_to(text_data=json.dumps({"type": "audio_chunk", "data": SILENCE}))
        await communicator.send_to(text_data=json.dumps({"type": "speech_cancel"}))
        await asyncio.sleep(0.3)

        assert fake_coach.calls == []
        assert len(gemini.directives) == before
    finally:
        await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_real_speech_still_gets_through(fake_gemini, fake_coach, user, adaptive_topic):
    """Darvoza qattiqlashdi, lekin haqiqiy gap baribir baholanadi."""
    communicator = await connect(user, adaptive_topic)
    try:
        await settle(0.3)
        gemini = fake_gemini.instances[-1]

        await communicator.send_to(text_data=json.dumps({"type": "speech_start"}))
        await asyncio.sleep(0.05)
        await gemini.emit(
            {"type": "input_transcript", "text": "I go to the bazaar every Sunday morning"}
        )
        await communicator.send_to(text_data=json.dumps({"type": "speech_end"}))
        await asyncio.sleep(0.4)

        assert fake_coach.calls, "haqiqiy gap baholanmadi"
    finally:
        await communicator.disconnect()


def test_short_live_text_is_not_trusted_when_grading_did_not_run():
    """Baholash ishlamagan navbatda Live'ning bir-ikki so'zi — shovqin."""
    from apps.practice.consumer import SessionConsumer

    trusted = SessionConsumer._trusted_text
    assert trusted(None, "", "the", dropped=True) == ""
    assert trusted(None, "", "uh the", dropped=True) == ""
    # Uzun matn haqiqiy nutq bo'lishi mumkin — u o'chirilmaydi.
    long_text = " ".join(["word"] * MIN_TRUSTED_WORDS)
    assert trusted(None, "", long_text, dropped=True) == long_text
    # Baholash ishlagan bo'lsa Live matni avvalgidek ishlatiladi.
    assert trusted(None, "", "the", dropped=False) == "the"
    # So'zma-so'z transkript hamma holatda ustun.
    assert trusted(None, "I went home", "the", dropped=True) == "I went home"
