#!/usr/bin/env python
"""Gemini Live API diagnostikasi — Faza 0.

Rejadagi 4 ta noaniqlikni haqiqiy API bilan tekshiradi, taxminlarga tayanmaydi:

  1. `enableAffectiveDialog` qaysi modelda qabul qilinadi?
  2. Sessiya o'rtasida matn yuborish: `clientContent` va `realtimeInput.text` —
     qaysi biri qaysi modelda ishlaydi? (Google hujjati 3.1 uchun `clientContent`
     ni faqat boshlang'ich kontekst uchun deb yozgan — hozirgi `gemini.py`
     `send_text()` aynan shuni ishlatadi.)
  3. `[DIRECTOR|...]` xizmat xabari ovoz chiqarib o'qib yuborilmaydimi?
  4. `contextWindowCompression` yoqilganda `usageMetadata` qanday o'sadi —
     kontekst har navbatda qayta hisoblanadimi (kumulyativ yoki navbat-bo'yicha)?

Ishga tushirish (Django kerak emas, faqat `websockets`):

    export GEMINI_API_KEY=...            # yoki .env dan o'qiladi
    python scripts/live_spike.py
    python scripts/live_spike.py --model gemini-3.1-flash-live-preview

Audio yuborilmaydi — hammasi matn bilan haydaladi, shuning uchun arzon (~$0.01).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

try:
    import websockets
except ImportError:  # pragma: no cover — diagnostika skripti
    sys.exit("websockets kerak: pip install websockets")

HOST = "generativelanguage.googleapis.com"
PATH = "/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"

DEFAULT_MODELS = [
    "gemini-2.5-flash-native-audio-preview-12-2025",
    "gemini-3.1-flash-live-preview",
]

SPIKE_SYSTEM_PROMPT = (
    "You are a warm English speaking partner. Keep every turn under 12 words.\n"
    "A message starting with [DIRECTOR is a private stage direction from the "
    "producer. NEVER read it aloud and never mention it. Do exactly what it says, "
    "immediately, in the tone it names."
)

RESET = "\033[0m"
BOLD = "\033[1m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"


def log(msg: str = "") -> None:
    print(msg, flush=True)


def ok(msg: str) -> None:
    log(f"  {GREEN}✓{RESET} {msg}")


def bad(msg: str) -> None:
    log(f"  {RED}✗{RESET} {msg}")


def warn(msg: str) -> None:
    log(f"  {YELLOW}!{RESET} {msg}")


def load_api_key() -> str:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if key:
        return key
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("GEMINI_API_KEY="):
                return line.split("=", 1)[1].strip()
    sys.exit("GEMINI_API_KEY topilmadi (env yoki .env)")


def setup_message(model: str, **flags) -> dict:
    """Setup xabari. `flags` orqali bitta-bitta imkoniyat yoqiladi."""
    name = model if model.startswith("models/") else f"models/{model}"
    setup: dict = {
        "model": name,
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "temperature": 0.7,
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Aoede"}}},
        },
        "systemInstruction": {"parts": [{"text": SPIKE_SYSTEM_PROMPT}]},
        "outputAudioTranscription": {},
        "inputAudioTranscription": {},
    }
    if flags.get("affective"):
        setup["enableAffectiveDialog"] = True
    if flags.get("compression"):
        setup["contextWindowCompression"] = {
            "slidingWindow": {},
            "triggerTokens": "8000",
        }
    if flags.get("resumption"):
        setup["sessionResumption"] = {}
    return {"setup": setup}


class Spike:
    """Bitta ulanish: matn yuboradi, transkript va usageMetadata yig'adi."""

    def __init__(self, ws):
        self.ws = ws
        self.out_text: list[str] = []
        self.usages: list[dict] = []
        self.audio_chunks = 0
        self.setup_complete = False
        self.errors: list[str] = []
        self.resumption_handles: list[str] = []

    async def send(self, payload: dict) -> None:
        await self.ws.send(json.dumps(payload))

    async def send_client_content(self, text: str) -> None:
        await self.send(
            {
                "clientContent": {
                    "turns": [{"role": "user", "parts": [{"text": text}]}],
                    "turnComplete": True,
                }
            }
        )

    async def send_realtime_text(self, text: str) -> None:
        await self.send({"realtimeInput": {"text": text}})

    async def collect(self, timeout: float = 12.0) -> str:
        """Bitta navbatni oxirigacha o'qiydi. Qaytaradi: chiqish transkripti."""
        start_len = len(self.out_text)
        try:
            async with asyncio.timeout(timeout):
                async for raw in self.ws:
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8", errors="replace")
                    msg = json.loads(raw)

                    if "setupComplete" in msg:
                        self.setup_complete = True
                        return ""
                    if msg.get("error"):
                        self.errors.append(json.dumps(msg["error"])[:300])
                        return ""

                    sc = msg.get("serverContent") or {}
                    for part in (sc.get("modelTurn") or {}).get("parts", []):
                        inline = part.get("inlineData") or {}
                        if str(inline.get("mimeType", "")).startswith("audio/"):
                            self.audio_chunks += 1
                    ot = sc.get("outputTranscription") or {}
                    if ot.get("text"):
                        self.out_text.append(ot["text"])

                    if msg.get("usageMetadata"):
                        self.usages.append(msg["usageMetadata"])
                    if msg.get("sessionResumptionUpdate", {}).get("newHandle"):
                        self.resumption_handles.append(
                            msg["sessionResumptionUpdate"]["newHandle"]
                        )
                    if sc.get("turnComplete"):
                        return "".join(self.out_text[start_len:]).strip()
        except (TimeoutError, asyncio.TimeoutError):
            return "".join(self.out_text[start_len:]).strip() + "  <TIMEOUT>"
        except websockets.ConnectionClosed as exc:
            self.errors.append(f"closed code={exc.code} reason={exc.reason}"[:300])
        return "".join(self.out_text[start_len:]).strip()


