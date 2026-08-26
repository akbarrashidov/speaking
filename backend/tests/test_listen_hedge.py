"""Kechikish "dumi" (§listen._post_hedged).

Tarmoq yo'li beqaror: bir xil so'rov 0.7 s dan 3.1 s gacha ketadi. O'quvchi shu
vaqt jim kutadi, shuning uchun sekin so'rov ikkinchisi bilan quviladi.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from apps.practice import listen


class FakeResponse:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self._body


@pytest.fixture
def hedge(monkeypatch, settings):
    settings.GEMINI_API_KEY = "test-key"
    settings.LISTEN_HEDGE_AFTER_SECONDS = 0.05
    settings.LISTEN_TIMEOUT_SECONDS = 5
    return settings


@pytest.mark.asyncio
async def test_a_fast_answer_never_costs_a_second_call(hedge, monkeypatch):
    calls = []

    class Client:
        async def post(self, url, **kwargs):
            calls.append(1)
            return FakeResponse({"ok": len(calls)})

    monkeypatch.setattr(listen, "_client", lambda: Client())
    assert await listen._post_hedged({}) == {"ok": 1}
    assert len(calls) == 1, "tez javobga qo'shimcha so'rov yuborildi"


@pytest.mark.asyncio
async def test_a_slow_first_call_is_overtaken_by_the_second(hedge, monkeypatch):
    calls = []

    class Client:
        async def post(self, url, **kwargs):
            calls.append(1)
            # Birinchisi cho'ziladi, ikkinchisi darhol qaytadi.
            await asyncio.sleep(2 if len(calls) == 1 else 0)
            return FakeResponse({"which": len(calls)})

    monkeypatch.setattr(listen, "_client", lambda: Client())
    body = await asyncio.wait_for(listen._post_hedged({}), timeout=1)
    assert body == {"which": 2}
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_the_second_call_saves_a_failed_first_one(hedge, monkeypatch):
    calls = []

    class Client:
        async def post(self, url, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                await asyncio.sleep(0.1)
                raise httpx.ConnectError("tarmoq uzildi")
            return FakeResponse({"which": 2})

    monkeypatch.setattr(listen, "_client", lambda: Client())
    assert await listen._post_hedged({}) == {"which": 2}


@pytest.mark.asyncio
async def test_hedging_can_be_switched_off(hedge, monkeypatch):
    hedge.LISTEN_HEDGE_AFTER_SECONDS = 0
    calls = []

    class Client:
        async def post(self, url, **kwargs):
            calls.append(1)
            await asyncio.sleep(0.2)
            return FakeResponse({"which": len(calls)})

    monkeypatch.setattr(listen, "_client", lambda: Client())
    assert await listen._post_hedged({}) == {"which": 1}
    assert len(calls) == 1
