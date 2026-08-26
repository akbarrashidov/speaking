"""Kontent sifat qoidalari (§4.2, §10).

Asosiy qoida: savolga yes/no yoki bitta so'z bilan javob berib bo'lmasligi shart —
tabiiy javob target strukturali to'liq gapni talab qilishi kerak.
"""

from __future__ import annotations

import re

YES_NO_STARTERS = {
    "do",
    "does",
    "did",
    "is",
    "are",
    "am",
    "was",
    "were",
    "will",
    "would",
    "can",
    "could",
    "should",
    "shall",
    "have",
    "has",
    "had",
    "may",
    "might",
    "must",
    "be",
}

# "Bir so'zli javob" ni rag'batlantiradigan savol boshlanishlari.
ONE_WORD_STARTERS = {"how many", "how much", "how old", "what time", "which"}

# Imperativ elicitation promptlari savol belgisisiz bo'ladi va bu to'g'ri —
# ular yes/no javobga umuman yo'l qo'ymaydi ("Tell me about your room.").
IMPERATIVE_STARTERS = (
    "tell me",
    "describe",
    "compare",
    "explain",
    "ask me",
    "talk about",
    "give me",
    "say",
    "think of",
    "imagine",
    # Rol suhbat promptlari: vaziyat ichidagi harakat topshiriladi
    # ("Order a drink and something to eat."). Bunday buyruqqa "ha/yo'q" deb
    # javob berib bo'lmaydi — o'quvchi gapni O'ZI tuzishi shart.
    "ask",
    "order",
    "arrange",
    "offer",
    "invite",
    "complain",
    "greet",
    "report",
)

MIN_CANONICAL_WORDS = 3


def word_count(text: str) -> int:
    return len([w for w in re.split(r"\s+", text.strip()) if w])


def check_question(item: dict) -> list[str]:
    """Bitta savol dict'ini tekshiradi, xatolar ro'yxatini qaytaradi (bo'sh = OK)."""
    problems: list[str] = []

    q = (item.get("question_text") or "").strip()
    a = (item.get("canonical_answer") or "").strip()

    if not q:
        problems.append("question_text bo'sh")
    if not a:
        problems.append("canonical_answer bo'sh")
    if not q or not a:
        return problems

    low = q.lower().lstrip("\"'“‘")
    is_imperative = low.startswith(IMPERATIVE_STARTERS)
    if not q.endswith("?") and not is_imperative:
        problems.append(
            "question_text savol belgisi bilan tugashi yoki imperativ prompt "
            "bo'lishi kerak (Tell me about..., Compare...)"
        )

    first = low.split()
    if first and first[0].strip(",.") in YES_NO_STARTERS:
        problems.append(
            f"yes/no savoli ko'rinishida ('{first[0]}' bilan boshlanadi) — "
            "to'liq gapli javobni majburlamaydi"
        )

    for starter in ONE_WORD_STARTERS:
        if low.startswith(starter):
            problems.append(f"'{starter}' bir so'zli javobga olib keladi")
            break

    if word_count(a) < MIN_CANONICAL_WORDS:
        problems.append(
            f"canonical_answer juda qisqa ({word_count(a)} so'z, minimum {MIN_CANONICAL_WORDS})"
        )

    variants = item.get("answer_variants") or []
    if not isinstance(variants, list):
        problems.append("answer_variants massiv bo'lishi shart")
    elif len(variants) > 3:
        problems.append("answer_variants maksimum 3 ta (§4.2 bo'yicha 1–2 tavsiya)")

    return problems


# ---------------------------------------------------------------------------
# Real vaqtda generatsiya qilingan savollar (§Faza 5)
# ---------------------------------------------------------------------------
#
# Coach suhbat davomida savol yozadi. Uni o'quvchiga aytishdan OLDIN shu yerda
# tekshiramiz: model mavzudan chiqib ketsa yoki o'quvchi registridan baland
# gapirsa, jimgina bankdagi savolga qaytamiz. Tekshiruv sof matn ustida
# ishlaydi — LLM ham, DB ham kerak emas, ya'ni tekin va bir zumda.

