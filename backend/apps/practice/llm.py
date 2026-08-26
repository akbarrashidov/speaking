"""OpenAI-mos chat endpointiga qat'iy JSON so'rovi — coach va tahlil uchun umumiy.

Bitta joyda: so'rov shakli, reasoning modellarning o'ziga xosligi, JSON'ni
qutqarib olish va token sarfini qaytarish. Provayder almashsa faqat shu fayl
tegiladi.

Coach real vaqtda, WS consumer ichida ishlaydi — shuning uchun async variant
ham bor va HTTP ulanish qayta ishlatiladi (har chaqiruvda TLS qo'l berish
kechikishni 100–200 ms ga oshirardi).
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

# Har event loop uchun bitta klient (Daphne'da bitta loop; testlarda bir nechta).
_async_clients: dict[int, httpx.AsyncClient] = {}
_MAX_CACHED_CLIENTS = 8


@dataclass
class LLMResult:
    """Chaqiruv natijasi. `ok=False` bo'lsa `data` ishonchsiz — fallback ishlaydi."""

    ok: bool = False
    data: dict = field(default_factory=dict)
    raw: str = ""
    usage: dict = field(default_factory=dict)
    error: str = ""
    latency_ms: int = 0


def build_payload(
    *,
    model: str,
    system: str,
    user: str,
    temperature: float = 0.2,
    reasoning_effort: str = "",
    max_tokens: int | None = None,
) -> dict:
    payload: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }
    # Reasoning modellar (gpt-oss va h.k.) uchun. Bo'sh bo'lsa yuborilmaydi —
    # buni qo'llab-quvvatlamaydigan provayder noma'lum maydondan xato beradi.
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort
    if max_tokens:
        payload["max_tokens"] = max_tokens
    return payload


def _endpoint(base: str) -> str:
    return f"{base.rstrip('/')}/chat/completions"


def _headers(key: str) -> dict:
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def message_content(body: dict) -> str:
    """Javobdan matnni oladi.

    Reasoning modellar (gpt-oss) o'ylash qismini alohida `reasoning_content`
    maydonida qaytaradi va ba'zan `content` ni bo'sh qoldiradi — o'sha holda
    zaxira sifatida o'ylash matnidan JSON qidiriladi.
    """
    message = body["choices"][0]["message"]
    content = (message.get("content") or "").strip()
    if content:
        return content
    return (message.get("reasoning_content") or "").strip()


def token_usage(body: dict, model: str) -> dict:
    """Narx hisobi uchun token sarfi (`cost.add_llm_call` kutgan shakl)."""
    usage = body.get("usage") or {}
    return {
        "model": model,
        "in": int(usage.get("prompt_tokens") or 0),
        "out": int(usage.get("completion_tokens") or 0),
    }


def parse_json(content: str) -> dict | None:
    """Modeldan kelgan matndan JSON obyektini qutqarib oladi."""
    content = (content or "").strip()
    if content.startswith("```"):
        content = content.strip("`")
        content = content.split("\n", 1)[-1] if "\n" in content else content
        if content.rstrip().endswith("```"):
            content = content.rstrip()[:-3]
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        start, end = content.find("{"), content.rfind("}")
        if start == -1 or end <= start:
            return salvage_truncated(content)
        try:
            data = json.loads(content[start : end + 1])
        except json.JSONDecodeError:
            return salvage_truncated(content)
    return data if isinstance(data, dict) else None


