"""Gemini Live API klienti (§5.1).

Server-side proxy: API key hech qachon clientga bermaydi. Barcha protokol
xabar shakllari SHU faylda to'plangan — API versiyasi o'zgarsa faqat shu yer
tahrirlanadi.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
from collections.abc import AsyncIterator
from typing import Any

import websockets
from django.conf import settings

logger = logging.getLogger(__name__)

ENDPOINT_PATH = "/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"


class GeminiError(Exception):
    pass


# Direktiv ovozga chiqib ketganda transkriptda qoladigan izlar. Kontrakt
# `prompts/base.md` da, bu esa uni buzilganda tutadigan to'r.
_LEAK_MARKERS = (
    "[director",
    "word for word",
    "then stop and wait",
    "guidance:",
    "say exactly:",
    "do not give the answer",
)


def strip_director_leak(text: str) -> tuple[str, bool]:
    """Sahna ko'rsatmasi o'quvchi transkriptiga tushib qolgan bo'lsa — kesadi.

    Model kontraktni buzib direktivni ovoz chiqarib o'qisa, uni ortga qaytarib
    bo'lmaydi. Lekin ekranga chiqmasligi va logda ko'rinishi kerak: bu prompt
    regressiyasining yagona o'lchanadigan signali.

    Direktivdan KEYINGI gaplar saqlanadi — model odatda ko'rsatmani o'qib,
    keyin uni bajaradi ("... word for word. Okay. Where are you from?").
    """
    if "[DIRECTOR" not in text:
        return text.strip(), False

    # Gap chegarasi tirnoq bilan yopilishi mumkin: `... 'I am from...' Okay.`
    sentences = re.split(r"(?<=[.!?][\"'])\s+|(?<=[.!?])\s+", text)
    last_directive = -1
    for i, sentence in enumerate(sentences):
        low = sentence.lower()
        if any(marker in low for marker in _LEAK_MARKERS):
            last_directive = i
    cleaned = " ".join(sentences[last_directive + 1 :]).strip()
    return cleaned, True


def supports_affective_dialog(model: str) -> bool:
    """`enableAffectiveDialog` faqat 2.5 native audio oilasida bor.

    Gemini 3.1 Flash Live uni QO'LLAMAYDI — setup bayrog'i bilan yuborilsa
    ulanish rad etiladi. Emotsiya u yerda direktiv matni orqali beriladi.
    """
    return "native-audio" in (model or "")


def wants_realtime_text(model: str) -> bool:
    """Sessiya o'rtasida matn qaysi kanal orqali yuborilishi kerak.

    Gemini 3.1 da `clientContent` faqat boshlang'ich kontekstni urug'lantirish
    uchun; davom etayotgan suhbatga matn `realtimeInput.text` orqali kiritiladi.
    2.5 da `clientContent` butun sessiya davomida ishlaydi.
    """
    return (model or "").startswith("gemini-3")


class GeminiLiveClient:
    """Bitta sessiya uchun Gemini Live WS ulanishi."""

    def __init__(
        self,
        system_prompt: str,
        *,
        api_key: str | None = None,
        model: str | None = None,
        voice: str | None = None,
        session_id: str = "",
        resumption_handle: str = "",
    ):
        self.system_prompt = system_prompt
        self.api_key = api_key if api_key is not None else settings.GEMINI_API_KEY
        self.model = (model or settings.GEMINI_LIVE_MODEL).removeprefix("models/")
        self.voice = voice or settings.GEMINI_VOICE
        self.session_id = session_id
        # §5.3 — reconnectda kontekstni qaytadan yuklamaslik uchun.
        self.resumption_handle = resumption_handle
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._setup_done = asyncio.Event()

    # --- ulanish ---------------------------------------------------------
    @property
    def url(self) -> str:
        return f"wss://{settings.GEMINI_LIVE_HOST}{ENDPOINT_PATH}?key={self.api_key}"

    def _setup_message(self) -> dict[str, Any]:
        setup: dict[str, Any] = {
            "model": f"models/{self.model}",
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "temperature": 0.7,
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": self.voice}}},
            },
            "systemInstruction": {"parts": [{"text": self.system_prompt}]},
            # Tool YO'Q (§Faza 3). Ilgari model har javobdan keyin
            # `evaluate_answer` ni chaqirardi: bu har javobga qo'shimcha
            # generatsiya sikli edi — qimmat, sekin va sifatsiz baholash.
            # Endi baholash `coach.py` da, arzon matn modelida.
            # Ikkala tomonning transkripti — post-session pipeline manbai.
            "inputAudioTranscription": {},
            "outputAudioTranscription": {},
            # Navbat yakunini SERVER emas, backend hal qiladi (§5.1a).
            #
            # Avtomatik VAD bilan model o'quvchi jim bo'lishi bilan javob berib
            # yuborardi — ya'ni coach xatoni topgunicha u allaqachon gapirib
            # bo'lgan bo'lardi va tuzatish keyingi, alohida navbat bo'lib
            # chiqardi ("oldin gapirib, keyin xato qilding deyish"). Endi
            # `activityEnd` ni backend yuboradi: avval nima aytilgani va qaysi
            # xato borligi aniqlanadi, keyin model BITTA javob beradi.
            "realtimeInputConfig": {
                "automaticActivityDetection": {"disabled": True},
                # Barge-in saqlanadi: o'quvchi gapira boshlashi modelni bo'ladi.
                "activityHandling": "START_OF_ACTIVITY_INTERRUPTS",
            },
            # Sirg'aluvchi oyna: kontekst cheksiz o'smaydi, ya'ni uzun sessiyada
            # har navbat qimmatlashib bormaydi. Yon foyda — 15 daqiqalik
            # sessiya cheklovi ham olib tashlanadi (premium tarif uchun kerak).
            "contextWindowCompression": {
                "slidingWindow": {},
                "triggerTokens": str(settings.GEMINI_COMPRESSION_TRIGGER_TOKENS),
            },
            # Uzilishdan keyin suhbatni tokensiz davom ettirish.
            "sessionResumption": (
                {"handle": self.resumption_handle} if self.resumption_handle else {}
            ),
        }
        if settings.GEMINI_AFFECTIVE_DIALOG and supports_affective_dialog(self.model):
            # Model o'quvchining ohangiga moslashib javob beradi (§Faza 6).
            setup["enableAffectiveDialog"] = True
        return {"setup": setup}

    async def connect(self, timeout: float = 15.0) -> None:
        if not self.api_key:
            raise GeminiError("GEMINI_API_KEY o'rnatilmagan")
        self._ws = await asyncio.wait_for(
            websockets.connect(self.url, max_size=None, ping_interval=20),
            timeout=timeout,
        )
        await self._send(self._setup_message())
        logger.info("gemini_connected session_id=%s model=%s", self.session_id, self.model)

    async def close(self) -> None:
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001 — yopilishda xato muhim emas
                pass
            self._ws = None

    @property
    def connected(self) -> bool:
        return self._ws is not None and self._ws.state.name == "OPEN"

    async def _send(self, message: dict) -> None:
        if self._ws is None:
            raise GeminiError("Gemini WS ulanmagan")
        await self._ws.send(json.dumps(message))

    # --- yuborish --------------------------------------------------------
    async def send_audio_chunk(self, b64_pcm: str) -> None:
        """16 kHz 16-bit mono PCM chunk (base64).

        `realtimeInput.mediaChunks` eskirgan — server uni 1007 bilan rad etadi.
        Hozirgi API bitta `audio` blob'ini kutadi (BidiGenerateContentRealtimeInput).
        """
        await self._send(
            {
                "realtimeInput": {
                    "audio": {
                        "mimeType": f"audio/pcm;rate={settings.GEMINI_INPUT_SAMPLE_RATE}",
                        "data": b64_pcm,
                    }
                }
            }
        )

    async def send_audio_stream_end(self) -> None:
        await self._send({"realtimeInput": {"audioStreamEnd": True}})

    # --- qo'lda navbat boshqaruvi (§5.1a) --------------------------------
    async def send_activity_start(self) -> None:
        """O'quvchi gapira boshladi. Modelni bo'ladi (barge-in)."""
        await self._send({"realtimeInput": {"activityStart": {}}})

    async def send_activity_end(self) -> None:
        """Navbat tugadi — model endi javob berishi mumkin.

        Bu backend baholashni tugatgach yuboriladi, shuning uchun modelning
        javobi tuzatishni ham o'z ichiga oladi.
        """
        await self._send({"realtimeInput": {"activityEnd": {}}})

    async def send_text(self, text: str, *, role: str = "user", turn_complete: bool = True) -> None:
        """Modelga matnli ko'rsatma (sessiya boshlash, yakunlash signali).

        `turn_complete=False` — matn kontekstga qo'shiladi, lekin javob
        BOSHLANMAYDI. Ochiq navbat ichida aynan shu kerak: javobni `activityEnd`
        ochadi (§send_directive).
        """
        await self._send(
            {
                "clientContent": {
                    "turns": [{"role": role, "parts": [{"text": text}]}],
                    "turnComplete": turn_complete,
                }
            }
        )

    async def send_realtime_text(self, text: str) -> None:
        """Sessiya o'rtasida matn (Gemini 3.x kanali)."""
        await self._send({"realtimeInput": {"text": text}})

    async def send_directive(
        self, instruction: str, *, tone: str = "", in_turn: bool = True
    ) -> None:
        """Backenddan modelga sahna ko'rsatmasi — ovoz chiqarib o'qilmaydi.

        Kontrakt system promptda o'rnatiladi: `[DIRECTOR` bilan boshlangan xabar
        maxfiy ko'rsatma, uni takrorlash mumkin emas, faqat bajariladi.

        `in_turn` — GENERATSIYANI KIM OCHADI degan savolga javob, va bu yerda
        aynan shu narsa noto'g'ri bo'lsa model ikki marta gapiradi.

        `True` — o'quvchining navbati ochiq (`activityStart` yuborilgan, hali
        `activityEnd` yo'q). Javobni o'sha `activityEnd` ochadi, shuning uchun
        ko'rsatma javob BOSHLAMASLIGI kerak: ikkalasi ham boshlasa server
        bitta navbatga ikkita generatsiya ochadi va o'quvchi ikkita matnni bir
        vaqtda oladi.

        `False` — ochiq navbat yo'q (podkaska, jimlik turtkisi, navbatga
        qo'yilgan ko'rsatma). Bu yerda `activityEnd` umuman kelmaydi, ya'ni
        ko'rsatmaning o'zi javobni ochishi SHART. Aks holda u kontekstda osilib
        qoladi va keyingi navbatning javobiga qo'shilib chiqadi — o'sha payt
        model ikkita ishni bitta javobda bajarib yuboradi.
        """
        header = f"[DIRECTOR|tone={tone}]" if tone else "[DIRECTOR]"
        message = f"{header} {instruction}"
        if in_turn and wants_realtime_text(self.model):
            await self.send_realtime_text(message)
        else:
            await self.send_text(message, turn_complete=not in_turn)

    # --- qabul qilish ----------------------------------------------------
    async def events(self) -> AsyncIterator[dict]:
        """Gemini xabarlarini normallashtirilgan eventlarga aylantiradi."""
        if self._ws is None:
            raise GeminiError("Gemini WS ulanmagan")
        async for raw in self._ws:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("gemini_bad_json session_id=%s", self.session_id)
                continue
            for event in self._normalize(msg):
                yield event

    def _normalize(self, msg: dict) -> list[dict]:
        events: list[dict] = []

        if "setupComplete" in msg:
            self._setup_done.set()
            events.append({"type": "setup_complete"})

        server_content = msg.get("serverContent")
        if server_content:
            if server_content.get("interrupted"):
                events.append({"type": "interrupted"})

            model_turn = server_content.get("modelTurn") or {}
            for part in model_turn.get("parts", []):
                inline = part.get("inlineData")
                if inline and str(inline.get("mimeType", "")).startswith("audio/"):
                    events.append(
                        {
                            "type": "audio",
                            "data": inline.get("data", ""),
                            "mime": inline.get("mimeType"),
                        }
                    )
                elif part.get("text"):
                    events.append({"type": "model_text", "text": part["text"]})

            it = server_content.get("inputTranscription")
            if it and it.get("text"):
                events.append({"type": "input_transcript", "text": it["text"]})

            ot = server_content.get("outputTranscription")
            if ot and ot.get("text"):
                events.append({"type": "output_transcript", "text": ot["text"]})

            if server_content.get("generationComplete"):
                events.append({"type": "generation_complete"})
            if server_content.get("turnComplete"):
                events.append({"type": "turn_complete"})

        tool_call = msg.get("toolCall")
        if tool_call:
            calls = []
            for fc in tool_call.get("functionCalls", []):
                calls.append(
                    {
                        "id": fc.get("id", ""),
                        "name": fc.get("name", ""),
                        "args": fc.get("args", {}) or {},
                    }
                )
            if calls:
                events.append({"type": "tool_call", "calls": calls})

        if msg.get("toolCallCancellation"):
            events.append(
                {"type": "tool_call_cancelled", "ids": msg["toolCallCancellation"].get("ids", [])}
            )

        usage = msg.get("usageMetadata")
        if usage:
            events.append({"type": "usage", "data": usage})

        resumption = msg.get("sessionResumptionUpdate")
        if resumption and resumption.get("newHandle"):
            self.resumption_handle = resumption["newHandle"]
            events.append({"type": "resumption_handle", "handle": resumption["newHandle"]})

        if msg.get("goAway"):
            events.append({"type": "go_away", "data": msg["goAway"]})

        return events

    async def wait_for_setup(self, timeout: float = 15.0) -> None:
        await asyncio.wait_for(self._setup_done.wait(), timeout=timeout)


def decode_audio(b64: str) -> bytes:
    return base64.b64decode(b64)
