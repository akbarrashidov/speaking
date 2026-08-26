"""AI gapining o'quvchi tilidagi tarjimasi — ekran uchun.

Nega alohida modul va alohida chaqiruv: o'quvchi AI nima deganini tushunmasa,
butun suhbat behuda ketadi. Ovozda tarjima berish esa mumkin emas — u ingliz
tilidagi gapirish vaqtini yeydi va o'quvchini tinglashdan voz kechishga
o'rgatadi. Shuning uchun tarjima faqat EKRANDA, ovozdan keyin chiqadi.

Chaqiruv juda kichik (~40 kirish / ~30 chiqish token) va kritik yo'lda emas:
yiqilsa gap tarjimasiz qoladi, sessiya davom etaveradi.
"""

from __future__ import annotations

import json
import logging

from django.conf import settings

from . import llm

logger = logging.getLogger(__name__)

MAX_SOURCE_CHARS = 600

# Qo'llab-quvvatlanadigan tillar. Kalit — `User.language_code`.
TARGETS = {
    "uz": ("Uzbek", "natural spoken Uzbek in Latin script"),
    "ru": ("Russian", "natural spoken Russian"),
}
DEFAULT_TARGET = "uz"


def system_prompt(language: str) -> str:
    """Tarjima ko'rsatmasi. Til o'quvchi profilidan keladi (§users.language_code)."""
    name, described = TARGETS.get(language) or TARGETS[DEFAULT_TARGET]
    return (
        f"You translate one short English line into {described} for a learner "
        "of English.\n"
        'Return STRICT JSON: {"text": "<translation>"}\n'
        "Rules:\n"
        f"- {name}, natural and spoken, not word-for-word.\n"
        "- Keep it the same length and register as the English line.\n"
        "- A question stays a question.\n"
        "- Translate only. Never answer, never explain, never add anything.\n"
        "- Leave proper names as they are."
    )


async def to_learner_language(text: str, language: str = DEFAULT_TARGET) -> tuple[str, dict]:
    """Bitta inglizcha gapning o'quvchi tilidagi varianti va token sarfi.

    Xato bo'lsa — bo'sh satr; sarf esa baribir qaytariladi, narx hisobiga
    tushishi uchun.
    """
    source = " ".join((text or "").split())[:MAX_SOURCE_CHARS]
    if not source or not settings.TRANSLATE_ENABLED or not settings.TRANSLATE_API_KEY:
        return "", {}

    result = await llm.achat_json(
        base=settings.TRANSLATE_API_BASE,
        key=settings.TRANSLATE_API_KEY,
        model=settings.TRANSLATE_MODEL,
        system=system_prompt(language),
        user=json.dumps({"en": source}, ensure_ascii=False),
        timeout=settings.TRANSLATE_TIMEOUT_SECONDS,
        temperature=0.2,
        reasoning_effort=settings.COACH_REASONING_EFFORT,
        max_tokens=settings.TRANSLATE_MAX_TOKENS,
    )
    if not result.ok:
        logger.info("translate_failed reason=%s latency=%dms", result.error, result.latency_ms)
        return "", result.usage

    # `uz` — eski kalit, eski javoblar bilan mos qolsin.
    raw = result.data.get("text") or result.data.get("uz") or ""
    return " ".join(str(raw).split())[:MAX_SOURCE_CHARS], result.usage
