"""Transkript timestamplaridan deterministik metrikalar (§4.6.2). LLM kerak emas."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

FILLERS = [
    "um",
    "uh",
    "erm",
    "ehm",
    "hmm",
    "like",
    "you know",
    "i mean",
    "actually",
    "well",
    "sort of",
    "kind of",
]
_FILLER_RE = re.compile(r"\b(" + "|".join(re.escape(f) for f in FILLERS) + r")\b", re.IGNORECASE)

# Mantiqsiz kechikishlarni chiqarib tashlash (transkript kechikishi, pauza).
MAX_PLAUSIBLE_LATENCY_MS = 15_000


@dataclass
class ComputedMetrics:
    talk_time_seconds: int = 0
    talk_time_pct: float = 0.0
    wpm: float = 0.0
    avg_response_latency_ms: int = 0
    questions_total: int = 0
    correct_total: int = 0
    first_attempt_correct: int = 0
    filler_count: int = 0
    filler_examples: list[str] = field(default_factory=list)
    learner_words: int = 0
    learner_turns: int = 0


def _words(text: str) -> int:
    return len([w for w in re.split(r"\s+", (text or "").strip()) if w])


def compute_from_turns(turns: list[dict], session_duration_seconds: int) -> ComputedMetrics:
    m = ComputedMetrics()

    learner_ms = 0
    latencies: list[int] = []
    filler_hits: list[str] = []

    for turn in turns:
        if turn.get("speaker") != "learner":
            continue
        m.learner_turns += 1
        start = int(turn.get("started_at_ms") or 0)
        end = int(turn.get("ended_at_ms") or 0)
        if end > start:
            learner_ms += end - start
        text = turn.get("text") or ""
        m.learner_words += _words(text)
        filler_hits.extend(match.group(0).lower() for match in _FILLER_RE.finditer(text))

        prev_ai_end = turn.get("prev_ai_end_ms")
        if prev_ai_end is not None and start > 0:
            latency = start - int(prev_ai_end)
            if 0 <= latency <= MAX_PLAUSIBLE_LATENCY_MS:
                latencies.append(latency)

    m.talk_time_seconds = round(learner_ms / 1000)
    if session_duration_seconds > 0:
        m.talk_time_pct = min(100.0, round(m.talk_time_seconds / session_duration_seconds * 100, 1))
    if learner_ms > 0:
        m.wpm = round(m.learner_words / (learner_ms / 60000), 1)
    if latencies:
        m.avg_response_latency_ms = int(sum(latencies) / len(latencies))

    m.filler_count = len(filler_hits)
    # Takrorlanmaydigan misollar, tartibni saqlagan holda.
    seen: set[str] = set()
    for f in filler_hits:
        if f not in seen:
            seen.add(f)
            m.filler_examples.append(f)
    m.filler_examples = m.filler_examples[:5]

    return m


def apply_evaluations(m: ComputedMetrics, evaluations: list[dict]) -> ComputedMetrics:
    """Baholashlardan aniqlik metrikalarini qo'shadi.

    `questions_total` — baholangan noyob savollar soni.
    `first_attempt_correct` — birinchi urinishda to'g'ri javob berilgan savollar.
    """
    by_question: dict[int, list[dict]] = {}
    for ev in evaluations:
        qid = ev.get("question_id")
        if qid is None:
            continue
        by_question.setdefault(int(qid), []).append(ev)

    m.questions_total = len(by_question)
    for items in by_question.values():
        items.sort(key=lambda e: int(e.get("attempt") or 0))
        if any(e.get("verdict") == "correct" for e in items):
            m.correct_total += 1
        first = items[0]
        if int(first.get("attempt") or 1) == 1 and first.get("verdict") == "correct":
            m.first_attempt_correct += 1
    return m


def first_attempt_accuracy(m: ComputedMetrics) -> float:
    if not m.questions_total:
        return 0.0
    return m.first_attempt_correct / m.questions_total


def transcript_text(turns: list[dict]) -> str:
    """LLM tahlili uchun o'qiladigan transkript."""
    lines = []
    for t in turns:
        who = "AI" if t.get("speaker") == "ai" else "LEARNER"
        text = (t.get("text") or "").strip()
        if text:
            lines.append(f"{who}: {text}")
    return "\n".join(lines)
