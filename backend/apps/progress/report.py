"""Sessiyalararo umumiy tahlil (§Faza 7).

Bitta sessiya feedbacki "bugun nima bo'ldi" ni aytadi. O'quvchiga esa "menda
qaysi xato QAYTA-QAYTA takrorlanadi" degan javob kerak — asosiy foyda shunda.

Narx dizayni:
  - **Agregatsiya sof SQL** — qaysi xato necha marta, qaysi mavzularda,
    kamayayaptimi. Bu butunlay tekin.
  - **Bitta arzon LLM chaqiruvi** — faqat o'zbekcha matn yozish uchun, va
    natija keshlanadi. Foydalanuvchiga haftada bir marta tushadi.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field

from django.conf import settings
from django.core.cache import cache
from django.db.models import Count, Max, Min
from django.utils import timezone

from apps.practice import llm
from apps.practice.models import Session, SessionMetrics, SessionStatus

from .models import ErrorLog

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 24 * 3600
MAX_PATTERNS = 5
# Shundan kam sessiya bo'lsa naqsh haqida gapirish erta — tasodif bo'lishi mumkin.
MIN_SESSIONS = 2

SYSTEM_PROMPT = """You write a short progress note in UZBEK for a learner of
English. You are given counted statistics — do not recount, do not invent, and
never add errors that are not in the data.

Return STRICT JSON only, no markdown:
{
  "headline_uz": "<one short sentence naming the single most useful thing to fix>",
  "patterns_uz": ["<one sentence per pattern, in the order given, plain Uzbek>"],
  "encouragement_uz": "<one or two sentences on what genuinely improved>",
  "focus_next_uz": "<one concrete thing to do in the next session>"
}

Rules:
- Uzbek only, addressed to the learner as "siz". Warm, never scolding.
- No grammar terminology at all — not "Past Simple", not "yordamchi fe'l".
  Describe what to SAY, with a real example.
- `patterns_uz`: exactly one item per pattern given, same order.
- `encouragement_uz` must be based on the numbers you were given. If nothing
  improved, say something true and modest instead of inventing progress.
