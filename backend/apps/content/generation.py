"""Savol generatsiyasi uchun LLM chaqiruvi (§10). Bir martalik tooling."""

from __future__ import annotations

import json
import logging

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

GENERATION_PROMPT_VERSION = "content-v1.0.0"


class GenerationError(Exception):
    pass


def load_etalons() -> list[dict]:
    """Uslub etaloni — barcha fayllar birga.

    Etalonlar ilgari daraja bo'yicha tanlanardi. Darajalar yo'q: savol
    bankidagi savol har qanday o'quvchiga beriladi, chunki javob darajasini
    o'quvchining o'zi belgilaydi. Shuning uchun bu yerda uslub namunalari
    birlashtiriladi va target struktura bo'yicha filtrlanadi.
    """
    folder = settings.PROMPTS_DIR / "content" / "etalons"
    files = sorted(folder.glob("*.json")) if folder.exists() else []
    if not files:
        raise GenerationError(f"Etalon fayllar topilmadi: {folder}")
    examples: list[dict] = []
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        examples.extend(data.get("examples") or [])
    if not examples:
        raise GenerationError(f"Etalon fayllarda misol yo'q: {folder}")
    return examples


def load_system_prompt() -> str:
    path = settings.PROMPTS_DIR / "content" / "generate_questions.md"
    if not path.exists():
        raise GenerationError(f"Generatsiya prompti topilmadi: {path}")
    return path.read_text(encoding="utf-8")


def build_user_prompt(
    *,
    target_structure: str,
    topic_title_en: str,
    count: int,
    existing_questions: list[str],
) -> str:
    examples = load_etalons()
    same_structure = [e for e in examples if e.get("target_structure") == target_structure]
    shown = same_structure or examples

    parts = [
        f"Target structure: {target_structure}",
        f"Topic theme: {topic_title_en or target_structure}",
        f"Write {count} new questions.",
        "",
        "Etalon examples (match this style exactly):",
        json.dumps(shown, ensure_ascii=False, indent=2),
    ]
    if existing_questions:
        parts += [
            "",
            "Questions that already exist — do NOT repeat these or write close variants of them:",
            json.dumps(existing_questions, ensure_ascii=False, indent=2),
        ]
    return "\n".join(parts)


def generate_questions(
    *,
    target_structure: str,
    topic_title_en: str = "",
    count: int = 20,
    existing_questions: list[str] | None = None,
) -> list[dict]:
    """LLM'dan savollar oladi. Sxema validatsiyasi chaqiruvchida (§10.3)."""
    if not settings.CONTENT_API_KEY:
        raise GenerationError("CONTENT_API_KEY (yoki ANALYSIS_API_KEY) o'rnatilmagan")

    payload = {
        "model": settings.CONTENT_MODEL,
        "messages": [
            {"role": "system", "content": load_system_prompt()},
            {
                "role": "user",
                "content": build_user_prompt(
                    target_structure=target_structure,
                    topic_title_en=topic_title_en,
                    count=count,
                    existing_questions=existing_questions or [],
                ),
            },
        ],
        "temperature": 0.8,
        "response_format": {"type": "json_object"},
    }

    try:
        response = httpx.post(
            f"{settings.CONTENT_API_BASE.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.CONTENT_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=180,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
        raise GenerationError(f"LLM chaqiruvi muvaffaqiyatsiz: {exc}") from exc

    return parse_questions(content)


def parse_questions(content: str) -> list[dict]:
    content = (content or "").strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[-1]
        if content.rstrip().endswith("```"):
            content = content.rstrip()[:-3]
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise GenerationError(f"JSON pars qilinmadi: {exc}") from exc

    items = data.get("questions") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise GenerationError("Chiqishda 'questions' massivi yo'q")

    cleaned = []
    for item in items:
        if not isinstance(item, dict):
            continue
        cleaned.append(
            {
                "question_text": str(item.get("question_text") or "").strip(),
                "canonical_answer": str(item.get("canonical_answer") or "").strip(),
                "answer_variants": [
                    str(v).strip() for v in (item.get("answer_variants") or []) if str(v).strip()
                ][:3],
                "elicitation_note": str(item.get("elicitation_note") or "").strip(),
            }
        )
    return cleaned
