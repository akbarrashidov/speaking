"""Shadowing baholash: o'quvchi takrori etalon gapga qanchalik yaqin (§4.3).

Uch narsa o'lchanadi va ular ATAYLAB har xil manbadan keladi:

  1. **So'zlar** — o'quvchi aytgani (so'zma-so'z transkript) etalon gap bilan
     solishtiriladi. Tushib qolgan, qo'shilgan va o'zgargan so'zlar aniq
     ko'rsatiladi. Bu sof matn ustidagi hisob — tekin va aniq.
  2. **Sur'at** — nutq uzunligi etalon bilan taqqoslanadi. Etalon: video klip
     uzunligi (aniq), video bo'lmasa gapning tabiiy uzunligi (so'z soni /
     `SHADOW_REFERENCE_WPM`). Bu ham o'lchov, taxmin emas.
  3. **Talaffuz** — buni matndan bilib bo'lmaydi, shuning uchun o'quvchi
     YOZUVI modelga eshittiriladi va u bitta qisqa izoh qaytaradi
     ("shu yerini shunday de"). Model yiqilsa, izoh birinchi ikki o'lchovdan
     yoziladi — ekran hech qachon bo'sh qolmaydi.

Ball ham shunga mos: 70% so'zlar, 30% sur'at. Talaffuz ballga QO'SHILMAYDI —
uni raqamga aylantirish uchun fonemalar darajasida tekshiruv kerak, bizda esa
u yo'q. Yo'q narsani bor qilib ko'rsatgandan ko'ra, izoh bo'lib qolgani rost.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher

import httpx
from django.conf import settings

from . import asr

logger = logging.getLogger(__name__)

WORD_RE = re.compile(r"[a-z']+")

# Qisqartmalar shadowingda MAQSAD: "I am" deb aytish gapni to'g'ri qiladi-yu,
# tabiiy nutqni buzadi. Shuning uchun ular alohida belgilanadi.
CONTRACTIONS = {
    "i'm": "i am",
    "you're": "you are",
    "we're": "we are",
    "they're": "they are",
    "he's": "he is",
    "she's": "she is",
    "it's": "it is",
    "that's": "that is",
    "there's": "there is",
    "i'd": "i would",
    "i'll": "i will",
    "we'll": "we will",
    "you'll": "you will",
    "don't": "do not",
    "doesn't": "does not",
    "didn't": "did not",
    "isn't": "is not",
    "aren't": "are not",
    "can't": "cannot",
    "won't": "will not",
    "shouldn't": "should not",
    "couldn't": "could not",
    "haven't": "have not",
    "hasn't": "has not",
    "wasn't": "was not",
    "weren't": "were not",
}

WORD_WEIGHT = 0.7
TEMPO_WEIGHT = 0.3


def words(text: str) -> list[str]:
    return WORD_RE.findall((text or "").lower())


def _expanded(tokens: list[str]) -> list[str]:
    """Qisqartmalarni yoyadi — ma'no bo'yicha solishtirish uchun."""
    out: list[str] = []
    for token in tokens:
        out.extend(CONTRACTIONS.get(token, token).split())
    return out


def reference_ms(
    reference: str,
    clip_start_ms: int | None = None,
    clip_end_ms: int | None = None,
    played_ms: int = 0,
) -> int:
    """Etalon uzunlik — uchta manba, aniqligi bo'yicha tartibda.

    1. Video klip oralig'i — eng aniq, chunki o'quvchi AYNAN shuni eshitgan.
    2. Klient o'lchagan eshittirish uzunligi (video biriktirilmagan gapni
       brauzer ovozi aytadi) — bu ham o'lchov, taxmin emas.
    3. Gapning tabiiy uzunligi (so'z soni / `SHADOW_REFERENCE_WPM`) — faqat
       birinchi ikkisi bo'lmaganda.
    """
    if clip_start_ms is not None and clip_end_ms is not None and clip_end_ms > clip_start_ms:
        return clip_end_ms - clip_start_ms
    if played_ms and played_ms > 0:
        return int(played_ms)
    count = max(1, len(words(reference)))
    return int(count / settings.SHADOW_REFERENCE_WPM * 60_000)


@dataclass
class ShadowScore:
    """Bitta takrorning natijasi."""

    idx: int = 0
    score: int = 0
    word_accuracy: float = 0.0
    tempo: float = 0.0
    tempo_label: str = "unknown"  # too_fast | good | too_slow | unknown
    missed: list[str] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)
    # "I'm" o'rniga "I am" deyilgan joylar — shadowingda bu asosiy xato.
    contractions_lost: list[str] = field(default_factory=list)
    reference: str = ""
    heard: str = ""
    reference_ms: int = 0
    spoken_ms: int = 0
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _tempo_fit(tempo: float) -> float:
    """Sur'at ballga qanday aylanadi: oraliq ichida 1.0, chetda tez pasayadi."""
    low, high = settings.SHADOW_TEMPO_MIN, settings.SHADOW_TEMPO_MAX
    if tempo <= 0:
        return 0.0
    if low <= tempo <= high:
        return 1.0
    distance = (low - tempo) if tempo < low else (tempo - high)
    return max(0.0, 1.0 - distance / 0.6)


def _tempo_label(tempo: float) -> str:
    if tempo <= 0:
        return "unknown"
    if tempo < settings.SHADOW_TEMPO_MIN:
        return "too_fast"
    if tempo > settings.SHADOW_TEMPO_MAX:
        return "too_slow"
    return "good"


def compare(
    reference: str,
    heard: str,
    *,
    spoken_ms: int = 0,
    clip_start_ms: int | None = None,
    clip_end_ms: int | None = None,
    played_ms: int = 0,
) -> ShadowScore:
    """Etalon gap va o'quvchi aytgani — o'lchanadigan hamma narsa shu yerda."""
    ref_tokens = words(reference)
    heard_tokens = words(heard)
    ref_ms = reference_ms(reference, clip_start_ms, clip_end_ms, played_ms)
    tempo = (spoken_ms / ref_ms) if (spoken_ms and ref_ms) else 0.0

    result = ShadowScore(
        reference=(reference or "").strip(),
        heard=(heard or "").strip(),
        reference_ms=ref_ms,
        spoken_ms=int(spoken_ms or 0),
        tempo=round(tempo, 2),
        tempo_label=_tempo_label(tempo),
    )
    if not ref_tokens:
        return result

    # Ma'no bo'yicha moslik: qisqartma yoyilgan holda solishtiriladi, ya'ni
    # "I am" degan o'quvchi so'zni TUSHIRIB qoldirgan hisoblanmaydi — u
    # alohida, yumshoqroq belgi oladi.
    ref_expanded = _expanded(ref_tokens)
    heard_expanded = _expanded(heard_tokens)
    matcher = SequenceMatcher(None, ref_expanded, heard_expanded, autojunk=False)
    result.word_accuracy = round(matcher.ratio(), 3) if heard_expanded else 0.0

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("delete", "replace"):
            result.missed.extend(ref_expanded[i1:i2])
        if tag in ("insert", "replace"):
            result.extra.extend(heard_expanded[j1:j2])

    heard_set = set(heard_tokens)
    result.contractions_lost = [
        token for token in ref_tokens if token in CONTRACTIONS and token not in heard_set
    ]

    fit = _tempo_fit(tempo) if tempo else 0.0
    weighted = result.word_accuracy * WORD_WEIGHT + fit * TEMPO_WEIGHT
    # Sur'at o'lchanmagan bo'lsa (yozuv yo'q) faqat so'zlar bo'yicha baho.
    if not tempo:
        weighted = result.word_accuracy
    result.score = int(round(weighted * 100))
    return result


# --- xulosa matni ---------------------------------------------------------
#
# Matn o'quvchi tilida va JUDA qisqa: sessiya davom etyapti, uzun izoh
# o'qilmaydi. Model yiqilsa ham ekranda gap turadi.

FALLBACK = {
    "uz": {
        "great": "Aynan shunday — so'zlar ham, sur'at ham joyida.",
        "missed": "Bu so'zlar tushib qoldi: {words}. Yana bir marta ayting.",
        "too_slow": "So'zlar to'g'ri, lekin sekinroq chiqdi — videodagi tezlikda urinib ko'ring.",
        "too_fast": "Biroz shoshildingiz — gapni videodagidek cho'zib ayting.",
        "contraction": '"{word}" ni to\'liq aytdingiz — qisqartmasi bilan ayting.',
        "again": "Gap to'liq chiqmadi, yana bir marta takrorlang.",
    },
    "ru": {
        "great": "Точно так — и слова, и темп на месте.",
        "missed": "Пропали слова: {words}. Повторите ещё раз.",
        "too_slow": "Слова верные, но медленнее — попробуйте в темпе видео.",
        "too_fast": "Немного поспешили — произнесите так же протяжно, как в видео.",
        "contraction": "Вы сказали «{word}» полностью — используйте сокращение.",
        "again": "Фраза вышла неполной, повторите ещё раз.",
    },
}


def fallback_note(score: ShadowScore, language: str = "uz") -> str:
    """O'lchovlardan yozilgan xulosa — model chaqirilmaganda ishlatiladi."""
    table = FALLBACK.get(language or "uz", FALLBACK["uz"])
    if score.word_accuracy < 0.5:
        return table["again"]
    if score.missed:
        return table["missed"].format(words=", ".join(score.missed[:3]))
    if score.contractions_lost:
        return table["contraction"].format(word=score.contractions_lost[0])
    if score.tempo_label == "too_slow":
        return table["too_slow"]
    if score.tempo_label == "too_fast":
        return table["too_fast"]
    return table["great"]


# --- talaffuz izohi (model o'quvchini ESHITADI) ---------------------------

PRONUNCIATION_PROMPT = """You hear a learner of English repeating one line after a
recording. You are given the exact line they were copying.

Write ONE short coaching sentence in {language_name} about their PRONUNCIATION —
how it sounded, not whether the grammar is right. Name the single word that needs
the most work and say how to say it, in plain words a beginner understands
("say the 'd' at the end", "the first part is longer: to-MO-rrow").

Rules:
- One sentence, maximum 15 words. It is read mid-exercise.
- Never mention grammar, never praise generally, never use phonetic symbols.
- If the pronunciation is genuinely close to the recording, say so in one short
  sentence and name nothing.

Return STRICT JSON: {{"word": "<the word, or empty>", "note": "<one sentence>"}}"""

LANGUAGE_NAMES = {"uz": "Uzbek", "ru": "Russian"}


async def pronunciation_note(pcm: bytes, reference: str, language: str = "uz") -> tuple[str, dict]:
    """O'quvchi yozuvini modelga eshittirib, bitta qisqa izoh oladi.

    Xato yoki o'chirilgan bo'lsa — bo'sh satr; chaqiruvchi o'lchovlardan
    yozilgan izohga qaytadi.
    """
    if not settings.SHADOW_PRONUNCIATION_ENABLED or not settings.GEMINI_API_KEY or not pcm:
        return "", {}
    if len(pcm) < settings.GEMINI_INPUT_SAMPLE_RATE:  # < 0.5 s — nutq emas
        return "", {}

    wav = asr.pcm16_to_wav(pcm, settings.GEMINI_INPUT_SAMPLE_RATE)
    prompt = PRONUNCIATION_PROMPT.format(
        language_name=LANGUAGE_NAMES.get(language or "uz", "Uzbek")
    )
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": f'{prompt}\n\nThe line they copied: "{reference}"'},
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
            "maxOutputTokens": 200,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }

    started = time.monotonic()
    try:
        response = await asr.client().post(
            asr.endpoint(),
            params={"key": settings.GEMINI_API_KEY},
            json=payload,
            timeout=settings.SHADOW_PRONUNCIATION_TIMEOUT,
        )
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("shadow_pronunciation_failed: %s", asr.http_error_label(exc))
        return "", {}

    try:
        text = body["candidates"][0]["content"]["parts"][0]["text"]
        data = json.loads(text)
        note = " ".join(str(data.get("note") or "").split())[:200]
    except (KeyError, IndexError, ValueError, TypeError):
        logger.warning("shadow_pronunciation_unparsed")
        return "", {}

    usage = asr.usage_from(body)
    logger.info(
        "shadow_pronunciation ms=%d note=%r", int((time.monotonic() - started) * 1000), note[:60]
    )
    return note, usage
