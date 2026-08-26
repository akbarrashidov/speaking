"""Podkaska zinapoyasi (§Faza 4).

Ikki xil tekshiruv: sof zinapoya mantiqi (`hints.py`) va WS orqali haqiqiy
jimlik ssenariysi (consumer + taymer).
"""

from __future__ import annotations

import asyncio
import json

import pytest
from test_consumer import drain_until, last_directive, open_session, questions_of

from apps.practice import hints
from apps.practice import state as sm
from conftest import coach_result

# --- sof mantiq ------------------------------------------------------------


class TestLadder:
    def test_slower_speakers_get_more_time(self):
        assert hints.silence_seconds(0) > hints.silence_seconds(4)

    def test_unknown_register_has_a_default(self):
        assert hints.silence_seconds(None) == hints.DEFAULT_SILENCE_SECONDS
        assert hints.silence_seconds(99) == hints.DEFAULT_SILENCE_SECONDS

    def test_rungs_go_from_repeat_to_model_answer(self):
        assert [hints.rung(i).kind for i in (1, 2, 3)] == ["repeat", "opener", "model"]

    def test_out_of_range_rung_clamps_to_the_last(self):
        assert hints.rung(9).kind == "model"

    def test_first_rung_shows_nothing_on_screen(self):
        """Savol qaytadan aytiladi — ekranga yozish o'quvchini o'qishga o'tkazadi."""
        result = coach_result("unintelligible", hint="Start with: I", model_answer="I went.")
        assert hints.screen_text(1, result) == ""

    def test_second_rung_shows_the_opener(self):
        result = coach_result("unintelligible", hint="Start with: I went to...")
        assert hints.screen_text(2, result) == "Start with: I went to..."

    def test_third_rung_shows_the_full_answer(self):
        result = coach_result("unintelligible", model_answer="I went to the bazaar.")
        assert hints.screen_text(3, result) == "I went to the bazaar."

    def test_opener_directive_tells_the_model_not_to_finish_the_sentence(self):
        result = coach_result("unintelligible", hint="Start with: I went to...")
        instruction, tone = hints.directive_for(2, result, "What did you do?")
        assert "Start with: I went to..." in instruction
        assert "Do not say the rest of it yourself" in instruction
        assert tone == "slow_encouraging"

    def test_repeat_directive_reuses_the_question(self):
        instruction, _ = hints.directive_for(1, coach_result("unintelligible"), "Where?")
        assert "Where?" in instruction
        assert "more slowly" in instruction

    def test_model_directive_asks_for_repetition(self):
        result = coach_result("unintelligible", model_answer="I went home.")
        instruction, _ = hints.directive_for(3, result, "Where?")
        assert "Repeat after me" in instruction
        assert "I went home." in instruction


def test_new_question_resets_the_ladder():
    """Zinapoya savolga bog'liq — keyingi savolda noldan boshlanadi."""
    state = sm.SessionState(session_id="s", mode="anticipation_drill", question_ids=[1, 2])
    sm.start_question(state)
    state.hint_rung = 2
    state.stuck_count = 1

    sm.start_question(state)
    assert state.hint_rung == 0
    assert state.stuck_count == 0


# --- WS ssenariysi ---------------------------------------------------------


@pytest.fixture
def instant_hints(monkeypatch):
    """Jimlik taymerini testda kutib o'tirmaslik uchun nolga tushiramiz."""
    monkeypatch.setattr(hints, "silence_seconds", lambda level: 0.02)
    return hints


@pytest.mark.django_db(transaction=True)
async def test_silence_walks_up_the_ladder(fake_gemini, fake_coach, instant_hints, user, topic):
    communicator, _ = await open_session(user, topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]
    questions = await questions_of(topic)

    fake_coach.scripted.extend(
        [
            coach_result("unintelligible", hint="Start with: I work..."),
            coach_result("unintelligible", model_answer="I work in a bank."),
        ]
    )

    # Model gapirib bo'ldi, o'quvchi jim — zinapoya ishga tushadi.
    await gemini.emit({"type": "turn_complete"})

    first = await drain_until(communicator, "hint")
    assert first["rung"] == 1
    assert first["kind"] == "repeat"
    assert first["text"] == ""  # 1-pog'onada ekranga yozilmaydi
    assert questions[0].question_text in last_directive(gemini)

    second = await drain_until(communicator, "hint")
    assert second["rung"] == 2
    assert second["text"] == "Start with: I work..."

    third = await drain_until(communicator, "hint")
    assert third["rung"] == 3
    assert third["text"] == "I work in a bank."
    assert "Repeat after me" in last_directive(gemini)

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_first_rung_costs_nothing(fake_gemini, fake_coach, instant_hints, user, topic):
    """Savolni takrorlash uchun LLM kerak emas — savol matni allaqachon bizda."""
    communicator, _ = await open_session(user, topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    await gemini.emit({"type": "turn_complete"})
    await drain_until(communicator, "hint")

    assert fake_coach.calls == []
    await communicator.disconnect()


@pytest.fixture
def slow_hints(monkeypatch):
    """Bekor qilish testida taymer o'quvchidan tez ishlab ketmasligi kerak."""
    monkeypatch.setattr(hints, "silence_seconds", lambda level: 0.4)
    return hints


@pytest.mark.django_db(transaction=True)
async def test_speaking_cancels_the_ladder(fake_gemini, fake_coach, slow_hints, user, topic):
    communicator, _ = await open_session(user, topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    await gemini.emit({"type": "turn_complete"})
    await communicator.send_to(text_data=json.dumps({"type": "speech_start"}))
    # Taymer 0.4 s; ikki barobar kutamiz — bekor qilinmagan bo'lsa ishlagan bo'lardi.
    await asyncio.sleep(0.9)

    assert gemini.directives == [], "gapirayotgan o'quvchiga podkaska berilmasligi kerak"

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_persistent_silence_moves_on_instead_of_hanging(
    fake_gemini, fake_coach, instant_hints, user, topic
):
    """Ikki to'liq zinapoyadan keyin savol yopiladi — sessiya osilib qolmaydi."""
    from apps.practice.store import SyncSessionStore

    communicator, payload = await open_session(user, topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    await gemini.emit({"type": "turn_complete"})
    for _ in range(6):
        await drain_until(communicator, "hint")
        # Har pog'onadan keyin model gapiradi va taymer qayta qo'yiladi.
        await gemini.emit({"type": "turn_complete"})

    state = SyncSessionStore(payload["session_id"]).load_state()
    assert state.stuck_count >= hints.MAX_STUCK_BEFORE_MOVING_ON

    await communicator.disconnect()