async def open_session(key: str, model: str, **flags):
    url = f"wss://{HOST}{PATH}?key={key}"
    ws = await asyncio.wait_for(websockets.connect(url, max_size=None, ping_interval=20), 20)
    spike = Spike(ws)
    await spike.send(setup_message(model, **flags))
    await spike.collect(timeout=20)
    return ws, spike


# --- testlar ---------------------------------------------------------------


async def test_setup_flags(key: str, model: str) -> dict:
    """1-savol: qaysi setup bayroqlari qabul qilinadi?"""
    log(f"\n{BOLD}[1] Setup bayroqlari{RESET}")
    results = {}
    for label, flags in (
        ("bazaviy", {}),
        ("enableAffectiveDialog", {"affective": True}),
        ("contextWindowCompression", {"compression": True}),
        ("sessionResumption", {"resumption": True}),
        ("hammasi birga", {"affective": True, "compression": True, "resumption": True}),
    ):
        try:
            ws, spike = await open_session(key, model, **flags)
            accepted = spike.setup_complete and not spike.errors
            results[label] = accepted
            (ok if accepted else bad)(
                f"{label}: {'qabul qilindi' if accepted else spike.errors or 'setupComplete kelmadi'}"
            )
            await ws.close()
        except Exception as exc:  # noqa: BLE001 — diagnostika
            results[label] = False
            bad(f"{label}: {type(exc).__name__}: {str(exc)[:160]}")
    return results


async def test_midsession_text(key: str, model: str) -> dict:
    """2-savol: sessiya o'rtasida matn qaysi kanal orqali o'tadi?"""
    log(f"\n{BOLD}[2] Sessiya o'rtasida matn yuborish{RESET}")
    results = {}

    for label, sender in (
        ("clientContent", "client"),
        ("realtimeInput.text", "realtime"),
    ):
        try:
            ws, spike = await open_session(key, model, compression=True)
            # 1-navbat: har doim clientContent (boshlang'ich kontekst — ruxsat etilgan).
            await spike.send_client_content("Say exactly: Hello there.")
            first = await spike.collect()
            # 2-navbat: tekshirilayotgan kanal.
            probe = "Say exactly: Banana pancakes."
            if sender == "client":
                await spike.send_client_content(probe)
            else:
                await spike.send_realtime_text(probe)
            second = await spike.collect()

            worked = "banana" in second.lower()
            results[label] = worked
            (ok if worked else bad)(f"{label}: 2-navbat javobi = {second!r}")
            if not worked:
                warn(f"    (1-navbat ishlagan edi: {first!r}; xatolar: {spike.errors})")
            await ws.close()
        except Exception as exc:  # noqa: BLE001
            results[label] = False
            bad(f"{label}: {type(exc).__name__}: {str(exc)[:160]}")
    return results


async def test_director_leak(key: str, model: str, channel: str) -> dict:
    """3-savol: [DIRECTOR] xizmat matni ovozga chiqib ketadimi?"""
    log(f"\n{BOLD}[3] [DIRECTOR] sizib chiqishi (kanal: {channel}){RESET}")
    try:
        ws, spike = await open_session(key, model, compression=True)
        await spike.send_client_content("Greet the learner in one short sentence.")
        await spike.collect()

        directive = (
            '[DIRECTOR|tone=excited] Say exactly, with excitement: '
            '"Brilliant! Now tell me about your weekend."'
        )
        if channel == "realtime":
            await spike.send_realtime_text(directive)
        else:
            await spike.send_client_content(directive)
        said = await spike.collect()
        await ws.close()

        lowered = said.lower()
        leaked = "director" in lowered or "tone=" in lowered or "say exactly" in lowered
        followed = "brilliant" in lowered and "weekend" in lowered

        (bad if leaked else ok)(f"sizib chiqish: {'HA — kontrakt ishlamadi' if leaked else 'yo`q'}")
        (ok if followed else bad)(f"direktivga amal qilish: {'ha' if followed else 'yo`q'}")
        log(f"    aytilgani: {said!r}")
        return {"leaked": leaked, "followed": followed, "said": said}
    except Exception as exc:  # noqa: BLE001
        bad(f"{type(exc).__name__}: {str(exc)[:160]}")
        return {"leaked": None, "followed": None, "said": ""}


