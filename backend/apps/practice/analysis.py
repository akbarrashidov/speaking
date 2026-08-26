"""Sessiyadan keyingi tahlil (§4.6.3, §Faza 7).

Ish bo'linishi ataylab shunday:

- **Xatolarni topish** — coach real vaqtda allaqachon bajargan. Ro'yxatni shu
  yerda qayta hosila qilmaymiz, faqat yig'amiz va sanaymiz. Bu sof Python,
  ya'ni **tekin va aniq**.
- **Izohlash** — bitta arzon LLM chaqiruvi: takrorlanuvchi naqshni o'zbekcha
  tushuntiradi, bitta o'sish nuqtasini nomlaydi, keyingi sessiyaga mashq
  gaplarini yozadi.

Natijada tahlilga ketadigan kirish tokenlari uch baravar kamayadi va sifat
oshadi — chunki xatolarni audio model emas, matn modeli topgan.

Coach yozuvlari bo'lmasa (masalan LLM butun sessiya davomida yiqilgan bo'lsa)
eski yo'l ishlaydi: xom transkript modelga beriladi.
"""

from __future__ import annotations

import logging
from collections import Counter

from django.conf import settings

from . import llm

logger = logging.getLogger(__name__)

# `*_uz` maydon nomlari tarixiy: ular "O'QUVCHI TILI" degan ma'noni bildiradi.
# Nomni o'zgartirish bazadagi saqlangan feedbacklarni ham buzardi, shuning
# uchun nom qoldi — til esa profildan keladi (§users.language_code).
LANGUAGES = {
    "uz": ("Uzbek", "siz"),
    "ru": ("Russian", "вы"),
}
DEFAULT_LANGUAGE = "uz"

MAX_ERRORS = 8
MAX_PATTERNS = 3
MAX_DRILLS = 3

_INTERPRET_PROMPT = """You write the end-of-session feedback for a {language}-speaking learner
of English. The errors have already been found for you — do NOT look for more,
and never invent an utterance the learner did not say.

Return STRICT JSON only, no markdown, with exactly this shape:
{
  "patterns": [
    {"type": "<the error_type you were given, unchanged>",
     "explain_uz": "<one sentence in {language}: what to do instead, no grammar terms>"}
  ],
  "growth_point_uz": "<ONE thing to work on next, one sentence, in {language}>",
  "next_drills": ["<English sentence the learner should practise saying>"],
  "strengths_uz": ["<one genuine thing they did well, in {language}>"],
  "summary_uz": "<2-3 sentences in {language}>"
}

Rules:
- `patterns`: only the error types you were given, in the same order, at most 3.
  `explain_uz` must be plain {language} a beginner understands — no "Past Simple",
  no "yordamchi fe'l". Say what to say, not what the rule is called.
- `next_drills`: exactly 3 short English sentences, at the learner's own level, that
  practise the exact thing they got wrong. They must be sentences the learner
  could plausibly say about their own life.
- `strengths_uz`: 1-2 items, and they must be real. If the session was weak, say
  something true and small ("oxirigacha gapirishdan to'xtamadingiz").
- `summary_uz`: warm, addressed to the learner as "{you}", 2-3 sentences, names
  exactly ONE growth point. Never mention AI, transcripts, or scores.
- Everything in `*_uz` fields is written in {language}. `next_drills` stays English.
"""

# Coach ishlamagan holat uchun eski yo'l.
_TRANSCRIPT_PROMPT = """You analyse a short English speaking practice transcript
from a {language}-speaking learner. You are given the transcript and the grammar structure the
session targeted.

Return STRICT JSON only, no markdown, with exactly this shape:
{
  "errors": [
    {"utterance": "<what the learner said, verbatim>",
     "error_type": "<short machine label, e.g. wrong_tense>",
     "correction": "<the corrected sentence, keeping the learner's own words>",
     "severity": "low" | "medium" | "high"}
  ],
  "summary_uz": "<2-3 sentences in {language}>"
}

Rules:
- Only real errors made by the LEARNER. Never invent utterances.
- Maximum 8 items, most important first.
- `severity` is high only when the error blocks understanding.
- Keep the learner's own words in `correction`; change only what was wrong.
- `summary_uz`: written in {language}, warm, addressed as "{you}", 2-3 sentences, ONE growth point,
  no grammar terminology, never mention AI or transcripts.
"""

EMPTY_RESULT = {
    "errors": [],
    "filler_examples": [],
    "summary_uz": "",
    "patterns": [],
    "growth_point_uz": "",
    "next_drills": [],
    "strengths_uz": [],
}

# Tahlil yiqilganda ko'rsatiladigan matn. O'quvchi tilida — aks holda ruscha
# interfeysdagi odam yagona o'zbekcha jumlaga duch keladi.
FALLBACK_SUMMARY = {
    "uz": (
        "Bugungi mashg'ulot uchun rahmat! Gapirishda davom eting — har sessiya "
        "nutqingizni tezlashtiradi."
    ),
    "ru": (
        "Спасибо за сегодняшнее занятие! Продолжайте говорить — каждая сессия "
        "делает вашу речь быстрее."
    ),
}
FALLBACK_SUMMARY_UZ = FALLBACK_SUMMARY[DEFAULT_LANGUAGE]