"""

FALLBACK_HEADLINE = "Mashqni davom ettiring — takrorlangan xatolar asta kamayib boradi."


@dataclass
class Report:
    sessions: int = 0
    patterns: list[dict] = field(default_factory=list)
    accuracy_trend: list[int] = field(default_factory=list)
    total_errors: int = 0
    headline_uz: str = ""
    patterns_uz: list[str] = field(default_factory=list)
    encouragement_uz: str = ""
    focus_next_uz: str = ""
    ok: bool = False

    def to_dict(self) -> dict:
        data = {
            "sessions": self.sessions,
            "patterns": self.patterns,
            "accuracy_trend": self.accuracy_trend,
            "total_errors": self.total_errors,
            "headline_uz": self.headline_uz,
            "encouragement_uz": self.encouragement_uz,
            "focus_next_uz": self.focus_next_uz,
            "ok": self.ok,
        }
        for pattern, text in zip(data["patterns"], self.patterns_uz, strict=False):
            pattern["explain_uz"] = text
        return data


# --- agregatsiya (SQL, tekin) ---------------------------------------------


def aggregate(user) -> Report:
    """Foydalanuvchining xato tarixini sanaydi. LLM chaqirilmaydi."""
    report = Report()

    done = (
        Session.objects.filter(user=user, status=SessionStatus.DONE)
        .order_by("-created_at")
        .values_list("id", flat=True)[:20]
    )
    session_ids = list(done)
    report.sessions = len(session_ids)
    if not session_ids:
        return report

    rows = (
        ErrorLog.objects.filter(user=user)
        .values("error_type")
        .annotate(count=Count("id"), first_seen=Min("created_at"), last_seen=Max("created_at"))
        .order_by("-count")[:MAX_PATTERNS]
    )
    report.patterns = [
        {
            "type": row["error_type"] or "unclassified",
            "count": row["count"],
            "example": _example_for(user, row["error_type"]),
            "last_seen": row["last_seen"].date().isoformat() if row["last_seen"] else "",
            "explain_uz": "",
        }
        for row in rows
        if row["count"] > 0
    ]
    report.total_errors = sum(p["count"] for p in report.patterns)

    metrics = (
        SessionMetrics.objects.filter(session_id__in=session_ids)
        # `created_at` bir xil bo'lishi mumkin (soat aniqligi ~15 ms) — o'sha
        # paytda tartib beqaror bo'lib, trend teskari chiqardi.
        .order_by("session__created_at", "session_id")
        .values("questions_total", "first_attempt_correct")
    )
    report.accuracy_trend = [
        round(m["first_attempt_correct"] / m["questions_total"] * 100)
        for m in metrics
        if m["questions_total"]
    ]
    return report


def _example_for(user, error_type: str) -> dict:
    row = (
        ErrorLog.objects.filter(user=user, error_type=error_type)
        .exclude(correction="")
        .order_by("-created_at")
        .values("learner_utterance", "correction")
        .first()
    )
    if not row:
        return {"said": "", "better": ""}
    return {"said": row["learner_utterance"], "better": row["correction"]}


# --- o'zbekcha matn (bitta LLM chaqiruvi, keshlanadi) ---------------------


def build(user, *, refresh: bool = False) -> dict:
    """Keshlangan umumiy hisobot. Ma'lumot o'zgarmasa LLM qayta chaqirilmaydi."""
    report = aggregate(user)
    if report.sessions < MIN_SESSIONS or not report.patterns:
        report.headline_uz = (
            "Hali naqsh chiqarish uchun ma'lumot kam — yana bir-ikki sessiya o'tkazing."
            if report.sessions < MIN_SESSIONS
            else "Takrorlanadigan xato topilmadi. Ajoyib — shu tempda davom eting!"
        )
        report.ok = True
        return report.to_dict()

    key = _cache_key(user, report)
    if not refresh:
        cached = cache.get(key)
        if cached:
            return cached

    filled = _write_uzbek(report)
    cache.set(key, filled, CACHE_TTL_SECONDS)
    return filled


def _cache_key(user, report: Report) -> str:
    """Kalit ma'lumot barmoq izidan — yangi sessiya bo'lsa kesh o'z-o'zidan yangilanadi."""
    signature = f"{user.id}:{report.sessions}:" + ",".join(
        f"{p['type']}={p['count']}" for p in report.patterns
    )
    return "progress_report:" + hashlib.sha256(signature.encode()).hexdigest()[:32]


def _write_uzbek(report: Report) -> dict:
    if not settings.ANALYSIS_API_KEY:
        report.headline_uz = FALLBACK_HEADLINE
        return report.to_dict()

    lines = [f"Sessions completed: {report.sessions}"]
    if report.accuracy_trend:
        lines.append(f"First-attempt accuracy per session: {report.accuracy_trend}")
    lines.append("Repeated error patterns (most frequent first):")
    for p in report.patterns:
        example = p["example"]
        lines.append(
            f"- {p['type']} ×{p['count']}"
            + (f' — said "{example["said"]}" → "{example["better"]}"' if example["said"] else "")
        )

    call = llm.chat_json(
        base=settings.ANALYSIS_API_BASE,
        key=settings.ANALYSIS_API_KEY,
        model=settings.ANALYSIS_MODEL,
        system=SYSTEM_PROMPT,
        user="\n".join(lines),
        timeout=settings.ANALYSIS_TIMEOUT_SECONDS,
        reasoning_effort=settings.ANALYSIS_REASONING_EFFORT,
    )
    if not call.ok:
        logger.warning("progress_report_failed: %s", call.error)
        report.headline_uz = FALLBACK_HEADLINE
        return report.to_dict()

    data = call.data
    report.headline_uz = _line(data.get("headline_uz")) or FALLBACK_HEADLINE
    report.patterns_uz = [_line(t) for t in (data.get("patterns_uz") or [])][: len(report.patterns)]
    report.encouragement_uz = _line(data.get("encouragement_uz"))
    report.focus_next_uz = _line(data.get("focus_next_uz"))
    report.ok = True
    return report.to_dict()


def _line(value, limit: int = 400) -> str:
    return " ".join(str(value or "").split())[:limit]


def stale_since(user):
    """Oxirgi sessiyadan beri o'tgan vaqt — hisobotni yangilash kerakligi belgisi."""
    last = Session.objects.filter(user=user, status=SessionStatus.DONE).aggregate(
        last=Max("created_at")
    )["last"]
    return (timezone.now() - last) if last else None
