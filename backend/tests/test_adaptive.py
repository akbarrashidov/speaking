"""AI suhbat registri va ohang (§Faza 6 → ko'zgu registri).

`adaptive.py` sof funksiyalardan iborat va LLM chaqirmaydi — moslashuv tekin
bo'lishi kerak, aks holda uni har javobda ishlatib bo'lmaydi.

Registrning ma'nosi: AI o'quvchi qanday gapirsa, shunday gapiradi. Shuning
uchun maqsad — o'quvchining o'z ravonligi (`avg_fluency`), tanlangan daraja
emas: darajalar tizimda umuman yo'q.
"""

from __future__ import annotations

import pytest

from apps.practice import adaptive
from apps.practice import state as sm


def fluent(**kwargs) -> adaptive.Signals:
    """Ravon gapiruvchi: uzun gaplar, xatolar kam."""
    base = {
        "answered": 5,
        "first_attempt_accuracy": 0.9,
        "avg_fluency": 4.0,
        "structure_hit_rate": 1.0,
        "stuck_count": 0,
    }
    base.update(kwargs)
    return adaptive.Signals(**base)


class TestMirroringUp:
    def test_fluent_learner_pulls_the_register_up(self):
        assert adaptive.next_register(2, fluent()) == 3

    def test_it_moves_one_step_at_a_time(self):
        """Sakrash o'quvchini chalg'itadi — har baholashda ko'pi bilan bitta qadam."""
        register = 0
        for _ in range(10):
            register = adaptive.next_register(register, fluent())
        assert register == adaptive.MAX_REGISTER

    def test_it_stops_at_the_ceiling(self):
        assert adaptive.next_register(adaptive.MAX_REGISTER, fluent()) == adaptive.MAX_REGISTER

    def test_short_answers_do_not_raise_the_register(self):
        """Aniq, lekin qisqa javob — bu hali "ravon gapiryapti" degani emas."""
        assert adaptive.next_register(1, fluent(avg_fluency=1.2)) == 1

    def test_fluent_but_full_of_errors_does_not_rise(self):
        """Tez gapirish tushunish emas: xato ko'p bo'lsa registr ko'tarilmaydi."""
        assert adaptive.next_register(2, fluent(first_attempt_accuracy=0.3)) == 2

    def test_no_change_before_enough_answers(self):
        assert adaptive.next_register(2, fluent(answered=2)) == 2


class TestMirroringDown:
    def test_shorter_answers_pull_the_register_down(self):
        assert adaptive.next_register(3, fluent(avg_fluency=1.0)) == 2

    def test_getting_stuck_moves_down_immediately(self):
        assert adaptive.next_register(3, fluent(stuck_count=2)) == 2

    def test_demotion_stops_at_the_floor(self):
        floor = adaptive.MIN_REGISTER
        assert adaptive.next_register(floor, fluent(avg_fluency=0.0)) == floor

    def test_demotion_also_waits_for_enough_answers(self):
        assert adaptive.next_register(2, fluent(answered=1, avg_fluency=0.0)) == 2

    def test_getting_stuck_beats_fluency_when_both_would_apply(self):
        """Qiynalayotgan o'quvchi bilan tezlashish eng yomon xato."""
        assert adaptive.next_register(2, fluent(stuck_count=3)) == 1

    def test_register_settles_where_the_learner_speaks(self):
        """Maqsad — o'quvchining o'z darajasi, undan baland ham, past ham emas."""
        signals = fluent(avg_fluency=2.0)
        register = 0
        for _ in range(10):
            register = adaptive.next_register(register, signals)
        assert register == 2


class TestSignalsFromState:
    def make_state(self, **kwargs):
        state = sm.SessionState(session_id="s", mode="anticipation_drill", question_ids=[1, 2, 3])
        for key, value in kwargs.items():
            setattr(state, key, value)
        return state

    def test_empty_session_gives_neutral_signals(self):
        signals = adaptive.signals_from_state(self.make_state(), [])
        assert signals.answered == 0
        assert signals.first_attempt_accuracy == 0.0

    def test_accuracy_uses_first_attempt_only(self):
        state = self.make_state(asked_total=4, first_attempt_correct=3)
        assert adaptive.signals_from_state(state, [3, 3]).first_attempt_accuracy == pytest.approx(
            0.75
        )

    def test_fluency_is_averaged_over_the_recent_window(self):
        state = self.make_state(asked_total=3)
        assert adaptive.signals_from_state(state, [4, 2]).avg_fluency == pytest.approx(3.0)

    def test_silent_answers_lower_the_structure_hit_rate(self):
        state = self.make_state(asked_total=4)
        assert adaptive.signals_from_state(state, [0, 0, 3, 3]).structure_hit_rate == pytest.approx(
            0.5
        )

    def test_answered_can_be_overridden_for_free_conversation(self):
        """Erkin suhbatda savol "berilmaydi" — o'lchov birligi baholangan navbat.

        `asked_total` u yerda 1 da qotib qoladi; override bo'lmasa registr hech
        qachon o'zgarmasdi (MIN_SAMPLES ga yetib bormaydi).
        """
        state = self.make_state(
            mode="adaptive_conversation",
            asked_total=1,
            evaluated_total=6,
            first_attempt_correct=3,
        )
        assert adaptive.signals_from_state(state, [3, 3]).answered == 1
        overridden = adaptive.signals_from_state(state, [3, 3], answered=state.evaluated_total)
        assert overridden.answered == 6
        assert overridden.first_attempt_accuracy == pytest.approx(0.5)


class TestTone:
    def test_struggling_learner_hears_calm(self):
        assert adaptive.tone_for(0, "incorrect", 1) == "slow_encouraging"
        assert adaptive.tone_for(2, "correct", 4, stuck=True) == "slow_encouraging"

    def test_strong_answer_gets_real_excitement(self):
        assert adaptive.tone_for(0, "correct", 4) == "excited"

    def test_top_register_gets_a_lighter_tone(self):
        assert adaptive.tone_for(adaptive.MAX_REGISTER, "correct", 4) == "playful"

    def test_ordinary_answer_stays_warm(self):
        assert adaptive.tone_for(0, "correct", 2) == "warm"


class TestRegisterText:
    def test_every_register_has_an_instruction(self):
        for value in range(adaptive.MIN_REGISTER, adaptive.MAX_REGISTER + 1):
            assert adaptive.pacing_clause(value).strip()

    def test_low_register_asks_for_the_simplest_english(self):
        assert "simplest English" in adaptive.pacing_clause(0)

    def test_top_register_asks_for_reasons_and_details(self):
        assert "reasons" in adaptive.pacing_clause(adaptive.MAX_REGISTER)

    def test_out_of_range_is_clamped_not_crashed(self):
        assert adaptive.pacing_clause(99) == adaptive.pacing_clause(adaptive.MAX_REGISTER)
        assert adaptive.clamp(-5) == adaptive.MIN_REGISTER
        assert adaptive.clamp("nonsense") == adaptive.DEFAULT_REGISTER

    def test_block_tells_the_model_to_follow_the_learner(self):
        block = " ".join(adaptive.register_block(2).split())
        assert "There is no fixed level in this session" in block
        assert "never above it" in block
        # Registr savolni osonlashtirmaydi — faqat tilni.
        assert "stays required at every level" in block
