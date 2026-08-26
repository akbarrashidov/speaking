"""Sessiya muhiti: shadowing videosi va rol suhbat sahnasi.

Bu yerda quvurning UCHLARI tekshiriladi: mavzudagi maydon klientga yetib
boradimi, va o'quvchi takroridan keyin baho hamda qisqa xulosa chiqadimi.
Baholash mantig'ining o'zi `test_shadow.py` da.
"""

import asyncio
import json

import pytest
from channels.db import database_sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator

from apps.content.models import Question, QuestionStatus, SessionMode, Topic, TopicTrack
from apps.practice.routing import websocket_urlpatterns
from apps.practice.services import start_session
from apps.practice.store import SyncSessionStore
from apps.users.jwt_utils import issue_token
from conftest import make_topic

application = URLRouter(websocket_urlpatterns)

LINES = [
    "Hey, how's it going?",
    "I'm good, thanks. What about you?",
]


def make_shadow_topic(*, media_url="", timings=True):
    topic = Topic.objects.create(
        track=TopicTrack.SHADOWING,
        order=1,
        title_uz="Shadowing mashqi",
        target_structure="shadow_test",
        session_mode=SessionMode.SHADOWING,
        status="published",
        max_questions=8,
        media_url=media_url,
    )
    for i, line in enumerate(LINES, start=1):
        Question.objects.create(
            topic=topic,
            order=i,
            question_text=f"Say this back to me: {line}",
            canonical_answer=line,
            status=QuestionStatus.APPROVED,
            clip_start_ms=(i - 1) * 4000 if timings else None,
            clip_end_ms=(i - 1) * 4000 + 2000 if timings else None,
        )
    return topic


def make_scene_topic():
    topic = Topic.objects.create(
        track=TopicTrack.ROLEPLAY,
        order=1,
        title_uz="Kafeda",
        target_structure="roleplay_test",
        session_mode=SessionMode.ROLEPLAY,
        status="published",
        persona_en="Rustam, a waiter in a busy cafe",
        setting_en="lunch rush, every table full",
        ambience="cafe",
        voice="Puck",
    )
    Question.objects.create(
        topic=topic,
        order=1,
        question_text="Order a drink.",
        canonical_answer="I'd like a coffee, please.",
        status=QuestionStatus.APPROVED,
    )
    return topic


# --- sessiya meta ---------------------------------------------------------


@pytest.mark.django_db
def test_shadow_session_carries_the_line_plan(user):
    topic = make_shadow_topic()
    payload = start_session(user, topic.id)
    meta = SyncSessionStore(payload["session_id"]).get_meta()

    assert meta["track"] == TopicTrack.SHADOWING
    plan = meta["shadow_lines"]
    assert [line["text"] for line in plan] == LINES
    assert plan[0]["start_ms"] == 0
    assert plan[0]["end_ms"] == 2000


@pytest.mark.django_db
def test_scene_reaches_the_session(user):
    topic = make_scene_topic()
    payload = start_session(user, topic.id)
    meta = SyncSessionStore(payload["session_id"]).get_meta()

    assert meta["persona"].startswith("Rustam")
    assert meta["ambience"] == "cafe"
    assert meta["voice"] == "Puck"
    # Sahna promptga ham tushadi — AI kim ekanini biladi.
    assert "Rustam" in meta["system_prompt"]
    assert "SCENE" in meta["system_prompt"]


@pytest.mark.django_db
def test_grammar_session_has_no_scene_and_no_lines(user):
    topic = make_topic(order=1)
    payload = start_session(user, topic.id)
    meta = SyncSessionStore(payload["session_id"]).get_meta()

    assert meta["shadow_lines"] == []
    assert meta["persona"] == ""
    assert meta["ambience"] == ""


@pytest.mark.django_db
def test_video_reaches_the_session(user):
    topic = make_shadow_topic(media_url="https://example.test/clip.mp4")
    payload = start_session(user, topic.id)
    meta = SyncSessionStore(payload["session_id"]).get_meta()
    assert meta["media_src"] == "https://example.test/clip.mp4"
    # Video bo'lsa AI gapni O'ZI aytmaydi — buni prompt aytib turadi.
    assert "RECORDING MODE" in meta["system_prompt"]
    # Va gaplar ro'yxati ham berilmaydi: bo'lsa, model uni o'qib yuboradi.
    assert "SESSION GOALS" not in meta["system_prompt"]
    assert LINES[0] not in meta["system_prompt"]


