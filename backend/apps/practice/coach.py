"""Real vaqtdagi "coach" — tizimning miyasi (§Faza 2).

Live modeli faqat gapiradi va eshitadi. Baholash, grammatik xatolarni topish,
podkaska matni, dinamik savol va ohang — hammasi shu yerda, arzon matn LLM'ida.

Dizayn qoidasi: **coach nima deyishni yozadi, backend nima bo'lishini hal
qiladi.** Coach hech qachon tarmoqlanishni tanlamaydi — u har chaqiruvda
barcha bo'laklarni (reaksiya, podkaska, model javob, keyingi savol) qaytaradi,
`state.py` esa qaysi biri ishlatilishini deterministik hal qiladi. Shuning uchun
LLM va state machine hech qachon bir-biriga zid kelmaydi.

Coach KRITIK YO'LDA EMAS: u javob bermasa yoki kechiksa, sessiya
`state.py` ning deterministik mantiqi bilan davom etadi.
"""

from __future__ import annotations

import functools
import json
import logging
from dataclasses import asdict, dataclass, field

from django.conf import settings

from . import llm

logger = logging.getLogger(__name__)

COACH_PROMPT_VERSION = "v1.0.0"

VALID_VERDICTS = ("correct", "incorrect", "off_topic", "unintelligible")
VALID_TONES = ("warm", "excited", "slow_encouraging", "playful")
VALID_SEVERITIES = ("low", "medium", "high")

# Bitta javobda beshtagacha xato ko'rsatiladi. Uchta edi: gapirish
# platformasida aytilmagan xato yillar davomida qoladigan xato.
MAX_ERRORS = 5
MAX_RECENT_TURNS = 6
# Qotib qolgan o'quvchiga beriladigan tayyor javoblar (§Faza 4).
MAX_OPTIONS = 3
# Coach'ga bir vaqtda ko'rsatiladigan ochiq maqsad-savollar soni.
MAX_OPEN_GOALS = 6


@functools.lru_cache(maxsize=1)
def system_prompt() -> str:
    path = settings.PROMPTS_DIR / "coach.md"
    if not path.exists():  # pragma: no cover — deploy xatosi
        logger.error("coach.md topilmadi: %s", path)
        return "Return JSON with verdict, errors, reaction, hint, model_answer, next_question."
    return path.read_text(encoding="utf-8").strip()


@dataclass
class CoachContext:
    """Coach'ga beriladigan ixcham holat — ~400 token."""

    register: int = 2
    target_structure: str = ""
    # Ibora yo'nalishi: `target_structure_used` shu iboraning aytilganini
    # bildiradi, shakl emas (§prompts._phrase_focus_block).
    focus_phrase: str = ""
    mode: str = ""
    question_text: str = ""
    canonical_answer: str = ""
    attempt: int = 1
    model_answer_given: bool = False
    learner_utterance: str = ""
    recent_turns: list[dict] = field(default_factory=list)
    recent_error_types: list[str] = field(default_factory=list)
    structure_miss_streak: int = 0
    # Hali javob olinmagan maqsad-savollar: [{"id": int, "text": str}].
    # Coach keyingi savolni shulardan quradi va o'quvchi javobida yopilganini
    # `covered_goal_ids` bo'lib qaytaradi (§coach.md).
    open_goals: list[dict] = field(default_factory=list)
    # `options[].uz` shu tilda yoziladi (§coach.md).
    learner_language: str = "uz"
    # O'quvchi jim qoldi — baholash emas, podkaska so'raladi.
    silent: bool = False

    def to_user_prompt(self) -> str:
        turns = [
            f"{'AI' if t.get('speaker') == 'ai' else 'LEARNER'}: {(t.get('text') or '').strip()}"
            for t in self.recent_turns[-MAX_RECENT_TURNS:]
            if (t.get("text") or "").strip()
        ]
        payload = {
            "register": self.register,
            "mode": self.mode,
            "target_structure": self.target_structure,
            "question_asked": self.question_text,
            "expected_answer_shape": self.canonical_answer,
            "attempt": self.attempt,
            "model_answer_already_given": self.model_answer_given,
            "structure_miss_streak": self.structure_miss_streak,
            "recent_error_types": self.recent_error_types[-3:],
            "open_goals": self.open_goals[:MAX_OPEN_GOALS],
            "recent_conversation": turns,
            "learner_said": self.learner_utterance,
            "learner_language": self.learner_language,
        }
        if self.focus_phrase:
            payload["focus_phrase"] = self.focus_phrase
        if self.silent:
            payload["learner_said"] = ""
            payload["note"] = (
                "The learner went silent and said nothing. Return verdict "
                "'unintelligible', fluency 0, and put your effort into "
                "`options` — 2 or 3 complete answers they can read off the "
                "screen and say out loud. They need scaffolding, not judgement."
            )
        return json.dumps(payload, ensure_ascii=False, indent=1)


