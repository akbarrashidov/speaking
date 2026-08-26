"""AI suhbat REGISTRI — o'quvchi qanday gapirsa, AI ham shunday gapiradi.

**LLM kerak emas, ya'ni butunlay tekin.** Barcha signallar coach allaqachon
qaytargan ma'lumotdan olinadi.

Bu modul ilgari "daraja ichidagi qadam" (`sub_level`) edi. Darajalar olib
tashlangach, u tizimdagi YAGONA daraja mexanizmiga aylandi va ma'nosi
o'zgardi: endi bu AI'ning tanlangan darajaga nisbatan siljishi emas, balki
o'quvchi nutqining o'lchovi.

`register` — 0..4, coach'ning `fluency` shkalasi bilan bir xil, ataylab:

  0  bitta so'z, jimlik — AI ham eng oddiy, sekin, qisqa gapiradi
  1  parcha gaplar
  2  qisqa to'liq gaplar (boshlanish nuqtasi)
  3  to'liq gap, ozgina tutilish bilan
  4  ravon, uzun, tabiiy — AI ham to'liq tabiiy tezlikda gapiradi

Ko'zgu qoidasi: MAQSAD — o'quvchining o'z ravonligi. AI undan baland ham,
past ham gapirmaydi. Faqat ikkita chetlanish bor:

  * o'quvchi ko'p xato qilayotgan bo'lsa registr KO'TARILMAYDI (ravon gapirish
    tushunish demak emas);
  * qotib qolgan bo'lsa registr darhol pasayadi.

Bir chaqiruvda ko'pi bilan bitta qadam — sakrash o'quvchini chalg'itadi.
"""

from __future__ import annotations

from dataclasses import dataclass

MIN_REGISTER = 0
MAX_REGISTER = 4
# Suhbat shu yerdan boshlanadi: oddiy, lekin bolalarcha emas. Foydalanuvchining
# o'tgan sessiyalardagi registri bo'lsa, u shuning o'rniga ishlatiladi.
DEFAULT_REGISTER = 2

# Shuncha javobdan oldin registr o'zgarmaydi — bitta omadli javob dalil emas.
MIN_SAMPLES = 3

# Registrni ko'tarish uchun minimal aniqlik: gapi ravon, lekin har gapi xato
# bo'lsa, tezlashtirish yordam bermaydi.
RAISE_MIN_ACCURACY = 0.5

# Shu qadar qotib qolish — darhol pasaytirish sababi.
DEMOTE_STUCK = 2


@dataclass
class Signals:
    """Coach va state machine bergan o'lchovlar."""

    answered: int = 0
    first_attempt_accuracy: float = 0.0  # 0..1
    avg_fluency: float = 0.0  # 0..4 — o'quvchi nutqining o'lchovi
    structure_hit_rate: float = 0.0  # 0..1
    stuck_count: int = 0


def signals_from_state(state, recent_fluency: list[int], *, answered: int | None = None) -> Signals:
    """`answered` — moslashuv o'lchov birligi.

    Skript rejimlarida bu berilgan savollar soni. Erkin suhbatda savol
    "berilmaydi", shuning uchun consumer u yerda baholangan navbatlar sonini
    uzatadi — aks holda ko'rsatkich 1 da qotib qolib, registr hech qachon
    o'zgarmasdi.
    """
    answered = max(0, state.asked_total if answered is None else answered)
    if not answered:
        return Signals()
    hits = sum(1 for f in recent_fluency if f > 0)
    return Signals(
        answered=answered,
        first_attempt_accuracy=state.first_attempt_correct / answered,
        avg_fluency=(sum(recent_fluency) / len(recent_fluency)) if recent_fluency else 0.0,
        structure_hit_rate=(hits / len(recent_fluency)) if recent_fluency else 0.0,
        stuck_count=state.stuck_count,
    )


def next_register(current: int, s: Signals) -> int:
    """O'quvchining ravonligiga bir qadam yaqinlashadi."""
    current = _clamp(current)
    if s.answered < MIN_SAMPLES:
        return current

    if s.stuck_count >= DEMOTE_STUCK:
        return _clamp(current - 1)

    # Yarimni yuqoriga: Python'ning bank yaxlitlashi (round(1.5) == 2,
    # round(2.5) == 2) bu yerda tushunarsiz sakrashlar berardi.
    target = clamp(int(s.avg_fluency + 0.5))
    if target > current:
        # Ko'tarilish shartli: ravon, lekin xato to'la nutq — bu hali yuqori
        # registr emas. Pasayish esa hech qachon shartli emas.
        if s.first_attempt_accuracy < RAISE_MIN_ACCURACY:
            return current
        return current + 1
    if target < current:
        return current - 1
    return current