@pytest.mark.django_db
def test_without_video_the_ai_still_gets_the_lines(user):
    """Video yo'q — gapni AI aytadi, ya'ni ro'yxat unga kerak."""
    topic = make_shadow_topic()
    payload = start_session(user, topic.id)
    meta = SyncSessionStore(payload["session_id"]).get_meta()
    assert "SESSION GOALS" in meta["system_prompt"]
    assert LINES[0] in meta["system_prompt"]


# --- jonli sessiya --------------------------------------------------------


async def connect(user, topic):
    payload = await database_sync_to_async(start_session)(user, topic.id)
    token, _ = await database_sync_to_async(issue_token)(user)
    communicator = WebsocketCommunicator(
        application, f"/ws/session/{payload['session_id']}/?token={token}"
    )
    connected, _ = await communicator.connect()
    assert connected
    return communicator


async def wait_for(communicator, msg_type, limit=40):
    for _ in range(limit):
        message = json.loads(await communicator.receive_from(timeout=3))
        if message["type"] == msg_type:
            return message
    raise AssertionError(f"'{msg_type}' xabari kelmadi")


@pytest.mark.django_db(transaction=True)
async def test_session_ready_describes_the_scene(fake_gemini, user):
    topic = await database_sync_to_async(make_scene_topic)()
    communicator = await connect(user, topic)
    try:
        ready = await wait_for(communicator, "session_ready")
        assert ready["track"] == TopicTrack.ROLEPLAY
        assert ready["scene"]["ambience"] == "cafe"
        assert ready["scene"]["persona"].startswith("Rustam")
    finally:
        await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_session_ready_carries_the_shadow_lines(fake_gemini, user):
    topic = await database_sync_to_async(make_shadow_topic)()
    communicator = await connect(user, topic)
    try:
        ready = await wait_for(communicator, "session_ready")
        assert ready["track"] == TopicTrack.SHADOWING
        assert [line["text"] for line in ready["shadow_lines"]] == LINES
    finally:
        await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_repeating_a_line_is_scored_and_summed_up(fake_gemini, fake_coach, user):
    """O'quvchi gapni takrorladi — ekranga baho, ovozga bitta qisqa xulosa."""
    topic = await database_sync_to_async(make_shadow_topic)()
    communicator = await connect(user, topic)
    try:
        await wait_for(communicator, "session_ready")
        gemini = fake_gemini.instances[-1]
        # Klient birinchi klipni o'ynatdi va uzunligini o'lchadi.
        await communicator.send_to(
            text_data=json.dumps({"type": "shadow_line", "idx": 0, "reference_ms": 2000})
        )
        await communicator.send_to(text_data=json.dumps({"type": "speech_start"}))
        await asyncio.sleep(0.05)
        await gemini.emit({"type": "input_transcript", "text": LINES[0]})
        await communicator.send_to(text_data=json.dumps({"type": "speech_end"}))

        score = await wait_for(communicator, "shadow_score")
        assert score["idx"] == 0
        assert score["reference"] == LINES[0]
        assert score["word_accuracy"] == 1.0
        assert score["score"] >= 70
        # Xulosa bo'sh qolmaydi: model chaqirilmasa o'lchovlardan yoziladi.
        assert score["note"]
        # Ovozda ham aynan o'sha bitta jumla aytiladi.
        assert score["note"] in gemini.directives[-1]["text"]
    finally:
        await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_a_wrong_repeat_names_the_missing_word(fake_gemini, fake_coach, user):
    topic = await database_sync_to_async(make_shadow_topic)()
    communicator = await connect(user, topic)
    try:
        await wait_for(communicator, "session_ready")
        gemini = fake_gemini.instances[-1]
        await communicator.send_to(
            text_data=json.dumps({"type": "shadow_line", "idx": 1, "reference_ms": 2000})
        )
        await communicator.send_to(text_data=json.dumps({"type": "speech_start"}))
        await asyncio.sleep(0.05)
        await gemini.emit({"type": "input_transcript", "text": "I good thanks"})
        await communicator.send_to(text_data=json.dumps({"type": "speech_end"}))

        score = await wait_for(communicator, "shadow_score")
        assert score["idx"] == 1
        assert score["score"] < 75
        assert score["missed"]
    finally:
        await communicator.disconnect()
