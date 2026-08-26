"""Eshitish + baholash BITTA chaqiruvda (§5.1a).

Nega birlashtirildi. Yangi oqimda model o'quvchi gapirib bo'lgach darhol javob
bermaydi — backend avval nima aytilganini va qaysi xato borligini biladi, keyin
modelga navbatni ochadi. Ya'ni bu ish endi KRITIK YO'LDA: har navbatda
o'quvchi kutib turadi.

Ilgari ikkita ketma-ket chaqiruv bor edi — avval `asr.py` (audio → matn), keyin
`coach.py` (matn → xatolar). Ikkalasi ~3.5 s. Bitta multimodal chaqiruvda
~1.5 s, ustiga baholash sifati ham yaxshiroq: model gapni O'ZI eshitadi, ya'ni
"I from" va "I'm from" farqini transkript orqali emas, to'g'ridan-to'g'ri
ajratadi.

Yiqilsa `asr.py` + `coach.py` yo'li zaxira bo'lib qoladi.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time

import httpx
from django.conf import settings

from apps.content.models import FREE_FLOW_MODES

from . import asr, coach

logger = logging.getLogger(__name__)

TRANSCRIBE_BLOCK = (
    "THE LEARNER'S ANSWER IS ATTACHED AS AUDIO, NOT TEXT.\n\n"
    "Before you judge anything, listen and write down EXACTLY what they said, "
    'word for word, into the "heard" field.\n\n'
    f"{asr.PROMPT}\n"
    'Then judge what is in "heard" — never a tidied-up version of it. If you '
    "write a word into `heard` that they did not say, you have hidden the "
    "mistake this whole platform exists to fix.\n\n"
    "NEVER guess. Not from the question, not from the expected answer, not from "
    "what a learner usually says — those are given to you for judging, never for "
    "filling in what you could not hear. If the recording is silence, noise, or "
    'words you cannot make out, write an empty string into "heard" and set the '
    'verdict to "unintelligible". An invented sentence is far worse than no '
    "sentence: the learner then gets corrected for something they never said, "
    "and stops trusting every correction after it.\n\n"
    'Add "heard" to the JSON you return, as the first field. Everything else '
    "stays exactly as described below."
)


# Erkin suhbatda backend savol ham, reaksiya ham yozmaydi — ularni Live modeli
# o'z ovozida o'zi topadi. Ya'ni `reaction`, `hint`, `next_question`, `options`
# va `tone` generatsiyasi sof yo'qotilgan vaqt: o'lchovda javob 188 tokendan
# 60 ga tushdi, o'quvchi esa shuncha vaqt jim kutib turadi.
FAST_BLOCK = (
    "SPEED RULE — the learner is sitting in silence until this answer comes "
    "back.\n"
    "Return ONLY these fields: heard, verdict, target_structure_used, errors, "
    "fluency, model_answer.\n"
    "Leave out reaction, hint, next_question, options and tone completely — the "
    "voice partner writes its own words. Every extra field is extra silence."
)

# Backend savol/reaksiya yozmaydigan rejimlar (§content.FREE_FLOW_MODES).
FAST_MODES = tuple(FREE_FLOW_MODES)


def system_prompt(target_structure: str = "", *, fast: bool = False) -> str:
    parts = [TRANSCRIBE_BLOCK]
    focus = asr.focus_for(target_structure)
    if focus:
        parts.append(
            f"This particular lesson is about {focus} — check that part of the "
            "audio twice before you write it. It is almost inaudible and Uzbek "
            "learners drop it constantly. If you do not CLEARLY hear it, leave "
            "it out. This does not lower your attention on everything else."
        )
    parts.append(coach.system_prompt())
    if fast:
        parts.append(FAST_BLOCK)
    return "\n\n".join(parts)


def _endpoint() -> str:
    return (
        f"https://{settings.GEMINI_LIVE_HOST}/v1beta/models/{settings.LISTEN_MODEL}:generateContent"
    )


async def evaluate(ctx: coach.CoachContext, pcm: bytes) -> tuple[coach.CoachResult, str]:
    """Audio + kontekst → (baholash, so'zma-so'z matn).

    Xato bo'lsa `ok=False` natija qaytadi va chaqiruvchi zaxira yo'lga o'tadi.
    """
    if not settings.LISTEN_ENABLED or not settings.GEMINI_API_KEY or not pcm:
        return coach.fallback("listen_disabled"), ""
    if len(pcm) < settings.GEMINI_INPUT_SAMPLE_RATE:  # < 0.5 s — shovqin
        return coach.fallback("too_short"), ""
    # Nutqsiz bo'lakka model gap to'qib beradi (§asr.is_silence).
    if asr.is_silence(pcm):
        logger.info("listen_skipped_silence bytes=%d", len(pcm))
        return coach.fallback("nothing_heard"), ""

    wav = asr.pcm16_to_wav(pcm, settings.GEMINI_INPUT_SAMPLE_RATE)
    payload = {
        "systemInstruction": {
            "parts": [{"text": system_prompt(ctx.target_structure, fast=ctx.mode in FAST_MODES)}]
        },
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": ctx.to_user_prompt()},
                    {
                        "inlineData": {
                            "mimeType": "audio/wav",
                            "data": base64.b64encode(wav).decode(),
                        }
                    },
                ],
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.2,
            "maxOutputTokens": settings.LISTEN_MAX_TOKENS,
            # O'quvchi shu paytda kutib turibdi — o'ylash byudjeti kechikish.
            "thinkingConfig": {"thinkingBudget": settings.LISTEN_THINKING_BUDGET},
        },
    }

    started = time.monotonic()
    try:
        body = await _post_hedged(payload)
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("listen_failed: %s", asr.http_error_label(exc))
        return coach.fallback(type(exc).__name__), ""

    elapsed_ms = int((time.monotonic() - started) * 1000)
    data = _json_from(body)
    if data is None:
        out = coach.fallback("bad_json")
        out.usage = _usage(body)
        out.latency_ms = elapsed_ms
        # Sabab odatda modelda: JSON yopilmasdan kesiladi yoki model o'ylash
        # bloklarini javobga qo'shib yuboradi. `finish` va uzunlik busiz
        # ko'rinmaydi — chaqiruv esa jimgina zaxira yo'lga o'tib ketaveradi.
        logger.warning(
            "listen_bad_json ms=%d model=%s finish=%s len=%d",
            elapsed_ms,
            settings.LISTEN_MODEL,
            _finish_reason(body),
            len(_raw_text(body)),
        )
        return out, ""

    result = coach.normalize(data)
    result.ok = True
    result.usage = _usage(body)
    result.latency_ms = elapsed_ms
    heard = " ".join(str(data.get("heard") or "").split())[:600]
    logger.info("listen ms=%d verdict=%s heard=%r", elapsed_ms, result.verdict, heard)
    return result, heard


async def _post_once(payload: dict) -> dict:
    response = await _client().post(
        _endpoint(),
        params={"key": settings.GEMINI_API_KEY},
        json=payload,
        timeout=settings.LISTEN_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


async def _post_hedged(payload: dict) -> dict:
    """Sekin ketgan so'rovni ikkinchisi bilan quvib o'tadi.

    Nega kerak: bu chaqiruvning o'zi arzon va tez, lekin tarmoq YO'LI beqaror —
    o'lchovda bir xil arzimas so'rov 0.7 s dan 3.1 s gacha ketdi (konteynerda
    ham, host'da ham bir xil, ya'ni sabab Docker emas). O'quvchi esa shu vaqt
    jim kutib turadi va aynan shu "dum" sekinlik bo'lib seziladi.

    Shuning uchun birinchi so'rov belgilangan vaqtda javob bermasa, IKKINCHI
    bir xil so'rov yuboriladi va qaysi biri avval qaytsa — o'sha ishlatiladi.
    Qo'shimcha chaqiruv faqat sekin holatlarda sarflanadi.
    """
    after = settings.LISTEN_HEDGE_AFTER_SECONDS
    first = asyncio.ensure_future(_post_once(payload))
    if after <= 0:
        return await first

    done, _ = await asyncio.wait({first}, timeout=after)
    if done:
        return first.result()

    logger.info("listen_hedged after=%.1fs", after)
    second = asyncio.ensure_future(_post_once(payload))
    tasks = {first, second}
    try:
        while tasks:
            done, tasks = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            winner = next(iter(done))
            if winner.exception() is None:
                return winner.result()
            # Birinchisi yiqildi — ikkinchisiga hali umid bor.
            if not tasks:
                raise winner.exception()
    finally:
        for task in (first, second):
            if not task.done():
                task.cancel()
    raise GeminiListenError("hedged so'rovlar javob bermadi")  # pragma: no cover


class GeminiListenError(httpx.HTTPError):
    pass


def _raw_text(body: dict) -> str:
    try:
        parts = body["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError):
        return ""
    return "".join(str(p.get("text") or "") for p in parts).strip()


def _finish_reason(body: dict) -> str:
    try:
        return str(body["candidates"][0].get("finishReason") or "")
    except (KeyError, IndexError, TypeError):
        return ""


def _json_from(body: dict) -> dict | None:
    raw = _raw_text(body)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _usage(body: dict) -> dict:
    usage = body.get("usageMetadata") or {}
    return {
        "model": settings.LISTEN_MODEL,
        "in": int(usage.get("promptTokenCount") or 0),
        "out": int(usage.get("candidatesTokenCount") or 0),
    }


_clients: dict[int, httpx.AsyncClient] = {}


def _client() -> httpx.AsyncClient:
    import asyncio

    loop_key = id(asyncio.get_running_loop())
    client = _clients.get(loop_key)
    if client is None or client.is_closed:
        if len(_clients) >= 8:
            _clients.clear()
        client = httpx.AsyncClient()
        _clients[loop_key] = client
    return client


async def aclose() -> None:
    for client in list(_clients.values()):
        if not client.is_closed:
            await client.aclose()
    _clients.clear()