# O'quvchi ro'yxatdan o'tishda O'ZI aytgan daraja → boshlang'ich registr.
#
# Bu o'lchov emas, TAXMIN: birinchi suhbat noldan emas, taxminan to'g'ri
# joydan boshlanadi. Daraja aniqlash suhbati tugagach uni o'lchangan qiymat
# almashtiradi (§placement.py) — aytgani bilan o'lchangani to'g'ri kelmasa,
# o'lchangani g'olib.
#
# 2 ro'yxatda yo'q, ataylab: u "hech narsa ma'lum emas" nuqtasi
# (`DEFAULT_REGISTER`), ya'ni javob bermagan o'quvchining joyi.
DECLARED_LEVEL_REGISTER = {
    "beginner": 0,
    "elementary": 1,
    "intermediate": 3,
    "advanced": MAX_REGISTER,
}


def register_from_declared_level(level: str) -> int:
    """Aytilgan daraja bo'yicha boshlang'ich registr. Noma'lum bo'lsa — odatiy."""
    return DECLARED_LEVEL_REGISTER.get((level or "").strip().lower(), DEFAULT_REGISTER)


def clamp(value: int) -> int:
    """Registrni ruxsat etilgan oraliqqa siqadi (0..4)."""
    try:
        return max(MIN_REGISTER, min(MAX_REGISTER, int(value)))
    except (TypeError, ValueError):
        return DEFAULT_REGISTER


_clamp = clamp


# Har registr uchun AI qanday gapirishi. Bu matn ikki joyda ishlatiladi:
# sessiya boshida system promptda (`prompts.py`) va registr o'zgarganda
# DIRECTOR ko'rsatmasida (`consumer.py`).
REGISTER = {
    0: (
        "The learner speaks in single words or stays silent. Use the simplest "
        "English you have: 4-6 word sentences, the most common words only, no "
        "contractions, long pauses. Ask questions they can answer with two or "
        "three words, and accept those answers."
    ),
    1: (
        "The learner speaks in fragments. Keep your sentences short and "
        "concrete, one idea each, and speak slowly. Ask for a little more than "
        "they gave you — a fragment plus one detail is a win."
    ),
    2: (
        "The learner makes short complete sentences. Speak in everyday English "
        "at a calm, clear pace. Expect a full sentence back, and ask a follow-up "
        "when they answer in one."
    ),
    3: (
        "The learner speaks in full sentences with some hesitation. Speak at a "
        "natural conversational pace with normal contractions. Do not accept "
        "one-word replies — ask for reasons and details."
    ),
    4: (
        "The learner is fluent and extended. Speak at full natural pace with "
        "real energy and normal idiom. Push every turn: reasons, comparisons, "
        "examples, opinions. Short answers from them are a step backwards."
    ),
}

# Ko'zgu qoidasi — system promptga qo'shiladigan doimiy qism. Registr raqami
# faqat boshlang'ich nuqta; suhbat davomida AI o'quvchiga qarab yuradi.
MIRROR_RULE = (
    "MATCH THE LEARNER, TURN BY TURN:\n"
    "There is no fixed level in this session. The learner sets it and you "
    "follow, every single turn.\n"
    "- Speak at the complexity the learner just used, never above it. If their "
    "last sentence was six simple words, yours is six simple words.\n"
    "- If they open up and speak in long, fluent sentences, rise to meet them "
    "immediately — same speed, same richness, same length. Staying simple with "
    "a strong speaker is as wrong as being complex with a beginner.\n"
    "- If they shrink back to short answers, come back down just as fast.\n"
    "- Never say anything about their level, never praise or grade their "
    "English, and never announce that you are simplifying or speeding up.\n"
    "- Matching their level is about HOW you speak, never about what you ask: "
    "the grammar this session drills stays required at every level."
)


def register_block(register: int) -> str:
    """Sessiya boshidagi to'liq blok: ko'zgu qoidasi + boshlang'ich registr."""
    return f"{MIRROR_RULE}\n\nRIGHT NOW: {REGISTER[_clamp(register)]}"


def pacing_clause(register: int) -> str:
    """Registr o'zgarganda modelga beriladigan qisqa ko'rsatma."""
    return REGISTER.get(_clamp(register), "")


def tone_for(register: int, verdict: str, fluency: int, *, stuck: bool = False) -> str:
    """Ovoz ohangi.

    Emotsiya — bezak emas: o'quvchi zo'r gapirganda haqiqiy hayajon eshitishi,
    qiynalganda esa bosiqlik eshitishi kerak.
    """
    if stuck or verdict in ("incorrect", "unintelligible", "off_topic"):
        return "slow_encouraging"
    if verdict == "correct" and fluency >= 3 and register >= 3:
        return "playful" if register >= MAX_REGISTER else "excited"
    if verdict == "correct" and fluency >= 3:
        return "excited"
    return "warm"
