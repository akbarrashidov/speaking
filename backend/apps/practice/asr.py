"""O'quvchi gapining SO'ZMA-SO'Z transkripti.

Nega kerak: Gemini Live'ning `inputAudioTranscription` moduli o'quvchi gapini
jimgina TO'G'RILAB beradi — "I from Uzbekistan" transkriptga "I'm from
Uzbekistan." bo'lib tushadi. Bu oddiy suhbat uchun yaxshi, grammatika
o'rgatadigan platforma uchun esa halokatli: coach xatoni ko'rmaydi, o'quvchi
ekranda o'zining to'g'ri gapini ko'radi va xato tuzatilmay qoladi.

Shuning uchun o'quvchi audiosi alohida chaqiruvda, "hech narsani tuzatma"
ko'rsatmasi bilan qaytadan transkript qilinadi. Faqat SHU matn coachga boradi
va ekranda ko'rinadi.

Chaqiruv kritik yo'lda emas: yiqilsa Live transkripti ishlatiladi (ya'ni eski
xatti-harakat), sessiya to'xtamaydi.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import math
import struct
import time

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

PROMPT = (
    "This is one utterance from an Uzbek learner of English, recorded in a "
    "speaking lesson.\n\n"
    "Write down EXACTLY what you hear, word for word. Your transcript is the "
    "only evidence of how they actually speak — every mistake you smooth over "
    "is a mistake they will never be taught.\n\n"
    "NEVER add, remove or change a single word to make the English correct. "
    "In particular, keep every one of these exactly as spoken:\n"
    '- Forms of "be": am, is, are, was, were, and the contractions (I\'m, '
    'he\'s, they\'re). If they say "I from Uzbekistan", write "I from '
    'Uzbekistan".\n'
    "- Auxiliaries: do, does, did, have, has, will, would, can, should.\n"
    "- Articles: a, an, the. Missing ones stay missing; wrong ones stay wrong.\n"
    '- Endings: plural "-s", third-person "-s", possessive "\'s", past "-ed", '
    'continuous "-ing". If you hear "two book", write "two book".\n'
    "- Irregular forms exactly as produced: go / went / goed / gone.\n"
    "- Prepositions exactly as said (in, on, at, to, from, for) — including "
    "missing ones.\n"
    "- Pronouns and subjects, including a missing subject "
    '("Is very hot today").\n'
    "- Word order exactly as spoken, even when it is wrong "
    '("Yesterday I to the shop went").\n'
    "- Repeated words, restarts and self-corrections, as they came out.\n"
    "- Singular/plural and subject-verb agreement as produced "
    '("He go", "They is").\n\n'
    "Other rules:\n"
    "- Keep filler sounds only if they are clearly words (um, uh).\n"
    "- If a word is in Uzbek or Russian, write it as you hear it.\n"
    "- Punctuate and capitalise normally — that part is yours, since it "
    "cannot be heard. Everything else is theirs.\n"
    "- NEVER invent. If the recording is silence, background noise, music, or "
    "words you simply cannot make out, return an empty string and nothing else. "
    "Do not reach for what a learner usually says, and do not build a sentence "
    "out of a few recognisable sounds. A guessed sentence is far worse than an "
    "empty one: the learner then gets corrected for something they never said.\n"
    "- Write only what is in THIS recording. There is no conversation, no "
    "question and no expected answer for you to lean on.\n"
)

# Sessiyaning grammatik mavzusi — quloqqa QO'SHIMCHA yo'nalish.
#
# Nega kerak: "I from" va "I'm from" farqi ~50 ms ovozli tovush. Yuqoridagi
# umumiy ro'yxat barcha shakllarni qamraydi, bu esa darsning o'z shakliga
# alohida e'tibor qo'shadi — u eng ko'p tekshiriladigan joy.
LISTEN_FOR = {
    "to_be": 'the forms of "be" — am, is, are — and their contractions',
    "present_continuous": 'both parts: "am/is/are" AND the "-ing" ending',
    "present_simple": 'the third-person "-s" ending, and the auxiliaries do / does',
    "past_simple": 'the "-ed" ending, irregular past forms (went, saw, had), '
    "and whether the auxiliary did is present",
    "article": "the articles a, an, the",
    "plural": 'the plural "-s" ending at the end of nouns',
    "possessive": "the possessive 's ending",
    "modal": "modal verbs — can, must, should, will — and whether one is there at all",
    "preposition": "the exact preposition (in, on, at, to, from)",
    "comparative": 'comparative endings ("-er") and the word than',
    "future": "will / going to, and whether either is there at all",
    "perfect": "have / has / had together with the participle form",
}

TAIL = 'Return STRICT JSON: {"text": "<exactly what was said>"}'


def focus_for(target_structure: str) -> str:
    """Shu darsning shakli uchun qo'shimcha tinglash ko'rsatmasi (bo'lsa)."""
    name = (target_structure or "").lower()
    for key, what in LISTEN_FOR.items():
        if key in name:
            return what
    return ""


def build_prompt(target_structure: str = "") -> str:
    """So'zma-so'z ko'rsatma + shu darsning shakliga qo'shimcha e'tibor."""
    focus = focus_for(target_structure)
    if not focus:
        return f"{PROMPT}\n{TAIL}"

    return (
        f"{PROMPT}\n"
        f"This particular lesson is about {focus} — so check that part of the "
        "audio twice before you write it. It is almost inaudible and Uzbek "
        "learners drop it constantly. If you do not CLEARLY hear it, leave it "
        "out. This does not lower your attention on everything else above.\n\n"
        f"{TAIL}"
    )


# Shu RMS dan past signal — nutq emas, xona shovqini yoki mikrofon jimligi.
# 16-bit shkalada (0..32767) juda past ostona: haqiqiy shivirlash ham bundan
# baland chiqadi, ya'ni gapirgan o'quvchi hech qachon kesilmaydi.
SILENCE_RMS = 200

# Ostonani o'lchash uchun butun bo'lakni sanash shart emas — qadam bilan
# olingan shuncha namuna yetarli, va bu kritik yo'lda millisekundlarni yeydi.
SILENCE_SAMPLES = 4000


def http_error_label(exc: Exception) -> str:
    """Xatoni logga yozish uchun QISQA yorliq.

    `httpx` xato matni to'liq URL'ni o'z ichiga oladi, URL'da esa `?key=` —
    ya'ni xom `str(exc)` API kalitini logga chiqaradi.
    """
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return f"{type(exc).__name__} status={status}" if status else type(exc).__name__


def is_silence(pcm: bytes) -> bool:
    """Bo'lakda nutq bormi. LLM'gacha, deterministik.

    Nega kerak: modellar nutqsiz audioga JAVOB TO'QIYDI. Jimlikka ham,
    shovqinga ham "I am from Uzbekistan." deb qaytaradi — barchasi, prompt
    qanchalik qat'iy bo'lmasin (o'lchab ko'rilgan). Bunday to'qima gap
    baholanadi, ekranga chiqadi va AI o'quvchi aytmagan gapni "tuzatadi".
    Shuning uchun bunday bo'lak modelga umuman yuborilmaydi.
    """
    count = len(pcm) // 2
    if count == 0:
        return True
    step = max(1, count // SILENCE_SAMPLES)
    total = 0
    taken = 0
    for offset in range(0, count * 2, step * 2):
        (sample,) = struct.unpack_from("<h", pcm, offset)
        total += sample * sample
        taken += 1
    return math.sqrt(total / taken) < SILENCE_RMS


def pcm16_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    """Xom PCM'ga WAV sarlavhasi. `generateContent` audio/pcm qabul qilmaydi."""
    buffer = io.BytesIO()
    buffer.write(b"RIFF")
    buffer.write(struct.pack("<I", 36 + len(pcm)))
    buffer.write(b"WAVEfmt ")
    buffer.write(struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16))
    buffer.write(b"data")
    buffer.write(struct.pack("<I", len(pcm)))
    buffer.write(pcm)
    return buffer.getvalue()


def endpoint() -> str:
    """Audio-in / JSON-out chaqiruvlar uchun manzil (§shadow.py ham ishlatadi)."""
    return f"https://{settings.GEMINI_LIVE_HOST}/v1beta/models/{settings.ASR_MODEL}:generateContent"


async def transcribe(pcm: bytes, target_structure: str = "") -> tuple[str, dict]:
    """16 kHz mono PCM16 → so'zma-so'z matn va token sarfi.

    Xato bo'lsa bo'sh satr qaytaradi — chaqiruvchi Live transkriptida qoladi.
    """
    if not settings.ASR_ENABLED or not settings.GEMINI_API_KEY or not pcm:
        return "", {}

    # Juda qisqa bo'lak — nutq emas, shovqin.
    if len(pcm) < settings.GEMINI_INPUT_SAMPLE_RATE:  # < 0.5 s
        return "", {}
    if is_silence(pcm):
        logger.info("asr_skipped_silence bytes=%d", len(pcm))
        return "", {}

    wav = pcm16_to_wav(pcm, settings.GEMINI_INPUT_SAMPLE_RATE)
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": build_prompt(target_structure)},
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
            "temperature": 0,
            "maxOutputTokens": settings.ASR_MAX_TOKENS,
            # O'ylash kerak emas — bu eshitish vazifasi, va har o'quvchi
            # navbatida ishlaydi, ya'ni tez bo'lishi shart.
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }

    started = time.monotonic()
    try:
        response = await client().post(
            endpoint(),
            params={"key": settings.GEMINI_API_KEY},
            json=payload,
            timeout=settings.ASR_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("asr_failed: %s", http_error_label(exc))
        return "", {}

    elapsed_ms = int((time.monotonic() - started) * 1000)
    text = _text_from(body)
    usage = usage_from(body)
    logger.info("asr ms=%d chars=%d", elapsed_ms, len(text))
    return text, usage


def _text_from(body: dict) -> str:
    try:
        parts = body["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError):
        return ""
    raw = "".join(str(p.get("text") or "") for p in parts).strip()
    if not raw:
        return ""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return ""
    if not isinstance(data, dict):
        return ""
    return " ".join(str(data.get("text") or "").split())[:600]


def usage_from(body: dict) -> dict:
    usage = body.get("usageMetadata") or {}
    return {
        "model": settings.ASR_MODEL,
        "in": int(usage.get("promptTokenCount") or 0),
        "out": int(usage.get("candidatesTokenCount") or 0),
    }


_clients: dict[int, httpx.AsyncClient] = {}


def client() -> httpx.AsyncClient:
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
