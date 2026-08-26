"""Kritik yo'ldagi javob hajmi (§listen.FAST_BLOCK).

Erkin suhbatda `reaction`, `hint`, `next_question`, `options` va `tone` ni
Live modeli o'z ovozida yozadi — ularni coach'dan ham so'rash sof kechikish:
o'lchovda javob 188 tokendan 60 ga tushdi, o'quvchi esa shuncha jim kutadi.
"""

from __future__ import annotations

from apps.practice import coach, listen


def test_free_conversation_asks_for_the_short_shape():
    prompt = listen.system_prompt("to_be", fast=True)
    assert "Return ONLY these fields" in prompt
    for field in ("heard", "verdict", "target_structure_used", "errors", "fluency", "model_answer"):
        assert field in prompt
    assert "Leave out reaction, hint, next_question, options and tone" in prompt


def test_scripted_modes_keep_the_full_shape():
    """Drill/guided rejimlarida savolni backend yozadi — `next_question` kerak."""
    prompt = listen.system_prompt("to_be")
    assert "Return ONLY these fields" not in prompt


def test_missing_fields_do_not_break_the_result():
    """Qisqa javobda yo'q maydonlar bo'sh qiymatga tushadi, xato bermaydi."""
    result = coach.normalize(
        {
            "heard": "I from Uzbekistan",
            "verdict": "incorrect",
            "target_structure_used": False,
            "errors": [{"span": "I from", "fix": "I am from", "type": "missing_auxiliary"}],
            "fluency": 2,
            "model_answer": "I am from Uzbekistan.",
        }
    )
    assert result.verdict == "incorrect"
    assert result.model_answer == "I am from Uzbekistan."
    assert result.errors[0]["fix"] == "I am from"
    assert result.reaction == ""
    assert result.next_question == ""
