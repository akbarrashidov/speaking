"""Podkaska zinapoyasi (§Faza 4) — sof logika, I/O yo'q.

O'quvchi qotib qolganda uni jimlikda qoldirmaslik kerak, lekin javobni ham
darrov berib qo'ymaslik kerak. Shuning uchun uch pog'onali zinapoya:

  1. `repeat`  — savolni sekinroq takrorlash. Ko'pincha shuning o'zi yetadi.
  2. `opener`  — gap boshini berish ("Start with: I went to..."). O'quvchi
                 gapni O'ZI tugatadi — eng ko'p o'rgatadigan pog'ona.
  3. `model`   — to'liq javob + "repeat after me". Bu pog'onadan keyin
                 boshqaruv `state.py` ga o'tadi, ya'ni sessiya cheksiz
                 kutib qolmaydi.

Har pog'ona ovozda ham, ekranda ham beriladi. Ekrandagi matn token
sarflamaydi va o'qib idrok qilish eshitishdan ko'ra oson.
"""

from __future__ import annotations

from dataclasses import dataclass

# O'quvchi qanchalik sekin gapirsa, shuncha ko'p vaqt beriladi. Kalit —
# suhbat registri (0..4, §adaptive.py), daraja emas: darajalar yo'q.
SILENCE_SECONDS = {0: 8.0, 1: 7.0, 2: 6.0, 3: 5.0, 4: 4.0}
DEFAULT_SILENCE_SECONDS = 6.0

MAX_RUNG = 3
# To'liq zinapoyadan shuncha marta o'tib ham jim bo'lsa — savol yopiladi va
# sessiya davom etadi. Busiz bitta savol butun vaqt limitini yeb qo'yardi.
MAX_STUCK_BEFORE_MOVING_ON = 2


@dataclass(frozen=True)
class Rung:
    number: int
    kind: str
    label_uz: str


RUNGS = {
    1: Rung(1, "repeat", "Shoshilmang — savolni yana bir bor eshiting."),
    2: Rung(2, "opener", "Mana shunday boshlab ko'ring:"),
    3: Rung(3, "model", "Menga ergashing:"),
}


def silence_seconds(register: int) -> float:
    try:
        return SILENCE_SECONDS.get(int(register), DEFAULT_SILENCE_SECONDS)
    except (TypeError, ValueError):
        return DEFAULT_SILENCE_SECONDS


def rung(number: int) -> Rung:
    return RUNGS.get(number, RUNGS[MAX_RUNG])


def screen_text(number: int, coach_result) -> str:
    """Ekranda ko'rsatiladigan matn — pog'onaga qarab.

    1-pog'onada matn bermaymiz: savol qaytadan aytiladi, ekranga yozish
    o'quvchini o'qishga o'tkazib yuboradi.
    """
    if number == 1:
        return ""
    if number == 2:
        return coach_result.hint or ""
    return coach_result.model_answer or ""


def directive_for(number: int, coach_result, question_text: str) -> tuple[str, str]:
    """Live uchun sahna ko'rsatmasi va ohang."""
    if number == 1:
        return (
            f'Say "Take your time." Then ask the question again, more slowly, word '
            f'for word: "{question_text}". Then stop and wait.',
            "slow_encouraging",
        )
    if number == 2:
        opener = coach_result.hint or "Start with the first word of your answer."
        return (
            f'Say exactly: "{opener}" Then stop and wait for the learner to finish '
            "the sentence. Do not say the rest of it yourself.",
            "slow_encouraging",
        )
    answer = coach_result.model_answer or ""
    return (
        f'Say "Let me help." Then say exactly: "{answer}" Then say "Repeat after me:" '
        "and say that same sentence once more. Wait for the learner to repeat it.",
        "slow_encouraging",
    )
