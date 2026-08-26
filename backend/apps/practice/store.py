"""Sessiya holati va transkript buferi — Redis (§4.4, §4.6).

Holat WS consumer tomonidan async, Celery tomonidan sync o'qiladi, shuning uchun
ikkala interfeys ham beriladi.
"""

from __future__ import annotations

import json
from typing import Any

import redis
import redis.asyncio as aioredis
from django.conf import settings

from .state import SessionState

_sync_pool: redis.Redis | None = None


def _key(session_id: str, suffix: str) -> str:
    return f"sess:{session_id}:{suffix}"


def sync_client() -> redis.Redis:
    global _sync_pool
    if _sync_pool is None:
        _sync_pool = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _sync_pool


def async_client() -> aioredis.Redis:
    # Har consumer o'z ulanishini oladi; consumer yopilishida yopiladi.
    return aioredis.from_url(settings.REDIS_URL, decode_responses=True)


TTL = None  # settings dan o'qiladi (test override qulayligi uchun funksiyada)


def _ttl() -> int:
    return settings.SESSION_STATE_TTL_SECONDS


# --- Async interfeys (WS consumer) ----------------------------------------


class AsyncSessionStore:
    def __init__(self, session_id: str, client: aioredis.Redis | None = None):
        self.session_id = str(session_id)
        self._client = client or async_client()
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def save_state(self, state: SessionState) -> None:
        await self._client.set(
            _key(self.session_id, "state"), json.dumps(state.to_dict()), ex=_ttl()
        )

    async def load_state(self) -> SessionState | None:
        raw = await self._client.get(_key(self.session_id, "state"))
        if not raw:
            return None
        return SessionState.from_dict(json.loads(raw))

    async def append_turn(self, turn: dict[str, Any]) -> None:
        await self._client.rpush(_key(self.session_id, "turns"), json.dumps(turn))
        await self._client.expire(_key(self.session_id, "turns"), _ttl())

    async def get_turns(self) -> list[dict]:
        raw = await self._client.lrange(_key(self.session_id, "turns"), 0, -1)
        return [json.loads(r) for r in raw]

    async def update_turn(self, idx: int, **fields) -> None:
        """Yozilgan navbatga maydon qo'shadi — masalan kechikib kelgan tarjima.

        Ro'yxat qisqa (bir sessiyada o'nlab navbat), shuning uchun to'liq o'qib
        `lset` qilish yetarli va indeks hisoblashdan ko'ra ishonchli.
        """
        key = _key(self.session_id, "turns")
        raw = await self._client.lrange(key, 0, -1)
        for position, item in enumerate(raw):
            turn = json.loads(item)
            if int(turn.get("idx") or 0) != int(idx):
                continue
            turn.update(fields)
            await self._client.lset(key, position, json.dumps(turn))
            return

    async def append_evaluation(self, item: dict[str, Any]) -> None:
        await self._client.rpush(_key(self.session_id, "evals"), json.dumps(item))
        await self._client.expire(_key(self.session_id, "evals"), _ttl())

    async def append_coach(self, item: dict[str, Any]) -> None:
        """Coach natijalari — sessiyadan keyingi tahlilning asosiy manbai.

        Xatolar real vaqtda, matn modeli tomonidan topilgani uchun yakuniy
        tahlil ularni xom transkriptdan qaytadan qidirmaydi.
        """
        await self._client.rpush(_key(self.session_id, "coach"), json.dumps(item))
        await self._client.expire(_key(self.session_id, "coach"), _ttl())

    async def append_llm_call(self, usage: dict[str, Any], *, kind: str = "coach") -> None:
        """Narx hisobi uchun: har matn LLM chaqiruvining token sarfi.

        `kind` byudjet uchun: tarjima chaqiruvlari coach tomiga kirmasligi
        kerak, aks holda uzun sessiyada tuzatishlar tarjima tufayli o'chib
        qolardi. Narx hisobiga esa ikkalasi ham tushadi.
        """
        if not usage:
            return
        await self._client.rpush(_key(self.session_id, "llm"), json.dumps({**usage, "kind": kind}))
        await self._client.expire(_key(self.session_id, "llm"), _ttl())

    async def count_llm_calls(self, kind: str = "coach") -> int:
        key = _key(self.session_id, "llm")
        if not kind:
            return int(await self._client.llen(key))
        raw = await self._client.lrange(key, 0, -1)
        # Eski yozuvlarda `kind` yo'q — ular coach chaqiruvlari edi.
        return sum(1 for item in raw if (json.loads(item).get("kind") or "coach") == kind)

    async def set_meta(self, **fields) -> None:
        if not fields:
            return
        await self._client.hset(
            _key(self.session_id, "meta"),
            mapping={k: json.dumps(v) for k, v in fields.items()},
        )
        await self._client.expire(_key(self.session_id, "meta"), _ttl())

    async def get_meta(self) -> dict:
        raw = await self._client.hgetall(_key(self.session_id, "meta"))
        return {k: json.loads(v) for k, v in raw.items()}

    async def mark_connected(self, connected: bool) -> None:
        """Reconnect grace oynasi uchun (§5.3)."""
        key = _key(self.session_id, "disconnected_at")
        if connected:
            await self._client.delete(key)
        else:
            await self._client.set(key, "1", ex=settings.SESSION_RESUME_GRACE_SECONDS)

    async def acquire_lock(self) -> bool:
        """Bitta sessiyaga bitta aktiv consumer."""
        return bool(await self._client.set(_key(self.session_id, "lock"), "1", nx=True, ex=_ttl()))

    async def release_lock(self) -> None:
        await self._client.delete(_key(self.session_id, "lock"))


# --- Sync interfeys (Celery / REST) ---------------------------------------


class SyncSessionStore:
    def __init__(self, session_id: str):
        self.session_id = str(session_id)
        self._client = sync_client()

    def load_state(self) -> SessionState | None:
        raw = self._client.get(_key(self.session_id, "state"))
        if not raw:
            return None
        return SessionState.from_dict(json.loads(raw))

    def get_turns(self) -> list[dict]:
        raw = self._client.lrange(_key(self.session_id, "turns"), 0, -1)
        return [json.loads(r) for r in raw]

    def get_evaluations(self) -> list[dict]:
        raw = self._client.lrange(_key(self.session_id, "evals"), 0, -1)
        return [json.loads(r) for r in raw]

    def get_coach(self) -> list[dict]:
        raw = self._client.lrange(_key(self.session_id, "coach"), 0, -1)
        return [json.loads(r) for r in raw]

    def get_llm_calls(self) -> list[dict]:
        raw = self._client.lrange(_key(self.session_id, "llm"), 0, -1)
        return [json.loads(r) for r in raw]

    def get_meta(self) -> dict:
        raw = self._client.hgetall(_key(self.session_id, "meta"))
        return {k: json.loads(v) for k, v in raw.items()}

    def has_active_consumer(self) -> bool:
        """Sessiyaga hozir ulangan consumer bormi (grace tekshiruvi uchun)."""
        return bool(self._client.exists(_key(self.session_id, "lock")))

    def purge(self) -> None:
        keys = [
            _key(self.session_id, s)
            for s in ("state", "turns", "evals", "coach", "llm", "meta", "lock", "disconnected_at")
        ]
        self._client.delete(*keys)