def fallback_summary(language: str = DEFAULT_LANGUAGE) -> str:
    return FALLBACK_SUMMARY.get(language) or FALLBACK_SUMMARY[DEFAULT_LANGUAGE]


# --- coach yozuvlaridan xatolar (LLM'siz, tekin) ---------------------------


def errors_from_coach(records: list[dict]) -> list[dict]:
    """Coach real vaqtda topgan xatolarni feedback shakliga keltiradi."""
    errors: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for record in records or []:
        utterance = (record.get("utterance") or "").strip()
        for err in record.get("errors") or []:
            span = str(err.get("span") or "").strip()
            fix = str(err.get("fix") or "").strip()
            if not span or not fix:
                continue
            key = (span.lower(), fix.lower())
            if key in seen:
                continue
            seen.add(key)
            errors.append(
                {
                    "utterance": (utterance or span)[:300],
                    "error_type": str(err.get("type") or "unclassified")[:64],
                    "correction": _apply_fix(utterance, span, fix)[:300],
                    "severity": str(err.get("severity") or "medium"),
                }
            )
    # Og'irroq xatolar oldinda — o'quvchi birinchi navbatda shularni ko'radi.
    order = {"high": 0, "medium": 1, "low": 2}
    errors.sort(key=lambda e: order.get(e["severity"], 1))
    return errors[:MAX_ERRORS]


def _apply_fix(utterance: str, span: str, fix: str) -> str:
    """Tuzatishni o'quvchining o'z gapiga qo'yadi — begona gap qaytarilmasin."""
    if utterance and span.lower() in utterance.lower():
        index = utterance.lower().index(span.lower())
        return utterance[:index] + fix + utterance[index + len(span) :]
    return fix


def count_patterns(errors: list[dict]) -> list[dict]:
    """Takrorlangan xato turlari — sof hisob, LLM kerak emas."""
    counter = Counter(e["error_type"] for e in errors if e.get("error_type"))
    patterns = []
    for error_type, count in counter.most_common(MAX_PATTERNS):
        example = next((e for e in errors if e["error_type"] == error_type), None)
        patterns.append(
            {
                "type": error_type,
                "count": count,
                "example": example["utterance"] if example else "",
                "fix": example["correction"] if example else "",
                "explain_uz": "",
            }
        )
    return patterns


# --- LLM izohi -------------------------------------------------------------


def _prompt(template: str, language: str) -> str:
    """Shablonni o'quvchi tiliga moslaydi.

    `str.format` EMAS: shablon ichida JSON shakli bor, ya'ni jingalak qavslar
    o'rin egallovchi sifatida talqin qilinib xato beradi.
    """
    name, you = LANGUAGES.get(language) or LANGUAGES[DEFAULT_LANGUAGE]
    return template.replace("{language}", name).replace("{you}", you)


def analyse_session(
    *,
    coach_records: list[dict],
    transcript: str,
    target_structure: str,
    register: int | None = None,
    accuracy_pct: int | None = None,
    language: str = DEFAULT_LANGUAGE,
) -> dict:
    """Sessiya feedbackini tayyorlaydi. Xatolikda ham foydali natija qaytaradi."""
    errors = errors_from_coach(coach_records)

    if not errors and not coach_records:
        # Coach umuman ishlamagan — eski yo'l bilan transkriptdan tahlil.
        return analyse_transcript(transcript, target_structure, register, language)

    patterns = count_patterns(errors)
    result = {**EMPTY_RESULT, "errors": errors, "patterns": patterns, "ok": True}

    if not settings.ANALYSIS_API_KEY:
        logger.warning("ANALYSIS_API_KEY yo'q — izohlash o'tkazib yuborildi")
        return {**result, "summary_uz": fallback_summary(language), "ok": False}

    user_prompt = _interpret_input(
        patterns, errors, target_structure, register, accuracy_pct, coach_records
    )
    call = llm.chat_json(
        base=settings.ANALYSIS_API_BASE,
        key=settings.ANALYSIS_API_KEY,
        model=settings.ANALYSIS_MODEL,
        system=_prompt(_INTERPRET_PROMPT, language),
        user=user_prompt,
        timeout=settings.ANALYSIS_TIMEOUT_SECONDS,
        reasoning_effort=settings.ANALYSIS_REASONING_EFFORT,
    )
    result["usage"] = call.usage

    if not call.ok:
        logger.warning("analysis_call_failed: %s", call.error)
        return {**result, "summary_uz": fallback_summary(language), "ok": False}

    return {**result, **normalize_interpretation(call.data, patterns, language), "ok": True}