async def test_usage_growth(key: str, model: str) -> dict:
    """4-savol: usageMetadata kumulyativmi yoki navbat-bo'yichami?"""
    log(f"\n{BOLD}[4] usageMetadata o'sishi (kontekst qayta hisoblanadimi?){RESET}")
    try:
        ws, spike = await open_session(key, model, compression=True)
        for i in range(4):
            await spike.send_client_content(
                f"Ask me short question number {i + 1} about daily life."
            )
            await spike.collect()
        await ws.close()

        if not spike.usages:
            warn("usageMetadata umuman kelmadi")
            return {"snapshots": []}

        log(f"    {len(spike.usages)} ta snapshot:")
        totals = []
        for i, u in enumerate(spike.usages):
            total = u.get("totalTokenCount") or u.get("total_token_count") or 0
            prompt = u.get("promptTokenCount") or u.get("prompt_token_count") or 0
            totals.append(total)
            details = u.get("responseTokensDetails") or u.get("response_tokens_details") or []
            log(f"      #{i + 1} total={total} prompt={prompt} response_details={details}")

        cumulative = all(b >= a for a, b in zip(totals, totals[1:]))
        if cumulative:
            ok("KUMULYATIV (monoton o'sadi) → cost.merge_usage() max bilan to'g'ri ishlaydi")
        else:
            warn("NAVBAT-BO'YICHA (kamayadi) → cost.merge_usage() ni yig'indiga o'zgartirish kerak")

        # Prompt tokenining o'sish tezligi kontekst qayta hisoblanishini ko'rsatadi.
        prompts = [u.get("promptTokenCount") or 0 for u in spike.usages]
        log(f"    promptTokenCount ketma-ketligi: {prompts}")
        log("    → keskin o'sib borsa, kontekst har navbatda qayta to'lanadi.")
        return {"cumulative": cumulative, "totals": totals, "prompts": prompts}
    except Exception as exc:  # noqa: BLE001
        bad(f"{type(exc).__name__}: {str(exc)[:160]}")
        return {}


async def run_for_model(key: str, model: str) -> dict:
    log(f"\n{BOLD}{'=' * 72}{RESET}")
    log(f"{BOLD}MODEL: {model}{RESET}")
    log(f"{BOLD}{'=' * 72}{RESET}")

    flags = await test_setup_flags(key, model)
    midsession = await test_midsession_text(key, model)
    channel = "realtime" if midsession.get("realtimeInput.text") else "client"
    director = await test_director_leak(key, model, channel)
    usage = await test_usage_growth(key, model)

    return {
        "model": model,
        "setup_flags": flags,
        "midsession": midsession,
        "directive_channel": channel,
        "director": director,
        "usage": usage,
    }


def print_verdict(results: list[dict]) -> None:
    log(f"\n{BOLD}{'=' * 72}{RESET}")
    log(f"{BOLD}XULOSA — reja uchun qarorlar{RESET}")
    log(f"{BOLD}{'=' * 72}{RESET}")
    for r in results:
        log(f"\n{BOLD}{r['model']}{RESET}")
        log(f"  affective dialog : {r['setup_flags'].get('enableAffectiveDialog')}")
        log(f"  sliding window   : {r['setup_flags'].get('contextWindowCompression')}")
        log(f"  session resume   : {r['setup_flags'].get('sessionResumption')}")
        log(f"  matn kanali      : {r['directive_channel']}  "
            f"(clientContent={r['midsession'].get('clientContent')}, "
            f"realtimeInput={r['midsession'].get('realtimeInput.text')})")
        log(f"  DIRECTOR sizishi : {r['director'].get('leaked')}")
        log(f"  usage kumulyativ : {r['usage'].get('cumulative')}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Gemini Live diagnostikasi")
    parser.add_argument("--model", action="append", help="Tekshiriladigan model (bir nechta bo'lishi mumkin)")
    parser.add_argument("--json", metavar="FAYL", help="Natijani JSON qilib saqlash")
    args = parser.parse_args()

    key = load_api_key()
    models = args.model or DEFAULT_MODELS

    results = []
    for model in models:
        results.append(await run_for_model(key, model))

    print_verdict(results)

    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2, ensure_ascii=False), "utf-8")
        log(f"\nSaqlandi: {args.json}")


if __name__ == "__main__":
    asyncio.run(main())
