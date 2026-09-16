"""Sessiya narxini hisoblash — Gemini Live `usageMetadata` → USD.

Optimizatsiyani o'lchamasdan qilib bo'lmaydi. Bu modul har sessiyaga aniq
dollar qiymatini beradi, shuning uchun keyingi har bir o'zgarish raqam bilan
isbotlanadi.

Narxlar `settings.LIVE_PRICING` / `settings.TEXT_LLM_PRICING` da (1M token
uchun USD) va env orqali yangilanadi — Google narxni o'zgartirsa kod tegilmaydi.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field

from django.conf import settings

logger = logging.getLogger(__name__)

# Faqat inson o'qishi uchun (log, admin). Hisob-kitob har doim tokenda.
# Google narxlaridan olingan: audio out $12/1M ≈ $0.018/daqiqa → 25 token/s.
AUDIO_TOKENS_PER_SECOND = 25.0

# usageMetadata maydonlari provayder versiyasiga qarab turlicha nomlanadi.
_PROMPT_TOTAL_KEYS = ("promptTokenCount", "prompt_token_count")
_RESPONSE_TOTAL_KEYS = (
    "responseTokenCount",
    "response_token_count",
    "candidatesTokenCount",
    "candidates_token_count",
)
_PROMPT_DETAIL_KEYS = ("promptTokensDetails", "prompt_tokens_details")
_RESPONSE_DETAIL_KEYS = ("responseTokensDetails", "response_tokens_details")
_TOOL_PROMPT_KEYS = ("toolUsePromptTokenCount", "tool_use_prompt_token_count")


def _first_int(data: dict, keys: tuple[str, ...]) -> int:
    for key in keys:
        value = data.get(key)
        if isinstance(value, int | float):
            return int(value)
    return 0


def _first_list(data: dict, keys: tuple[str, ...]) -> list:
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            return value
    return []


@dataclass
class Breakdown:
    """Bitta sessiyaning to'liq sarfi."""

    text_in_tokens: int = 0
    audio_in_tokens: int = 0
    text_out_tokens: int = 0
    audio_out_tokens: int = 0
    live_usd: float = 0.0

    llm_in_tokens: int = 0
    llm_out_tokens: int = 0
    llm_calls: int = 0
    llm_usd: float = 0.0

    total_usd: float = 0.0
    # Qaysi narx jadvali qo'llanilgani — keyin audit qilish uchun.
    live_model: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def audio_in_seconds(self) -> float:
        return round(self.audio_in_tokens / AUDIO_TOKENS_PER_SECOND, 1)

    @property
    def audio_out_seconds(self) -> float:
        return round(self.audio_out_tokens / AUDIO_TOKENS_PER_SECOND, 1)


# --- narx jadvallari -------------------------------------------------------


def resolve_live_prices(model: str) -> dict:
    """Model nomiga eng mos narx qatorini topadi (prefiks bo'yicha)."""
    name = (model or "").removeprefix("models/")
    table = settings.LIVE_PRICING
    best_key = ""
    for key in table:
        if key != "default" and name.startswith(key) and len(key) > len(best_key):
            best_key = key
    return table.get(best_key) or table["default"]


def resolve_text_prices(model: str) -> dict:
    """Coach/tahlil LLM'i uchun narx qatori."""
    name = model or ""
    table = settings.TEXT_LLM_PRICING
    best_key = ""
    for key in table:
        if key != "default" and key in name and len(key) > len(best_key):
            best_key = key
    return table.get(best_key) or table["default"]


# --- usageMetadata ---------------------------------------------------------


def merge_usage(previous: dict | None, incoming: dict | None) -> dict:
    """Ketma-ket kelgan `usageMetadata` snapshotlarini birlashtiradi.

    Gemini Live har javobda sessiya boshidan hisoblangan KUMULYATIV qiymatni
    yuboradi, shuning uchun har hisoblagich bo'yicha maksimum olinadi: kumulyativ
    bo'lsa bu oxirgi snapshotga teng, agar provayder navbat-bo'yicha yuborsa ham
    ikki marta sanalmaydi (kam sanaladi — buni `scripts/live_spike.py` tekshiradi).
    """
    if not incoming:
        return dict(previous or {})
    if not previous:
        return dict(incoming)

    merged = dict(previous)
    for key, value in incoming.items():
        old = merged.get(key)
        if isinstance(value, int | float) and isinstance(old, int | float):
            merged[key] = max(old, value)
        elif isinstance(value, list) and isinstance(old, list):
            merged[key] = _merge_detail_lists(old, value)
        else:
            merged[key] = value
    merged["snapshots"] = int(previous.get("snapshots") or 1) + 1
    return merged