# Target strukturani majburlaydigan ishoralar. Kalit — `target_structure`
# qiymatining boshlanishi (masalan `past_simple_affirmative`).
STRUCTURE_CUES = {
    "past_simple": r"\b(yesterday|last|ago|did|when|then|that day|this morning)\b",
    "past_continuous": r"\b(while|when|at \d|doing|happening)\b",
    "present_simple": r"\b(usually|every|often|always|normally|generally|do you|does)\b",
    "present_continuous": r"\b(right now|at the moment|these days|doing|wearing|happening)\b",
    "present_perfect": r"\b(ever|already|yet|since|so far|in your life|before)\b",
    "future": r"\b(tomorrow|next|later|going to|will|plan|planning|weekend)\b",
    "comparative": r"\b(than|more|better|worse|compare|which one)\b",
    "superlative": r"\b(best|worst|most|least|favourite|favorite|ever)\b",
    "conditional": r"\b(if|would|imagine|suppose)\b",
    "modal": r"\b(can|could|should|have to|must|able to)\b",
    "there_is": r"\b(what is there|what are there|in your|how many things)\b",
    # Kengaytirilgan ro'yxatdagi yangi oilalar. Eng uzun mos kelgan kalit
    # yutadi, shuning uchun `first_conditional` "conditional" emas, o'zining
    # ishorasini oladi.
    "first_conditional": r"\b(if|when|plan|tomorrow|next|what will)\b",
    "second_conditional": r"\b(if|would|imagine|suppose|dream)\b",
    "third_conditional": r"\b(if|would have|imagine|instead|differently|past)\b",
    "time_clauses": r"\b(when|if|as soon as|before|after|finish|get home)\b",
    "going_to": r"\b(going to|plan|planning|tomorrow|next|weekend|future)\b",
    "will": r"\b(will|tomorrow|next|future|think|predict|promise)\b",
    "would_like": r"\b(would|like|offer|order|wish|want)\b",
    "too_and_enough": r"\b(too|enough|expensive|difficult|not big|not good)\b",
    "as_as": r"\b(as|compare|same|similar|equal|than)\b",
    "verb_ing": r"\b(enjoy|like|want|need|decide|stop|hope|avoid|mind|finish)\b",
    "relative_clauses": r"\b(kind of|type of|sort of|describe|person|thing|place|which|who)\b",
    "indirect_questions": r"\b(politely|ask me|could you tell|would you ask|imagine)\b",
    "narrative": r"\b(step by step|describe|what happened|order|then|first)\b",
    "present_perfect_vs": r"\b(ever|already|yet|since|recently|last|ago|when|so far)\b",
}

# Registr bo'yicha savol uzunligi tomi — o'quvchi savolni tushunmasa mashq
# yo'q. Kalit: suhbat registri 0..4 (§apps/practice/adaptive.py).
MAX_QUESTION_WORDS = {0: 8, 1: 10, 2: 12, 3: 16, 4: 20}
DEFAULT_MAX_QUESTION_WORDS = 14


def structure_cue(target_structure: str) -> str:
    """`target_structure` uchun ishora regexi. Noma'lum bo'lsa — bo'sh satr."""
    name = (target_structure or "").strip().lower()
    best_key = ""
    for key in STRUCTURE_CUES:
        if name.startswith(key) and len(key) > len(best_key):
            best_key = key
    return STRUCTURE_CUES.get(best_key, "")


def validate_generated_question(
    text: str, target_structure: str = "", register: int | None = None
) -> list[str]:
    """Coach yozgan savolni tekshiradi. Bo'sh ro'yxat = aytish mumkin."""
    problems: list[str] = []
    q = (text or "").strip()
    if not q:
        return ["bo'sh savol"]

    if q.count("?") != 1 or not q.endswith("?"):
        problems.append("aniq bitta savol bo'lishi va '?' bilan tugashi kerak")

    limit = MAX_QUESTION_WORDS.get(register, DEFAULT_MAX_QUESTION_WORDS)
    if word_count(q) > limit:
        problems.append(f"registr {register} uchun juda uzun ({word_count(q)} > {limit} so'z)")

    low = q.lower().lstrip("\"'“‘")
    first = low.split()
    if first and first[0].strip(",.") in YES_NO_STARTERS:
        problems.append(f"yes/no savoli ('{first[0]}' bilan boshlanadi)")

    for starter in ONE_WORD_STARTERS:
        if low.startswith(starter):
            problems.append(f"'{starter}' bir so'zli javobga olib keladi")
            break

    cue = structure_cue(target_structure)
    # Noma'lum struktura uchun bloklamaymiz — noto'g'ri rad etish ham zarar.
    if cue and not re.search(cue, low):
        problems.append(f"'{target_structure}' strukturasini majburlaydigan ishora yo'q")

    return problems


def check_batch(items: list[dict]) -> dict[int, list[str]]:
    """Indeks → muammolar. Faqat muammoli elementlar qaytariladi."""
    result = {}
    for idx, item in enumerate(items):
        problems = check_question(item)
        if problems:
            result[idx] = problems
    return result