def _interpret_input(
    patterns, errors, target_structure, register, accuracy_pct, coach_records
) -> str:
    """Ixcham kirish — xatolar allaqachon topilgan, ularni qaytadan yubormaymiz."""
    lines = [
        f"How the learner speaks (0 words - 4 fluent): {_register_label(register)}",
        f"Target structure: {target_structure or 'general speaking'}",
    ]
    if accuracy_pct is not None:
        lines.append(f"First-attempt accuracy: {accuracy_pct}%")
    fluency = [r.get("fluency") for r in coach_records if isinstance(r.get("fluency"), int)]
    if fluency:
        lines.append(f"Average fluency (0-4): {sum(fluency) / len(fluency):.1f}")

    lines.append("\nRepeated error patterns (most frequent first):")
    for p in patterns:
        lines.append(f'- {p["type"]} ×{p["count"]} — said "{p["example"]}" → "{p["fix"]}"')
    if not patterns:
        lines.append("- none; the learner made no repeated grammar errors")

    lines.append("\nAll corrections from this session:")
    for e in errors[:MAX_ERRORS]:
        lines.append(f'- "{e["utterance"]}" → "{e["correction"]}"')

    return "\n".join(lines)


def normalize_interpretation(
    data: dict, patterns: list[dict], language: str = DEFAULT_LANGUAGE
) -> dict:
    """LLM izohini ishonchli shaklga keltiradi va naqshlarga bog'laydi."""
    explanations = {}
    for item in (data.get("patterns") or [])[:MAX_PATTERNS]:
        if isinstance(item, dict) and item.get("type"):
            explanations[str(item["type"])] = _line(item.get("explain_uz"), 240)

    enriched = [{**p, "explain_uz": explanations.get(p["type"], "")} for p in patterns]

    drills = [_line(d, 160) for d in (data.get("next_drills") or []) if _line(d, 160)]
    strengths = [_line(s, 200) for s in (data.get("strengths_uz") or []) if _line(s, 200)]

    return {
        "patterns": enriched,
        "growth_point_uz": _line(data.get("growth_point_uz"), 300),
        "next_drills": drills[:MAX_DRILLS],
        "strengths_uz": strengths[:2],
        "summary_uz": _line(data.get("summary_uz"), 600) or fallback_summary(language),
    }


def _line(value, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


# --- zaxira yo'l: xom transkript -------------------------------------------
#
# Coach umuman ishlamagan sessiya uchun (LLM butun davomida yiqilgan). Sifati
# pastroq, chunki xatolarni transkriptdan qayta qidirish kerak — lekin
# o'quvchi baribir feedbacksiz qolmaydi.


def _register_label(register) -> str:
    """Registr — daraja emas, o'quvchi nutqining o'lchovi (§adaptive.py)."""
    return "unknown" if register is None else str(register)


def analyse_transcript(
    transcript: str,
    target_structure: str,
    register: int | None = None,
    language: str = DEFAULT_LANGUAGE,
) -> dict:
    if not transcript.strip():
        return {**EMPTY_RESULT, "ok": True}
    if not settings.ANALYSIS_API_KEY:
        logger.warning("ANALYSIS_API_KEY yo'q — LLM tahlili o'tkazib yuborildi")
        return {**EMPTY_RESULT, "summary_uz": fallback_summary(language), "ok": False}

    call = llm.chat_json(
        base=settings.ANALYSIS_API_BASE,
        key=settings.ANALYSIS_API_KEY,
        model=settings.ANALYSIS_MODEL,
        system=_prompt(_TRANSCRIPT_PROMPT, language),
        user=(
            f"Target structure: {target_structure or 'general speaking'}\n"
            f"How the learner speaks (0 words - 4 fluent): {_register_label(register)}\n\n"
            f"Transcript:\n{transcript}"
        ),
        timeout=settings.ANALYSIS_TIMEOUT_SECONDS,
        reasoning_effort=settings.ANALYSIS_REASONING_EFFORT,
    )
    if not call.ok:
        logger.warning("analysis_call_failed: %s", call.error)
        return {
            **EMPTY_RESULT,
            "summary_uz": fallback_summary(language),
            "ok": False,
            "usage": call.usage,
        }

    normalized = normalize(call.data, language)
    return {
        **EMPTY_RESULT,
        **normalized,
        "patterns": count_patterns(normalized["errors"]),
        "ok": True,
        "usage": call.usage,
    }


def normalize(data: dict, language: str = DEFAULT_LANGUAGE) -> dict:
    """Transkript yo'lidagi LLM chiqishini kutilgan shaklga keltiradi."""
    errors = []
    for item in (data.get("errors") or [])[:MAX_ERRORS]:
        if not isinstance(item, dict):
            continue
        utterance = str(item.get("utterance") or "").strip()
        correction = str(item.get("correction") or "").strip()
        if not utterance or not correction:
            continue
        severity = str(item.get("severity") or "medium").lower()
        if severity not in ("low", "medium", "high"):
            severity = "medium"
        errors.append(
            {
                "utterance": utterance[:300],
                "error_type": str(item.get("error_type") or "")[:64],
                "correction": correction[:300],
                "severity": severity,
            }
        )

    fillers = [str(f).strip()[:32] for f in (data.get("filler_examples") or []) if str(f).strip()][
        :5
    ]
    summary = str(data.get("summary_uz") or "").strip() or fallback_summary(language)
    return {"errors": errors, "filler_examples": fillers, "summary_uz": summary}