def _merge_detail_lists(old: list, new: list) -> list:
    """`[{modality: AUDIO, tokenCount: N}]` ro'yxatlarini modalitet bo'yicha birlashtiradi."""
    by_modality: dict[str, int] = {}
    for item in list(old) + list(new):
        if not isinstance(item, dict):
            continue
        modality = str(item.get("modality") or item.get("Modality") or "").upper()
        count = _first_int(item, ("tokenCount", "token_count"))
        by_modality[modality] = max(by_modality.get(modality, 0), count)
    return [{"modality": m, "tokenCount": c} for m, c in by_modality.items()]


def split_modalities(usage: dict | None) -> dict[str, int]:
    """`usageMetadata` ni text/audio bo'yicha ajratadi.

    Modalitet tafsiloti bo'lmasa — hammasi audio deb hisoblanadi (audio ancha
    qimmat, ya'ni xato tomonga emas, ehtiyotkor tomonga qarab yaxlitlaymiz).
    """
    usage = usage or {}
    out = {"text_in": 0, "audio_in": 0, "text_out": 0, "audio_out": 0}

    prompt_total = _first_int(usage, _PROMPT_TOTAL_KEYS) + _first_int(usage, _TOOL_PROMPT_KEYS)
    response_total = _first_int(usage, _RESPONSE_TOTAL_KEYS)

    for details, text_key, audio_key, total in (
        (_first_list(usage, _PROMPT_DETAIL_KEYS), "text_in", "audio_in", prompt_total),
        (_first_list(usage, _RESPONSE_DETAIL_KEYS), "text_out", "audio_out", response_total),
    ):
        seen = 0
        for item in details:
            if not isinstance(item, dict):
                continue
            modality = str(item.get("modality") or item.get("Modality") or "").upper()
            count = _first_int(item, ("tokenCount", "token_count"))
            seen += count
            if modality == "AUDIO":
                out[audio_key] += count
            else:
                # TEXT, IMAGE, VIDEO, MODALITY_UNSPECIFIED — matn narxida.
                out[text_key] += count
        if seen == 0 and total > 0:
            out[audio_key] = total
        elif total > seen:
            # Tafsilotda ko'rsatilmagan qoldiq.
            out[audio_key] += total - seen

    return out


# --- hisoblash -------------------------------------------------------------


def live_breakdown(usage: dict | None, model: str) -> Breakdown:
    prices = resolve_live_prices(model)
    parts = split_modalities(usage)

    bd = Breakdown(
        text_in_tokens=parts["text_in"],
        audio_in_tokens=parts["audio_in"],
        text_out_tokens=parts["text_out"],
        audio_out_tokens=parts["audio_out"],
        live_model=(model or "").removeprefix("models/"),
    )
    bd.live_usd = round(
        (
            bd.text_in_tokens * prices["text_in"]
            + bd.audio_in_tokens * prices["audio_in"]
            + bd.text_out_tokens * prices["text_out"]
            + bd.audio_out_tokens * prices["audio_out"]
        )
        / 1_000_000,
        6,
    )
    if not usage:
        bd.notes.append("usage_missing")
    bd.total_usd = bd.live_usd
    return bd


def add_llm_call(bd: Breakdown, model: str, in_tokens: int, out_tokens: int) -> Breakdown:
    """Coach yoki tahlil LLM'ining bitta chaqiruvini qo'shadi."""
    prices = resolve_text_prices(model)
    bd.llm_in_tokens += max(0, int(in_tokens or 0))
    bd.llm_out_tokens += max(0, int(out_tokens or 0))
    bd.llm_calls += 1
    bd.llm_usd = round(
        bd.llm_usd
        + (
            max(0, int(in_tokens or 0)) * prices["text_in"]
            + max(0, int(out_tokens or 0)) * prices["text_out"]
        )
        / 1_000_000,
        6,
    )
    bd.total_usd = round(bd.live_usd + bd.llm_usd, 6)
    return bd


def session_breakdown(usage: dict | None, model: str, llm_calls: list[dict] | None = None):
    """Sessiyaning to'liq sarfi: Live + barcha matn LLM chaqiruvlari.

    `llm_calls` — `[{"model": ..., "in": N, "out": N}]` ko'rinishida; coach va
    post-session tahlil o'z chaqiruvlarini shu shaklda yozib boradi.
    """
    bd = live_breakdown(usage, model)
    for call in llm_calls or []:
        add_llm_call(
            bd,
            str(call.get("model") or ""),
            call.get("in") or call.get("in_tokens") or 0,
            call.get("out") or call.get("out_tokens") or 0,
        )
    return bd


def log_line(session_id, bd: Breakdown) -> str:
    """`session_cost` log eventi — grep qilinadigan bitta qator."""
    return (
        f"session_cost session_id={session_id} usd={bd.total_usd:.5f} "
        f"live_usd={bd.live_usd:.5f} llm_usd={bd.llm_usd:.5f} "
        f"audio_in_s={bd.audio_in_seconds} audio_out_s={bd.audio_out_seconds} "
        f"text_in={bd.text_in_tokens} text_out={bd.text_out_tokens} "
        f"llm_calls={bd.llm_calls} model={bd.live_model}"
    )