def salvage_truncated(content: str) -> dict | None:
    """Yarmida kesilgan JSON'dan to'liq bo'lgan qismini qutqaradi.

    Reasoning modellar (gpt-oss) o'ylash tokenlarini ham `completion` hisobiga
    yozadi, shuning uchun `max_tokens` ga urilib javob gap o'rtasida uzilishi
    real hodisa. To'liq yozilgan maydonlarni tashlab yuborish o'rniga — oxirgi
    tugallangan qiymatgacha kesamiz va ochiq qavslarni yopamiz.
    """
    start = content.find("{")
    if start == -1:
        return None

    text = content[start:]
    stack: list[str] = []
    in_string = escaped = False
    cut: tuple[int, list[str]] | None = None  # (kesish joyi, yopilmagan qavslar)

    for i, ch in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if stack:
                stack.pop()
            cut = (i + 1, list(stack))
        elif ch == "," and stack:
            cut = (i, list(stack))

    if cut is None:
        return None
    end, unclosed = cut
    candidate = text[:end].rstrip().rstrip(",") + "".join(reversed(unclosed))
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _interpret(body: dict, model: str, elapsed_ms: int) -> LLMResult:
    usage = token_usage(body, model)
    raw = message_content(body)
    parsed = parse_json(raw)
    if parsed is None:
        # `finish_reason` bad_json sababini bir qarashda aytadi: "length" bo'lsa
        # javob kesilgan (max_tokens kichik), "stop" bo'lsa model JSON yozmagan.
        finish = (body.get("choices") or [{}])[0].get("finish_reason") or "?"
        logger.warning(
            "llm_bad_json model=%s finish=%s out_tokens=%s raw_head=%r",
            model,
            finish,
            usage.get("out"),
            raw[:120],
        )
        return LLMResult(ok=False, raw=raw, usage=usage, error="bad_json", latency_ms=elapsed_ms)
    return LLMResult(ok=True, data=parsed, raw=raw, usage=usage, latency_ms=elapsed_ms)


# --- sync (Celery pipeline) ------------------------------------------------


def chat_json(
    *,
    base: str,
    key: str,
    model: str,
    system: str,
    user: str,
    timeout: float = 60.0,
    **kwargs,
) -> LLMResult:
    if not key:
        return LLMResult(ok=False, error="no_api_key")
    payload = build_payload(model=model, system=system, user=user, **kwargs)
    started = _now_ms()
    try:
        response = httpx.post(_endpoint(base), headers=_headers(key), json=payload, timeout=timeout)
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("llm_call_failed model=%s: %s", model, exc)
        return LLMResult(ok=False, error=type(exc).__name__, latency_ms=_now_ms() - started)
    try:
        return _interpret(body, model, _now_ms() - started)
    except (KeyError, IndexError, TypeError) as exc:
        logger.warning("llm_bad_shape model=%s: %s", model, exc)
        return LLMResult(ok=False, error="bad_shape", latency_ms=_now_ms() - started)


# --- async (WS consumer, real vaqt) ---------------------------------------


def _client() -> httpx.AsyncClient:
    loop_key = id(asyncio.get_running_loop())
    client = _async_clients.get(loop_key)
    if client is None or client.is_closed:
        if len(_async_clients) >= _MAX_CACHED_CLIENTS:
            _async_clients.clear()
        client = httpx.AsyncClient()
        _async_clients[loop_key] = client
    return client


async def achat_json(
    *,
    base: str,
    key: str,
    model: str,
    system: str,
    user: str,
    timeout: float = 6.0,
    **kwargs,
) -> LLMResult:
    if not key:
        return LLMResult(ok=False, error="no_api_key")
    payload = build_payload(model=model, system=system, user=user, **kwargs)
    started = _now_ms()
    try:
        response = await _client().post(
            _endpoint(base), headers=_headers(key), json=payload, timeout=timeout
        )
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("llm_acall_failed model=%s: %s", model, exc)
        return LLMResult(ok=False, error=type(exc).__name__, latency_ms=_now_ms() - started)
    try:
        return _interpret(body, model, _now_ms() - started)
    except (KeyError, IndexError, TypeError) as exc:
        logger.warning("llm_bad_shape model=%s: %s", model, exc)
        return LLMResult(ok=False, error="bad_shape", latency_ms=_now_ms() - started)


async def aclose() -> None:
    """Test va graceful shutdown uchun."""
    for client in list(_async_clients.values()):
        if not client.is_closed:
            await client.aclose()
    _async_clients.clear()


def _now_ms() -> int:
    import time

    return int(time.monotonic() * 1000)