@dataclass
class CoachResult:
    verdict: str = "unintelligible"
    target_structure_used: bool = False
    errors: list[dict] = field(default_factory=list)
    fluency: int = 0
    reaction: str = ""
    hint: str = ""
    model_answer: str = ""
    next_question: str = ""
    # `open_goals` dan o'quvchi SHU javobida yopib ketganlari — ular boshqa
    # so'ralmaydi (§consumer._apply_covered_goals).
    covered_goal_ids: list[int] = field(default_factory=list)
    # Jim qolgan o'quvchi ekrandan o'qib aytadigan tayyor javoblar:
    # [{"en": ..., "uz": ...}]. Faqat `silent` chaqiruvda to'ladi.
    options: list[dict] = field(default_factory=list)
    tone: str = "warm"
    # Xizmat maydonlari
    ok: bool = False
    usage: dict = field(default_factory=dict)
    latency_ms: int = 0
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def error_type(self) -> str:
        """`state.py` kutgan bitta yorliq — eng muhim xatoning turi."""
        return self.errors[0]["type"] if self.errors else ""


def fallback(reason: str) -> CoachResult:
    """Coach javob bermadi — sessiya to'xtamaydi, deterministik yo'l ishlaydi."""
    return CoachResult(
        verdict="unintelligible",
        tone="slow_encouraging",
        hint="Take your time — try again.",
        ok=False,
        error=reason,
    )


async def evaluate(ctx: CoachContext) -> CoachResult:
    """Bitta o'quvchi javobini baholaydi. Hech qachon istisno tashlamaydi."""
    if not settings.COACH_API_KEY:
        return fallback("no_api_key")

    result = await llm.achat_json(
        base=settings.COACH_API_BASE,
        key=settings.COACH_API_KEY,
        model=settings.COACH_MODEL,
        system=system_prompt(),
        user=ctx.to_user_prompt(),
        timeout=settings.COACH_TIMEOUT_SECONDS,
        temperature=0.3,
        reasoning_effort=settings.COACH_REASONING_EFFORT,
        max_tokens=settings.COACH_MAX_TOKENS,
    )

    if not result.ok:
        logger.warning("coach_failed reason=%s latency=%dms", result.error, result.latency_ms)
        out = fallback(result.error or "unknown")
        out.usage = result.usage
        out.latency_ms = result.latency_ms
        return out

    out = normalize(result.data)
    out.ok = True
    out.usage = result.usage
    out.latency_ms = result.latency_ms
    return out


def normalize(data: dict) -> CoachResult:
    """LLM chiqishini ishonchli shaklga keltiradi — hech narsaga ishonmaydi."""
    out = CoachResult()

    verdict = str(data.get("verdict") or "").strip().lower()
    out.verdict = verdict if verdict in VALID_VERDICTS else "unintelligible"
    out.target_structure_used = bool(data.get("target_structure_used"))

    try:
        out.fluency = max(0, min(4, int(data.get("fluency") or 0)))
    except (TypeError, ValueError):
        out.fluency = 0

    for item in (data.get("errors") or [])[:MAX_ERRORS]:
        if not isinstance(item, dict):
            continue
        span = str(item.get("span") or "").strip()
        fix = str(item.get("fix") or "").strip()
        if not span or not fix or span == fix:
            continue
        severity = str(item.get("severity") or "medium").strip().lower()
        out.errors.append(
            {
                "span": span[:300],
                "fix": fix[:300],
                "type": _slug(item.get("type"))[:64] or "unclassified",
                "severity": severity if severity in VALID_SEVERITIES else "medium",
            }
        )

    out.reaction = _line(data.get("reaction"), 160)
    out.hint = _line(data.get("hint"), 200)
    out.model_answer = _line(data.get("model_answer"), 300)
    out.next_question = _line(data.get("next_question"), 300)

    for value in (data.get("covered_goal_ids") or [])[:MAX_OPEN_GOALS]:
        try:
            out.covered_goal_ids.append(int(value))
        except (TypeError, ValueError):
            continue

    for item in (data.get("options") or [])[:MAX_OPTIONS]:
        if not isinstance(item, dict):
            continue
        en = _line(item.get("en"), 160)
        if not en:
            continue
        out.options.append({"en": en, "uz": _line(item.get("uz"), 200)})

    tone = str(data.get("tone") or "").strip().lower()
    out.tone = tone if tone in VALID_TONES else "warm"
    return out


def _line(value, limit: int) -> str:
    """Bir qatorli matn — direktivga qo'yiladi, shuning uchun yangi qator bo'lmaydi."""
    text = " ".join(str(value or "").split())
    return text[:limit]


def _slug(value) -> str:
    text = str(value or "").strip().lower()
    return "".join(ch if ch.isalnum() else "_" for ch in text).strip("_")
