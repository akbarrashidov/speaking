"""§4.4 state machine — barcha tarmoqlar. Sof logika, DB kerak emas."""

import pytest

from apps.practice import state as sm


def make_state(mode="anticipation_drill", questions=(101, 102, 103)):
    return sm.SessionState(
        session_id="test-session",
        mode=mode,
        question_ids=list(questions),
        max_questions=len(questions),
    )


def start(state):
    return sm.start_question(state)


# --- asosiy oqim ----------------------------------------------------------


def test_first_question_is_asked():
    state = make_state()
    decision = start(state)
    assert decision.action == sm.Action.ASK_QUESTION
    assert decision.payload["question_id"] == 101
    assert state.asked_total == 1
    assert state.attempt == 0


def test_correct_first_attempt_counts_as_first_attempt_correct():
    state = make_state()
    start(state)
    decision = sm.evaluate(state, 101, "correct")

    assert decision.action == sm.Action.ASK_QUESTION  # keyingi savolga o'tdi
    assert state.correct_total == 1
    assert state.first_attempt_correct == 1
    assert state.current_question_id == 102


# --- retry → model javob → tiklanish (§4.4) -------------------------------


def test_incorrect_first_attempt_triggers_retry():
    state = make_state()
    start(state)
    decision = sm.evaluate(state, 101, "incorrect", "wrong_tense")

    assert decision.action == sm.Action.RETRY
    assert state.attempt == 1
    assert state.current_question_id == 101  # xuddi shu savolda qolamiz


def test_second_incorrect_triggers_model_answer():
    state = make_state()
    start(state)
    sm.evaluate(state, 101, "incorrect", "wrong_tense")
    decision = sm.evaluate(state, 101, "incorrect", "wrong_tense")

    assert decision.action == sm.Action.GIVE_MODEL_ANSWER
    assert state.model_answer_given is True
    assert state.attempt == 2


def test_never_more_than_two_attempts_before_model_answer():
    """§4.4: hech qachon 3+ urinish."""
    state = make_state()
    start(state)
    actions = [
        sm.evaluate(state, 101, "incorrect").action,
        sm.evaluate(state, 101, "incorrect").action,
    ]
    assert actions == [sm.Action.RETRY, sm.Action.GIVE_MODEL_ANSWER]
    assert state.attempt == sm.MAX_ATTEMPTS_BEFORE_MODEL


def test_correct_after_model_answer_is_flagged_recovered():
    state = make_state()
    start(state)
    sm.evaluate(state, 101, "incorrect")
    sm.evaluate(state, 101, "incorrect")
    decision = sm.evaluate(state, 101, "correct")

    assert decision.action == sm.Action.ASK_QUESTION
    record = state.record_for(101)
    assert record.recovered_after_model is True
    assert record.first_attempt_correct is False
    assert state.correct_total == 1
    assert state.first_attempt_correct == 0


def test_incorrect_after_model_answer_is_severe_error():
    state = make_state()
    start(state)
    sm.evaluate(state, 101, "incorrect")
    sm.evaluate(state, 101, "incorrect")
    decision = sm.evaluate(state, 101, "incorrect")

    assert decision.action == sm.Action.ASK_QUESTION  # keyingi savolga o'tildi
    assert state.severe_errors == 1
    assert state.record_for(101).severe_error is True
    assert state.current_question_id == 102


# --- alohida verdictlar ---------------------------------------------------


def test_unintelligible_produces_clarify_but_counts_as_attempt():
    """§4.5 — xato urinish sifatida hisoblanadi, lekin boshqa signal bilan."""
    state = make_state()
    start(state)
    decision = sm.evaluate(state, 101, "unintelligible")

    assert decision.action == sm.Action.CLARIFY
    assert state.attempt == 1

    decision2 = sm.evaluate(state, 101, "unintelligible")
    assert decision2.action == sm.Action.GIVE_MODEL_ANSWER


def test_off_topic_is_treated_as_incorrect_attempt():
    state = make_state()
    start(state)
    decision = sm.evaluate(state, 101, "off_topic")
    assert decision.action == sm.Action.RETRY
    assert state.attempt == 1


def test_unknown_verdict_falls_back_to_unintelligible():
    state = make_state()
    start(state)
    decision = sm.evaluate(state, 101, "banana")
    assert decision.action == sm.Action.CLARIFY


# --- modelning oldinga sakrashiga yo'l qo'yilmaydi ------------------------


def test_mismatched_question_id_keeps_current_question():
    state = make_state()
    start(state)
    decision = sm.evaluate(state, 999, "correct")

    assert decision.action == sm.Action.RETRY
    assert decision.payload["reason"] == "question_id_mismatch"
    assert state.current_question_id == 101
    assert state.correct_total == 0
    assert state.attempt == 0  # urinish hisoblanmadi


