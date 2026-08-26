"""Real vaqtda generatsiya qilingan savollar tekshiruvi (§Faza 5).

Bu darvoza coach bilan o'quvchi orasida turadi: model mavzudan chiqib ketsa
yoki o'quvchi registridan baland gapirsa, savol jimgina rad etiladi va bankdagi
savol ishlatiladi. Tekshiruv sof matn ustida — tekin va bir zumda.
"""

from __future__ import annotations

import pytest

from apps.content.validators import structure_cue, validate_generated_question


def ok(text, structure="past_simple_affirmative", register=1):
    return validate_generated_question(text, structure, register) == []


class TestShape:
    def test_a_good_question_passes(self):
        assert ok("What did you eat yesterday?")

    def test_empty_is_rejected(self):
        assert validate_generated_question("") == ["bo'sh savol"]
        assert validate_generated_question("   ")

    def test_must_end_with_a_question_mark(self):
        assert not ok("Tell me what you did yesterday")

    def test_two_questions_in_one_turn_are_rejected(self):
        """Bir navbatda ikkita savol — o'quvchi qaysi biriga javob berishni bilmaydi."""
        assert not ok("What did you do yesterday? And where did you go?")

    def test_yes_no_question_is_rejected(self):
        assert not ok("Did you go to school yesterday?")

    def test_one_word_answer_question_is_rejected(self):
        assert not ok("How many books did you read yesterday?")


class TestRegisterLength:
    def test_long_question_is_rejected_at_a_low_register(self):
        long_q = "What exactly did you and your whole family decide to do together yesterday?"
        assert not ok(long_q, register=1)

    def test_same_question_passes_at_the_top_register(self):
        long_q = "What exactly did you and your whole family decide to do together yesterday?"
        assert ok(long_q, register=4)

    def test_unknown_register_uses_a_default_limit(self):
        assert ok("What did you do yesterday?", register=None)


class TestStructureCue:
    def test_question_without_a_cue_is_rejected(self):
        """Struktura majburlanmasa mashqning ma'nosi qolmaydi."""
        assert not ok("What is your favourite colour?", structure="past_simple_affirmative")

    def test_cue_matching_is_case_insensitive(self):
        assert ok("Where did you go?", structure="past_simple_affirmative")

    @pytest.mark.parametrize(
        "structure,question",
        [
            ("present_simple_affirmative", "What do you usually eat?"),
            ("present_continuous", "What are you doing right now?"),
            ("present_perfect", "Where have you travelled so far?"),
            ("future_simple", "What will you do tomorrow?"),
            ("comparative_adjectives", "Why is Samarkand nicer than Tashkent?"),
            ("conditional_second", "What would you buy if you won?"),
        ],
    )
    def test_each_structure_family_has_a_working_cue(self, structure, question):
        assert ok(question, structure=structure, register=3)

    def test_unknown_structure_does_not_block(self):
        """Noto'g'ri rad etish ham zarar — noma'lum struktura uchun o'tkazamiz."""
        assert ok("What makes you smile?", structure="something_we_never_defined")

    def test_structure_cue_prefers_the_longest_match(self):
        assert structure_cue("past_continuous_negative") == structure_cue("past_continuous")
        assert structure_cue("past_simple_x") != structure_cue("past_continuous")

    def test_blank_structure_returns_no_cue(self):
        assert structure_cue("") == ""


def test_problems_are_reported_not_just_a_boolean():
    """Rad etilgan savol logga tushadi — nima uchun rad etilgani ko'rinishi kerak."""
    problems = validate_generated_question("Did you like it?", "past_simple_affirmative", "A1")
    assert any("yes/no" in p for p in problems)