def test_evaluation_before_any_question_starts_the_first_one():
    state = make_state()
    decision = sm.evaluate(state, None, "correct")
    assert decision.action == sm.Action.ASK_QUESTION
    assert state.asked_total == 1


# --- sessiya yakuni -------------------------------------------------------


def test_bank_exhaustion_ends_session():
    state = make_state(questions=(101, 102))
    start(state)
    sm.evaluate(state, 101, "correct")
    decision = sm.evaluate(state, 102, "correct")

    assert decision.action == sm.Action.END_SESSION
    assert decision.payload["reason"] == "completed"
    assert state.is_ended


def test_max_questions_limit_ends_session_before_bank_end():
    state = sm.SessionState(
        session_id="s", mode="anticipation_drill", question_ids=[1, 2, 3, 4], max_questions=2
    )
    start(state)
    sm.evaluate(state, 1, "correct")
    decision = sm.evaluate(state, 2, "correct")

    assert decision.action == sm.Action.END_SESSION
    assert state.asked_total == 2


def test_evaluation_after_end_returns_end_session():
    state = make_state(questions=(101,))
    start(state)
    sm.evaluate(state, 101, "correct")
    assert state.is_ended
    assert sm.evaluate(state, 101, "correct").action == sm.Action.END_SESSION


# --- guided_conversation strategiyasi (§4.3.2) ----------------------------


def test_guided_conversation_never_retries_on_wrong_answer():
    """Suhbat oqimi buzilmaydi: xato bo'lsa ham keyingi savolga o'tiladi."""
    state = make_state(mode="guided_conversation")
    start(state)
    decision = sm.evaluate(state, 101, "incorrect", "wrong_tense")

    assert decision.action == sm.Action.ASK_QUESTION
    assert state.current_question_id == 102
    assert state.record_for(101).error_types == ["wrong_tense"]
    assert state.correct_total == 0


def test_guided_conversation_clarifies_once_on_unintelligible():
    state = make_state(mode="guided_conversation")
    start(state)
    assert sm.evaluate(state, 101, "unintelligible").action == sm.Action.CLARIFY
    # Ikkinchi marta tushunarsiz bo'lsa — davom etamiz, tiqilib qolmaymiz.
    assert sm.evaluate(state, 101, "unintelligible").action == sm.Action.ASK_QUESTION


def test_guided_conversation_counts_first_attempt_accuracy():
    state = make_state(mode="guided_conversation")
    start(state)
    sm.evaluate(state, 101, "correct")
    assert state.first_attempt_correct == 1
    assert state.correct_total == 1


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        sm.get_strategy("free_conversation")


# --- adaptive_conversation: state machine oqimga aralashmaydi -------------


@pytest.mark.parametrize("verdict", ["correct", "incorrect", "off_topic", "unintelligible"])
def test_adaptive_conversation_never_steers_the_conversation(verdict):
    """Har qanday verdikt uchun NO_OP — modelga direktiv ketmaydi."""
    state = make_state(mode="adaptive_conversation")
    start(state)

    decision = sm.evaluate(state, 101, verdict)

    assert decision.action == sm.Action.NO_OP
    # Savol almashmaydi: navbatni Live o'zi boshqaradi, bank esa GOALS ro'yxati.
    assert state.current_question_id == 101
    assert state.asked_total == 1


def test_adaptive_conversation_still_counts_statistics():
    state = make_state(mode="adaptive_conversation")
    start(state)

    sm.evaluate(state, 101, "correct")
    sm.evaluate(state, 101, "incorrect", "wrong_tense")
    sm.evaluate(state, 101, "correct")

    assert state.correct_total == 2
    # Retry tushunchasi yo'q — har gap mustaqil "birinchi urinish".
    assert state.first_attempt_correct == 2
    assert state.record_for(101).error_types == ["wrong_tense"]


def test_adaptive_conversation_never_gives_a_model_answer():
    """Ketma-ket xatolar ham "repeat after me" ga olib bormaydi."""
    state = make_state(mode="adaptive_conversation")
    start(state)

    for _ in range(5):
        decision = sm.evaluate(state, 101, "incorrect", "wrong_tense")
        assert decision.action == sm.Action.NO_OP

    assert state.model_answer_given is False


# --- serializatsiya (Redis'ga yozish/o'qish) ------------------------------


def test_state_survives_round_trip():
    state = make_state()
    start(state)
    sm.evaluate(state, 101, "incorrect", "word_order")

    restored = sm.SessionState.from_dict(state.to_dict())

    assert restored.current_question_id == 101
    assert restored.attempt == 1
    assert restored.record_for(101).error_types == ["word_order"]

    decision = sm.evaluate(restored, 101, "incorrect")
    assert decision.action == sm.Action.GIVE_MODEL_ANSWER
