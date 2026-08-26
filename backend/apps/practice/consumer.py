"""Sessiya WebSocket consumer'i (§5.1, §7.2).

Mini App ⇄ Django Channels ⇄ Gemini Live. Har aktiv sessiyaga bitta consumer;
u Gemini ulanishiga, Redis'dagi holatga, tool call ishloviga va ikki tomonlama
audio relay'ga egalik qiladi.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.conf import settings
from django.utils import timezone

from apps.content import validators
from apps.content.models import FREE_FLOW_MODES, SessionMode
from apps.users.jwt_utils import TokenError, get_user_from_token

from . import adaptive, asr, coach, cost, hints, listen, shadow, translate
from . import state as sm
from .gemini import GeminiError, GeminiLiveClient, strip_director_leak
from .models import EndReason, Session, SessionStatus, Speaker
from .store import AsyncSessionStore

logger = logging.getLogger(__name__)

# Yakunlovchi gap aytilishi uchun beriladigan vaqt (testlarda 0 ga tushiriladi).
CLOSING_GRACE_SECONDS = 3.5

# `speech_end` kelgach navbat SHUNCHA kutib yopiladi (testlarda 0).
#
# Client VAD jimlikdan keyin `speech_end` yuboradi, A1 o'quvchi esa gap
# O'RTASIDA to'xtab qolishi mumkin. Bu oyna bo'lmasa bitta gap ikkita navbatga
# bo'linadi: birinchi bo'lagi baholanib model javob bera boshlaydi, ikkinchi
# bo'lagining tuzatishi esa model gapirayotganda tayyor bo'ladi va keyingi
# navbatga suriladi — "avval savol, keyin xato" aynan shundan tug'iladi.
#
# Qiymat client VAD'i bilan birga o'lchanadi (`useSession.js: VAD_SILENCE_MS`):
# ikkalasi ham javobdan oldingi sof jimlik, ya'ni yig'indisi ~0.9 s dan
# oshmasligi kerak.
# Live-first yo'lida (§_close_turn_live_first) bu oyna SOF KECHIKISH: navbat
# yopilishi bilan model gapira boshlaydi, ya'ni har 100 ms bevosita seziladi.
# Shu bilan birga u gap o'rtasidagi pauzani ushlab turadigan yagona narsa —
# busiz bitta gap ikkita navbatga bo'linadi.
#
# 0.5 s — o'rtasi: klient VAD'i (0.3 s) bilan birga pauzaga chidam 0.8 s,
# javobgacha esa jimlik 0.8 s + Live'ning o'z kechikishi. Ilgari bu yerda
# 0.75 s turardi, chunki oyna coach chaqiruvining ostida bepul o'tardi;
# baholash kritik yo'ldan chiqqach o'sha hisob yaroqsiz bo'ldi.
TURN_END_GRACE_SECONDS = 0.5

# Shundan qisqa nutq bo'lagi — tugallangan javob emas, gap o'rtasidagi pauza.
# Unga qo'shimcha kutish beriladi: tez javob uzun, tugallangan gaplarga.
#
# Chegara past: aynan SHU qiymat oldindan baholash boshlanadigan chegara ham.
# 1.6 s da "Yes, I do" kabi tugallangan qisqa javoblar oldindan baholanmasdan
# qolardi — ular oynani ham, chaqiruvni ham KETMA-KET to'lardi, ya'ni eng tez
# javoblar eng sekin qaytardi.
SHORT_UTTERANCE_SECONDS = 0.9
SHORT_UTTERANCE_EXTRA_GRACE = 0.35

# Shundan kam so'zli javob — gap qurishga urinish emas, qisqa ijtimoiy javob.
MIN_SENTENCE_WORDS = 3

# Ketma-ket shuncha javobda target struktura ishlatilmasa — drill rejimida ham
# dinamik, strukturani majburlaydigan savol qo'shiladi (§Faza 5).
STRUCTURE_MISS_LIMIT = 2

# Erkin suhbat: backend savol bermaydi va tuzatishni Live'ga yubormaydi —
# oqimni model o'zi boshqaradi, tuzatishlar esa ekranga chiqadi.
# Oqimni Live o'zi boshqaradigan rejimlar: erkin suhbat, shadowing, rol suhbat.
# Bularda backend savol yozib bermaydi va state machine navbatga aralashmaydi.
FREE_FLOW = FREE_FLOW_MODES

# Shadowing navbati "o'tdi" deb hisoblanadigan ball. Past emas: mashqning
# mazmuni AYNAN o'sha gapni aytish, "tushunarli aytish" emas.
SHADOW_PASS_SCORE = 75

# Baholash UMUMAN bo'lmagan holatlar (`coach.fallback` sabablari). Bularda
# deterministik "qayta ayting" tarmog'i ham ishlatilmaydi: byudjet tugagan yoki
# kalit yo'q bo'lsa, u har navbatda takrorlanib sessiyani buzib yuborardi.
GRADING_NOT_RUN = ("no_question", "budget", "nothing_heard", "no_api_key")

# Baholash ishlamagan navbatda Live transkriptiga ishonish uchun kerakli
# minimal so'z soni. Bir-ikki so'z — odatda shovqinning "matni".
MIN_TRUSTED_WORDS = 3

# Zaxira baholash yo'li (ASR + coach) shuncha soniyasiz boshlanmaydi.
FALLBACK_MIN_BUDGET = 2.5

CLOSE_UNAUTHORIZED = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_NOT_FOUND = 4404
CLOSE_CONFLICT = 4409
CLOSE_SERVER_ERROR = 4500


class SessionConsumer(AsyncWebsocketConsumer):
    # --- hayot sikli -----------------------------------------------------
    async def connect(self):
        self.session_id = self.scope["url_route"]["kwargs"]["session_id"]
        self.log_ctx = {"session_id": self.session_id}
        self.store = AsyncSessionStore(self.session_id)
        self.gemini: GeminiLiveClient | None = None
        self.state: sm.SessionState | None = None
        self.meta: dict = {}
        self._reader_task: asyncio.Task | None = None
        self._deadline_task: asyncio.Task | None = None
        self._closing = False
        self._t0 = time.monotonic()
        self._started_wall = None
        self._turn_idx = 0
        self._resumed_transcript: list[dict] = []
        self._ai_buffer: list[str] = []
        # Joriy AI navbatida direktiv ovozga chiqib ketdimi (§gemini.strip_director_leak).
        self._ai_leaked = False
        self._learner_buffer: list[str] = []
        # Navbat allaqachon yopilganmi — `speech_end` va model gapirishi
        # ikkalasi ham yopishga urinadi, ikki marta yopilmasin.
        self._turn_handled = False
        # Joriy o'quvchi navbatining xom audiosi (16 kHz PCM16) — so'zma-so'z
        # transkript uchun (§asr.py). Live transkripti xatolarni tuzatib
        # yuboradi, shuning uchun grammatika baholashi unga tayanolmaydi.
        self._learner_audio: list[bytes] = []
        self._learner_audio_bytes = 0
        # Shadowing: klient hozir qaysi klipni o'ynatgani va o'sha navbatning
        # yozuvi. Baholash aynan shu gapga nisbatan bo'ladi (§shadow.py).
        self._shadow_idx = 0
        self._shadow_reference_ms = 0
        self._last_turn_audio = b""
        self._ai_turn_started_ms: int | None = None
        self._ai_turn_ended_ms: int | None = None
        self._learner_turn_started_ms: int | None = None
        self._learner_last_ms: int | None = None
        self._gemini_retry_used = False
        self._pending_question_id: int | None = None
        self._usage: dict = {}
        self._audio_open = False
        # Live'da ochiq turgan `activity` oynasi. Qo'lda navbat boshqaruvida
        # `activityStart` ikki marta yuborilmasligi kerak (§_start_activity).
        self._activity_open = False
        # `speech_end` dan keyin navbatni yopadigan kechiktirilgan vazifa.
        self._close_task: asyncio.Task | None = None
        # Oyna kutilayotganda boshlangan baholash: (audio uzunligi, vazifa).
        self._speculative: tuple[int, asyncio.Task] | None = None
        # Live-first: matni hali yo'q, joyi band qilingan navbat va unga
        # Gemini transkriptidan yig'ilgan matn (§_fill_reserved_turn).
        self._reserved_turn_idx = 0
        self._reserved_text = ""
        self._resumption_handle = ""
        self._coach_tasks: set[asyncio.Task] = set()
        # AI gaplarining o'zbekcha tarjimasi — fon vazifalari (§translate.py).
        self._translate_tasks: set[asyncio.Task] = set()
        self._silence_task: asyncio.Task | None = None
        # Model gapirib turganda yuborib bo'lmaydigan ko'rsatmalar navbati
        # (§_flush_pending_directive).
        self._pending_directives: list[tuple[str, str]] = []

        token = self._token_from_query()
        if not token:
            await self.close(code=CLOSE_UNAUTHORIZED)
            return
        try:
            self.user = await database_sync_to_async(get_user_from_token)(token)
        except TokenError:
            await self.close(code=CLOSE_UNAUTHORIZED)
            return

        self.session = await self._load_session()
        if self.session is None:
            await self.close(code=CLOSE_NOT_FOUND)
            return
        if self.session.user_id != self.user.id:
            await self.close(code=CLOSE_FORBIDDEN)
            return
        if self.session.status != SessionStatus.ACTIVE:
            await self.close(code=CLOSE_CONFLICT)
            return

        if not await self.store.acquire_lock():
            # Bir sessiyaga ikkinchi ulanish — eskisi hali tirik.
            await self.close(code=CLOSE_CONFLICT)
            return

        self.state = await self.store.load_state()
        self.meta = await self.store.get_meta()
        # Reconnect'dan keyin sarf noldan boshlanmasin.
        self._usage = self.meta.get("usage") or {}
        self._resumption_handle = self.meta.get("resumption_handle") or ""
        if self.state is None or not self.meta.get("system_prompt"):
            logger.error("session_state_missing %s", self.log_ctx)
            await self.store.release_lock()
            await self.close(code=CLOSE_NOT_FOUND)
            return

        await self.accept()
        await self.store.mark_connected(True)

        # Gemini ulanishidan OLDIN o'qiladi: reader task darrov yangi turn
        # qo'shishi mumkin, `_turn_idx` esa shundan keyin to'g'rilansa kech bo'ladi.
        self._resumed_transcript = await self._existing_transcript()

        resuming = self.session.started_at is not None
        if resuming:
            # Reconnect: vaqt limiti nolga qaytmaydi — sessiya boshidan sanaladi.
            self._started_wall = self.session.started_at
        else:
            self._started_wall = await self._mark_started()

        try:
            await self._connect_gemini(resuming=resuming)
        except (TimeoutError, GeminiError, OSError) as exc:
            logger.exception("gemini_connect_failed %s: %s", self.log_ctx, exc)
            await self.send_json({"type": "error", "code": "gemini_unavailable"})
            await self._teardown(EndReason.ERROR)
            return

        self._deadline_task = asyncio.create_task(self._deadline_watchdog())
        await self.send_json(
            {
                "type": "session_ready",
                "mode": self.state.mode,
                "time_limit_s": self.session.time_limit_seconds,
                "elapsed_s": int(self._elapsed_ms() / 1000),
                "questions_total": len(self.state.question_ids),
                "resumed": resuming,
                # Yo'nalish muhiti: klient shu ma'lumot bilan video pleyerni
                # yoki sahna fonini quradi (§frontend Session).
                "track": self.meta.get("track", ""),
                "scene": {
                    "persona": self.meta.get("persona", ""),
                    "setting": self.meta.get("setting", ""),
                    "ambience": self.meta.get("ambience", ""),
                },
                "media_src": self.meta.get("media_src", ""),
                "media_kind": self.meta.get("media_kind", ""),
                "media_ref": self.meta.get("media_ref", ""),
                "shadow_lines": self.meta.get("shadow_lines") or [],
                # Uzilishdan keyin suhbat oynasi bo'sh qolmasin.
                "transcript": self._resumed_transcript,
            }
        )

    async def _existing_transcript(self) -> list[dict]:
        turns = await self.store.get_turns()
        self._turn_idx = max((int(t.get("idx") or 0) for t in turns), default=0)
        return [
            {
                "idx": t.get("idx", 0),
                "speaker": t.get("speaker", ""),
                "text": t.get("text", ""),
                # Uzilishdan keyin tarjimalar ham qaytadi — qayta so'ralmaydi.
                "text_uz": t.get("text_uz", ""),
            }
            for t in turns
            if (t.get("text") or "").strip()
        ]

    async def disconnect(self, code):
        if self._closing:
            return
        self._closing = True
        logger.info("ws_disconnect %s code=%s", self.log_ctx, code)
        await self._cancel_tasks()
        if self.gemini:
            await self.gemini.close()
        if self.state is not None:
            await self.store.save_state(self.state)
        await self.store.mark_connected(False)
        await self.store.release_lock()
        # §5.3 — 60 soniyalik reconnect oynasi, keyin avtomatik yakunlash.
        if self.state is not None and not self.state.is_ended:
            await self._schedule_grace_finalize()
        await self.store.close()

    # --- clientdan kelgan xabarlar ---------------------------------------
    async def receive(self, text_data=None, bytes_data=None):
        if bytes_data:
            # Xom binar audio ham qo'llab-quvvatlanadi (base64'siz, tezroq).
            await self._forward_audio_bytes(bytes_data)
            return
        if not text_data:
            return
        try:
            msg = json.loads(text_data)
        except json.JSONDecodeError:
            return

        mtype = msg.get("type")
        if mtype == "audio_chunk":
            await self._forward_audio_b64(msg.get("data") or "")
        elif mtype == "speech_start":
            # Client VAD signali — javob kechikishini aniq o'lchash uchun.
            # Podkaska taymerini ham darhol to'xtatadi: o'quvchi gapira boshladi.
            self._disarm_silence_watchdog()
            # Ikki holat, va ular ARALASHMASLIGI kerak.
            #
            # a) Oyna hali ochiq (`_close_task` bor) — bu o'sha gapning davomi.
            #    Yopish ham, oldindan boshlangan baholash ham bekor qilinadi,
            #    audio o'sha navbatga to'planishda davom etadi.
            #
            # b) Navbat allaqachon yopilgan (baholash ketyapti yoki tugagan) —
            #    bu YANGI navbat. Ilgari bu yerda ham `_turn_handled` tushirilar,
            #    lekin `_activity_open` True bo'lib qolardi: `activityStart`
            #    yuborilmasdi, ya'ni yangi gap Live'da hech qaysi navbatga
            #    tushmasdi va modelga umuman yetib bormasdi — o'quvchi esa
            #    gapining ikkinchi yarmi "eshitilmadi" deb ko'rardi.
            continuation = self._close_task is not None
            self._cancel_pending_close()
            if continuation:
                self._cancel_speculative()
            else:
                self._activity_open = False
            self._turn_handled = False
            if self._learner_turn_started_ms is None:
                self._learner_turn_started_ms = self._elapsed_ms()
            await self._start_activity()
        elif mtype == "speech_end":
            self._learner_last_ms = self._elapsed_ms()
            # Navbat SHU YERDA yakunlanadi: avval nima aytilgani va qaysi xato
            # borligi aniqlanadi, keyingina modelga javob berishga ruxsat
            # beriladi (§5.1a). Fon vazifasi — `receive` bloklanmaydi.
            self._schedule_turn_close()
        elif mtype == "speech_cancel":
            # Klient VAD'i yanglishdi (eshik taqilladi, stol turtildi): navbat
            # ochilgan-u, gap bo'lmagan. Bufer tozalanadi, hech narsa
            # baholanmaydi va modelga ham hech narsa yuborilmaydi.
            self._cancel_pending_close()
            self._cancel_speculative()
            self._take_learner_audio()
            self._learner_buffer = []
            self._learner_turn_started_ms = None
            self._turn_handled = False
            logger.info("turn_cancelled_by_client %s", self.log_ctx)
        elif mtype == "shadow_line":
            # Klient klipni o'ynatdi — keyingi navbat shu gapga taqqoslanadi.
            # `reference_ms` — klient O'LCHAGAN eshittirish uzunligi. Video
            # bo'lmasa etalon shu bo'ladi: taxmin emas, haqiqiy uzunlik.
            try:
                self._shadow_idx = max(0, int(msg.get("idx") or 0))
            except (TypeError, ValueError):
                self._shadow_idx = 0
            try:
                self._shadow_reference_ms = max(0, int(msg.get("reference_ms") or 0))
            except (TypeError, ValueError):
                self._shadow_reference_ms = 0
        elif mtype == "end_session":
            await self._graceful_end(EndReason.COMPLETED)
        elif mtype == "ping":
            await self.send_json({"type": "pong", "elapsed_s": int(self._elapsed_ms() / 1000)})

    async def _forward_audio_b64(self, b64: str):
        if not b64 or not self.gemini:
            return
        self._buffer_learner_audio(b64)
        try:
            await self.gemini.send_audio_chunk(b64)
            self._audio_open = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("audio_forward_failed %s: %s", self.log_ctx, exc)
            await self._handle_gemini_drop()

    def _buffer_learner_audio(self, b64: str) -> None:
        """Joriy navbat audiosini yig'adi (§asr.py).

        Client darvozasi tufayli bu yerga faqat o'quvchi gapirgan bo'laklar
        keladi, ya'ni bufer aynan bitta gap bo'lib chiqadi. Chegara qat'iy:
        uzun monologda ham xotira va ASR narxi o'smaydi.
        """
        limit = settings.ASR_MAX_SECONDS * settings.GEMINI_INPUT_SAMPLE_RATE * 2
        if not settings.ASR_ENABLED or self._learner_audio_bytes >= limit:
            return
        try:
            chunk = base64.b64decode(b64)
        except (ValueError, TypeError):
            return
        self._learner_audio.append(chunk)
        self._learner_audio_bytes += len(chunk)

    def _take_learner_audio(self) -> bytes:
        """Yig'ilgan audioni qaytaradi va buferni bo'shatadi."""
        pcm = b"".join(self._learner_audio)
        self._learner_audio = []
        self._learner_audio_bytes = 0
        return pcm

    async def _start_activity(self):
        """Modelga: o'quvchi gapira boshladi (barge-in ham shu orqali).

        Oyna allaqachon ochiq bo'lsa qayta yuborilmaydi: gap o'rtasidagi
        pauzadan keyingi davomi — yangi navbat emas, o'sha navbatning davomi.
        """
        if not self.gemini or self._activity_open:
            return
        self._activity_open = True
        try:
            await self.gemini.send_activity_start()
        except Exception as exc:  # noqa: BLE001
            logger.warning("activity_start_failed %s: %s", self.log_ctx, exc)

    async def _end_audio_activity(self):
        """Nutq segmenti tugadi — model endi javob berishi mumkin.

        Faqat segment davomida haqiqatan audio yuborilgan bo'lsa yuboriladi,
        aks holda server bo'sh navbatga javob berishga urinadi.
        """
        if not self._audio_open or not self.gemini:
            return
        self._audio_open = False
        self._activity_open = False
        try:
            await self.gemini.send_activity_end()
        except Exception as exc:  # noqa: BLE001
            logger.warning("audio_stream_end_failed %s: %s", self.log_ctx, exc)

    async def _forward_audio_bytes(self, raw: bytes):
        await self._forward_audio_b64(base64.b64encode(raw).decode())

    # --- Gemini ----------------------------------------------------------
    async def _connect_gemini(self, *, resuming: bool):
        self.gemini = GeminiLiveClient(
            self.meta["system_prompt"],
            session_id=self.session_id,
            resumption_handle=self._resumption_handle,
            # Rol suhbatda har qahramonning o'z ovozi bor — ofitsiant va
            # shifokor bir xil ovozda gapirsa, muhit yo'qoladi.
            voice=self.meta.get("voice") or None,
        )
        # Narx hisobi qaysi model ishlaganini bilishi kerak (§Faza 0).
        await self.store.set_meta(live_model=self.gemini.model)
        await self.gemini.connect()
        self._reader_task = asyncio.create_task(self._read_gemini())
        await self.gemini.wait_for_setup()

        if not resuming:
            await self._send_first_question()
        elif not self._resumption_handle:
            # Handle yo'q — kontekst yo'qolgan, savolni qaytadan aytamiz.
            await self._send_resume_instruction()
        else:
            # Kontekst tiklandi: model suhbatni eslaydi, faqat qisqa turtki yetarli.
            await self.gemini.send_directive(
                "The learner just reconnected. Welcome them back in one short "
                "sentence, then continue exactly where you left off.",
                tone="warm",
            )

    async def _read_gemini(self):
        try:
            async for event in self.gemini.events():
                await self._handle_gemini_event(event)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("gemini_stream_error %s: %s", self.log_ctx, exc)
            await self._handle_gemini_drop()

    async def _handle_gemini_event(self, event: dict):
        etype = event["type"]

        if etype == "audio":
            # Model gapira boshladi — demak o'quvchining navbati tugagan.
            await self._close_learner_turn()
            if self._ai_turn_started_ms is None:
                self._ai_turn_started_ms = self._elapsed_ms()
                await self.send_json({"type": "state", "value": "ai_speaking"})
            await self.send_json({"type": "ai_audio", "data": event["data"]})

        elif etype == "interrupted":
            # Barge-in — clientdagi playback darhol to'xtatiladi (§5.1).
            await self.send_json({"type": "ai_audio_interrupt"})
            await self._flush_ai_turn()

        elif etype == "output_transcript":
            await self._close_learner_turn()
            self._ai_buffer.append(event["text"])
            # Direktiv ovozga chiqib ketsa, u ekranga ham oqib o'tmasin: bo'lak
            # bo'laklab kelgani uchun bu yerda faqat to'xtatamiz, toza matn
            # navbat yakunida (`_flush_ai_turn`) bir marta yuboriladi.
            if "[DIRECTOR" in "".join(self._ai_buffer):
                self._ai_leaked = True
                return
            await self._send_transcript(Speaker.AI, event["text"], final=False)

        elif etype == "input_transcript":
            if self._turn_handled:
                # Gemini 3.1 Live kirish transkriptini navbat YAKUNIDA yuboradi.
                #
                # Eski (hold) yo'lda bu o'sha gapning kechikkan nusxasi edi:
                # baholash tugab, gap allaqachon ekranga chiqqan bo'lardi. Qabul
                # qilinsa ekranda ikkinchi marta chiqadi va yangi navbat ochib,
                # ikkinchi marta baholanadi. Yangi navbatni faqat `speech_start`
                # ochadi.
                #
                # Live-first yo'lida esa aksincha: navbat baholashni kutmasdan
                # yopilgani uchun gap ekranda HALI YO'Q — faqat joyi band
                # qilingan. Ya'ni bu matn kechikkan nusxa emas, ekranga
                # chiqadigan yagona narsa. U yangi navbat ham ochmaydi va
                # baholanmaydi: shunchaki o'sha bo'sh qatorni to'ldiradi.
                await self._fill_reserved_turn(event["text"])
                return
            self._disarm_silence_watchdog()
            now = self._elapsed_ms()
            if self._learner_turn_started_ms is None:
                self._learner_turn_started_ms = now
            self._learner_last_ms = now
            self._learner_buffer.append(event["text"])
            await self._send_transcript(Speaker.LEARNER, event["text"], final=False)

        elif etype in ("turn_complete", "generation_complete"):
            if etype == "turn_complete":
                await self._flush_ai_turn()
                await self._flush_pending_directive()
                await self.send_json({"type": "state", "value": "listening"})
                # Model gapirib bo'ldi — endi navbat o'quvchida. Jim qolsa
                # podkaska zinapoyasi ishga tushadi (§Faza 4).
                self._arm_silence_watchdog()

        elif etype == "tool_call":
            # Tool'lar e'lon qilinmagan (§Faza 3) — bu kelmasligi kerak.
            logger.warning("unexpected_tool_call %s calls=%s", self.log_ctx, event["calls"])

        elif etype == "resumption_handle":
            # §5.3 — uzilishdan keyin kontekstni qaytadan yuklamaslik uchun.
            self._resumption_handle = event["handle"]
            await self.store.set_meta(resumption_handle=event["handle"])

        elif etype == "usage":
            # Snapshotlar birlashtiriladi — oxirgisi bilan almashtirilmaydi
            # (`cost.merge_usage` kumulyativ hisobni to'g'ri qamrab oladi).
            self._usage = cost.merge_usage(self._usage, event["data"])
            await self.store.set_meta(usage=self._usage)

        elif etype == "go_away":
            logger.info("gemini_go_away %s", self.log_ctx)
            await self._handle_gemini_drop()

    async def _handle_gemini_drop(self):
        """§5.3 — bir marta jimgina reconnect, aks holda xushmuomala yakun."""
        if self._closing:
            return
        if self._gemini_retry_used:
            await self.send_json({"type": "error", "code": "gemini_lost"})
            await self._teardown(EndReason.ERROR)
            return
        self._gemini_retry_used = True
        logger.info("gemini_reconnecting %s", self.log_ctx)
        if self._reader_task:
            self._reader_task.cancel()
        if self.gemini:
            await self.gemini.close()
        try:
            await self._connect_gemini(resuming=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("gemini_reconnect_failed %s: %s", self.log_ctx, exc)
            await self.send_json({"type": "error", "code": "gemini_lost"})
            await self._teardown(EndReason.ERROR)

    # --- state machine ----------------------------------------------------
    async def _send_first_question(self):
        decision = sm.start_question(self.state)
        await self.store.save_state(self.state)
        if decision.action == sm.Action.END_SESSION:
            await self._graceful_end(EndReason.COMPLETED)
            return
        if self.state.mode in FREE_FLOW:
            # Savollar allaqachon system promptda GOALS ro'yxati bo'lib turibdi —
            # bittalab berilmaydi. Modelga faqat boshlash signali kerak.
            self._pending_question_id = decision.payload["question_id"]
            await self.gemini.send_text("SESSION_START. Follow your FLOW instruction.")
            return

        q = await self._question_payload(decision.payload["question_id"])
        self._pending_question_id = q["question_id"]
        # Sessiya boshi — boshlang'ich kontekst, shuning uchun `clientContent`
        # (Gemini 3.x da ham bu ruxsat etilgan yagona `clientContent` ishlatilishi).
        await self.gemini.send_text(
            "SESSION_START. Greet the learner in one short sentence, then ask "
            f'this question word for word: "{q["question_text"]}". Then stop and wait.'
            + (f" Guidance: {q['elicitation_note']}" if q["elicitation_note"] else "")
        )

    async def _send_resume_instruction(self):
        qid = self.state.current_question_id
        if qid is None:
            await self._send_first_question()
            return

        if self.state.mode in FREE_FLOW:
            # Bank savolini so'zma-so'z aytish bu rejimning butun ma'nosini
            # buzadi — model suhbatni o'zi tiklaydi, GOALS hamon promptda.
            await self.gemini.send_text(
                "The connection dropped and the learner is back. Say one short "
                "sentence to welcome them back, then continue the conversation "
                "with your next goal."
            )
            return

        q = await self._question_payload(qid)
        self._pending_question_id = qid
        await self.gemini.send_text(
            "The connection dropped and the learner is back. Say one short "
            "sentence to welcome them back, then ask this question again word "
            f'for word: "{q["question_text"]}". Then stop and wait.'
        )

    # --- navbat yakuni (§5.1a) -------------------------------------------
    async def _close_learner_turn(self):
        """Zaxira yo'l: model o'zicha gapira boshladi, navbat esa yopilmagan.

        Odatiy oqimda navbatni `speech_end` yopadi. Bu yerga faqat model
        kutilmaganda gapirib qolgan holatda kelinadi (masalan turtki
        direktividan keyin). Bu gap ham baholanadi — busiz u transkriptda
        qolib, tuzatishsiz va statistikasiz o'tib ketardi, ya'ni sessiya
        yakunidagi tahlil ham uni ko'rmasdi.

        Ikki narsa qat'iy. Birinchisi — baholash FON vazifasi: bu yerni
        `_read_gemini` chaqiradi, u bloklansa AI ovozi o'quvchiga yetib
        bormaydi. Ikkinchisi — ovozga aralashilmaydi: model allaqachon
        gapiryapti, tuzatish esa faqat o'sha payt ma'noli, shuning uchun u
        faqat ekranga chiqadi (§_deliver_directive).
        """
        if self._turn_handled or not self._learner_buffer:
            return
        self._turn_handled = True
        self._cancel_pending_close()
        audio = self._take_learner_audio()
        live_text = "".join(self._learner_buffer).strip()
        # Oynani model yopdi. Bayroq tushmasa keyingi barge-in yangi
        # `activityStart` yubora olmaydi (§_start_activity).
        self._activity_open = False
        # `_audio_open` ham tushadi: navbatni server O'ZI yopdi, ya'ni endi
        # `activityEnd` yuborilmasligi kerak. Qolib ketsa u KEYINGI navbatning
        # yakunida uzatilardi — ikkita navbat bitta oynaga qo'shilib, model
        # bir generatsiyada ikkita javob aytib yuborardi.
        self._audio_open = False
        turn_idx = await self._flush_learner_turn()
        task = asyncio.create_task(self._grade_silently(audio, live_text, turn_idx))
        self._coach_tasks.add(task)

    async def _grade_silently(self, audio: bytes, live_text: str, turn_idx: int):
        """Model gapirayotgan navbat baholanadi: ekran va statistika, ovoz yo'q.

        Hech kim kutmaydi — model shu payt gapirib turibdi, o'quvchi esa uni
        eshityapti. Yiqilsa sessiya davom etadi: bu navbat shunchaki
        baholanmagan bo'lib qoladi.
        """
        try:
            result, _heard = await self._hear_and_judge(
                audio, live_text, quiet=True, exclude_idx=turn_idx
            )
            if not live_text or not result.ok:
                return
            await self._steer_after_evaluation(live_text, turn_idx, result, silent=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — baholash sessiyani yiqitmaydi
            logger.exception("late_turn_grading_failed %s: %s", self.log_ctx, exc)
        finally:
            self._coach_tasks.discard(asyncio.current_task())

    def _schedule_turn_close(self):
        """`speech_end` — navbatni darhol emas, qisqa oynadan keyin yopadi.

        Oyna ichida `speech_start` kelsa yopish bekor qilinadi va gapning
        davomi o'sha navbatga qo'shiladi: audio buferi ham, transkript buferi
        ham to'planishda davom etadi.

        Baholash esa SHU YERDA, oynani kutmasdan boshlanadi — quyiga qarang.
        """
        self._cancel_pending_close()
        self._start_speculative_grading()
        self._close_task = asyncio.create_task(self._close_turn_after_grace())
        self._coach_tasks.add(self._close_task)

    def _cancel_pending_close(self):
        """Faqat oyna ichida ishlaydi: baholash boshlangach bekor qilinmaydi."""
        if self._close_task and not self._close_task.done():
            self._close_task.cancel()
            self._coach_tasks.discard(self._close_task)
        self._close_task = None

    # --- baholashni oldindan boshlash -------------------------------------
    #
    # Navbat yopilishini kutish oynasi (grace) va tarmoq kutishi ilgari
    # KETMA-KET turardi: 0.35-0.85 s jimlik, keyin ~1.9 s chaqiruv. Ikkalasi
    # ham sof kutish, ya'ni ularni ustma-ust qo'yish mumkin — audio `speech_end`
    # paytida allaqachon to'liq, oyna esa faqat "davomi bormi?" degan savolga
    # javob kutadi. Shuning uchun chaqiruv o'sha zahoti yuboriladi.
    #
    # O'quvchi gapida davom etsa, audio o'zgaradi va bu natija yaroqsiz bo'ladi
    # — o'shanda u bekor qilinadi va oyna yakunida yangisi so'raladi. Sifat
    # o'zgarmaydi: bir xil audio, bir xil model, bir xil prompt.

    def _start_speculative_grading(self):
        self._cancel_speculative()
        if self._closing or self.state is None:
            return
        audio = b"".join(self._learner_audio)
        # Qisqa bo'lakda davomi kelishi ehtimoli katta, ya'ni bu chaqiruv
        # katta ehtimol bilan tashlanadi. Sessiyaning chaqiruv byudjeti
        # cheklangan (`COACH_MAX_CALLS`) — uni behuda yeyish oxirida
        # baholashning butunlay o'chishiga olib keladi. Shuning uchun oldindan
        # faqat tugallangandek ko'rinadigan javob baholanadi.
        if not audio or self._learner_audio_seconds() < SHORT_UTTERANCE_SECONDS:
            return
        live_text = "".join(self._learner_buffer).strip()
        task = asyncio.create_task(self._hear_and_judge(audio, live_text, quiet=True))
        self._coach_tasks.add(task)
        self._speculative = (len(audio), task)

    def _cancel_speculative(self):
        """O'quvchi gapida davom etdi — boshlangan baholash yaroqsiz."""
        if self._speculative:
            _, task = self._speculative
            if not task.done():
                task.cancel()
            self._coach_tasks.discard(task)
        self._speculative = None

    async def _graded(
        self, audio: bytes, live_text: str, *, quiet: bool = False, exclude_idx: int = 0
    ):
        """Oldindan boshlangan natijani oladi yoki yangisini so'raydi.

        `quiet` — hech kim kutmayapti (model allaqachon gapiryapti), ya'ni
        ekranda "tekshirilmoqda" ko'rsatilmaydi.
        """
        spec, self._speculative = self._speculative, None
        if spec and spec[0] == len(audio):
            # Audio o'zgarmagan — o'sha chaqiruv aynan shu navbatniki.
            if not quiet:
                await self.send_json({"type": "state", "value": "evaluating"})
            self._coach_tasks.discard(spec[1])
            return await spec[1]
        if spec and not spec[1].done():
            spec[1].cancel()
            self._coach_tasks.discard(spec[1])
        return await self._hear_and_judge(audio, live_text, quiet=quiet, exclude_idx=exclude_idx)

    async def _close_turn_after_grace(self):
        await asyncio.sleep(TURN_END_GRACE_SECONDS)
        # Qisqa bo'lak — gap tugagani emas, o'rtasida o'ylanib qolgani. Uzun
        # javob darhol yopiladi (tez javob), qisqa bo'lak esa davomini kutadi:
        # busiz bitta gap "bedroom bedroom" / "dining room and" bo'lib bir
        # nechta navbatga bo'linadi va har bo'lagi alohida baholanadi.
        # Nol — audio buferi o'chirilgan yoki bo'sh, ya'ni uzunlik haqida
        # ma'lumot yo'q. Bunday holatda kutish bejiz kechikish bo'lardi.
        seconds = self._learner_audio_seconds()
        if 0 < seconds < SHORT_UTTERANCE_SECONDS:
            await asyncio.sleep(SHORT_UTTERANCE_EXTRA_GRACE)
        # Shu nuqtadan keyin navbat yopilgan hisoblanadi — endi bekor qilinmaydi.
        self._close_task = None
        await self._close_turn(self._take_learner_audio())

    def _learner_audio_seconds(self) -> float:
        """Joriy navbatda yig'ilgan nutq uzunligi (16 kHz PCM16)."""
        return self._learner_audio_bytes / (settings.GEMINI_INPUT_SAMPLE_RATE * 2)

    async def _close_turn(self, audio: bytes):
        """`speech_end` → baholash → ko'rsatma → modelga navbat ochiladi.

        Tartib shu yerda hal bo'ladi. Ilgari model o'quvchi jim bo'lishi bilan
        javob berardi, coach esa 2–4 s keyin tugab, tuzatish ALOHIDA navbat
        bo'lib chiqardi — "avval gapirib, keyin xato qilding deyish". Endi
        baholash oldinda: model bitta javobda ham tuzatadi, ham davom etadi.

        Baholash yiqilsa yoki cho'zilsa navbat baribir ochiladi — jim qolgan
        suhbat noto'g'ri tuzatishdan ham yomonroq.
        """
        if self._turn_handled:
            return
        self._turn_handled = True
        if self._live_first():
            await self._close_turn_live_first(audio)
            return
        try:
            await asyncio.wait_for(
                self._evaluate_and_steer(audio), timeout=settings.TURN_HOLD_MAX_SECONDS
            )
        except TimeoutError:
            logger.warning("turn_hold_timeout %s", self.log_ctx)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — baholash sessiyani yiqitmaydi
            logger.exception("turn_pipeline_failed %s: %s", self.log_ctx, exc)
        finally:
            self._coach_tasks.discard(asyncio.current_task())
            await self._end_audio_activity()

    def _live_first(self) -> bool:
        """Model baholashni kutmaydimi (§prompts/self_correction.md).

        Erkin suhbatda — kutmaydi. Xatoni model o'z qulog'i bilan topadi va
        o'sha zahoti aytadi; coach esa fonda ishlab, tuzatishni EKRANGA
        chiqaradi. Skript rejimlarida aksincha: keyingi savolni backend
        yozadi, ya'ni ko'rsatmasiz model gapira olmaydi.
        """
        return (
            settings.LIVE_FIRST_ENABLED
            and self.state is not None
            and self.state.mode in FREE_FLOW
            and self.state.mode != SessionMode.SHADOWING
        )

    async def _close_turn_live_first(self, audio: bytes):
        """O'quvchi jim bo'ldi → model DARHOL javob beradi, baholash fonda.

        Tartib bu yerda hamma narsa. `activityEnd` birinchi ketadi: shundan
        keyingi har bir amal — Redis yozuvi, ekranga xabar, coach chaqiruvi —
        modelning javobiga PARALLEL ketadi, ya'ni o'quvchi uchun kutish yo'q.

        Ilgari aksincha edi: navbat coach chaqiruvi (~2 s) tugamaguncha
        yopilmasdi. Sifat yaxshi edi-yu, suhbat jonli emasdi — o'quvchi har
        gapidan keyin jimlikni eshitardi.

        Ekranga chiqadigan tuzatish shundan yo'qolmaydi: u shu navbat raqamiga
        bog'lanib, coach javob bergach yetib boradi (§_send_correction).
        """
        self._last_turn_audio = audio
        await self._end_audio_activity()
        # Gemini 3.1 kirish transkriptini navbat YAKUNIDA yuboradi, ya'ni bu
        # yerda `live_text` ko'pincha bo'sh bo'ladi va gap ekranga so'zma-so'z
        # matn kelgach chiqadi. Raqam esa hozir band qilinadi — tartib uchun.
        live_text, started, ended = self._take_learner_turn()
        turn_idx = await self._append_learner_turn(live_text, started, ended, reserve=True)
        self._reserved_turn_idx = turn_idx
        self._reserved_text = live_text
        task = asyncio.create_task(self._grade_in_background(audio, live_text, turn_idx))
        self._coach_tasks.add(task)

    async def _grade_in_background(self, audio: bytes, live_text: str, turn_idx: int):
        """Baholash — hech kim kutmaydi: model shu payt allaqachon gapiryapti.

        Yiqilsa sessiya davom etadi, o'sha navbat shunchaki tuzatishsiz qoladi.
        """
        try:
            result, heard = await self._graded(audio, live_text, quiet=True, exclude_idx=turn_idx)
            # Ekranda hozir Gemini transkripti turgan bo'lishi mumkin — taqqoslash
            # ham, zaxira matn ham o'shanga nisbatan bo'ladi (§_fill_reserved_turn).
            shown = self._reserved_text if turn_idx == self._reserved_turn_idx else live_text
            if turn_idx == self._reserved_turn_idx:
                self._reserved_turn_idx = 0
                self._reserved_text = ""
            text = self._trusted_text(heard, shown, dropped=result.error in GRADING_NOT_RUN)
            if text != shown:
                await self._replace_learner_text(turn_idx, text)
            if not text or result.error in GRADING_NOT_RUN:
                return
            await self._steer_after_evaluation(text, turn_idx, result, silent=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — baholash sessiyani yiqitmaydi
            logger.exception("background_grading_failed %s: %s", self.log_ctx, exc)
        finally:
            self._coach_tasks.discard(asyncio.current_task())

    async def _fill_reserved_turn(self, text: str):
        """Gemini transkriptini band qilingan qatorga oqizadi.

        Nega umuman kerak. So'zma-so'z matn (`listen`/`asr`) 1.5-2.5 s da
        keladi, ya'ni o'sha vaqt o'quvchi o'z gapini ekranda ko'rmay turardi.
        Gemini transkripti esa navbat yakunida deyarli darhol keladi.

        Nega u YETARLI EMAS. Live transkripti xatolarni jimgina tuzatib
        beradi: "I from Uzbekistan" ekranga "I'm from Uzbekistan" bo'lib
        chiqadi. Tuzatish diffi aynan AYTILGAN so'zga qo'yiladi, shuning uchun
        so'zma-so'z matn kelgach qator yana almashtiriladi (§_trusted_text).
        Ya'ni bu — vaqtinchalik ko'rinish, yakuniy haqiqat emas.

        Bo'laklab keladi, shuning uchun har bo'lakda matn o'sib boradi.
        """
        if not self._reserved_turn_idx or not (text or "").strip():
            return
        self._reserved_text = (self._reserved_text + text).strip()
        await self._replace_learner_text(self._reserved_turn_idx, self._reserved_text)

    async def _replace_learner_text(self, turn_idx: int, text: str):
        """Ekrandagi gapni so'zma-so'z matn bilan almashtiradi.

        Live transkripti xatolarni jimgina tuzatib beradi ("I from" → "I'm
        from"), tuzatish diffi esa aynan o'quvchi AYTGAN matnga qo'yiladi —
        ikkisi bir-biriga to'g'ri kelmasa ekranda tuzatiladigan so'z ko'rinmay
        qoladi. Klient bir xil `idx` kelganda qatorni almashtiradi.
        """
        await self.store.update_turn(turn_idx, text=text)
        await self._send_transcript(Speaker.LEARNER, text, final=True, idx=turn_idx)

    async def _evaluate_and_steer(self, audio: bytes):
        # Talaffuz izohi uchun kerak: model o'quvchini ESHITADI (§shadow.py).
        self._last_turn_audio = audio
        live_text = "".join(self._learner_buffer).strip()
        result, heard = await self._graded(audio, live_text)
        text = self._trusted_text(heard, live_text, dropped=result.error in GRADING_NOT_RUN)

        turn_idx = await self._flush_learner_turn(text)
        if not text or result.error in GRADING_NOT_RUN:
            return
        # Coach yiqilsa ham suhbat to'xtamaydi: `coach.fallback` verdikti
        # `unintelligible`, ya'ni deterministik yo'l "qayta ayting" deydi
        # (§4.4). Baholash umuman bo'lmagan holatlar yuqorida chiqib ketdi.
        await self._steer_after_evaluation(text, turn_idx, result)

    def _trusted_text(self, heard: str, live_text: str, *, dropped: bool = False) -> str:
        """So'zma-so'z transkript ustun — Live xatolarni tuzatib beradi.

        Live transkripti tekshiruv sifatida ISHLATILMAYDI. Bu sinab ko'rildi va
        yiqildi: Gemini 3.1 Live `inputTranscription` ni navbat yakunida, ya'ni
        baholash tugagandan KEYIN yuboradi, shuning uchun bu yerda u deyarli
        doim bo'sh. "Live jim bo'lsa, eshitilgan gap to'qima" qoidasi o'sha
        sababdan real gaplarni ham o'chirib yuborardi.
        """
        if heard:
            return heard
        # Baholash umuman ishlamagan bo'lsa (jimlik, byudjet) Live matniga
        # tayanib bo'lmaydi: aynan o'sha holatda u shovqinni "gap" qilib
        # beradi. Uzun matn — boshqa masala: u haqiqiy nutq bo'lishi mumkin.
        if dropped and len(live_text.split()) < MIN_TRUSTED_WORDS:
            return ""
        return live_text

    async def _hear_and_judge(
        self, audio: bytes, live_text: str, *, quiet: bool = False, exclude_idx: int = 0
    ):
        """Audio → (baholash, so'zma-so'z matn). Bitta chaqiruv (§listen.py).

        Yiqilsa eski ikki bosqichli yo'l ishlaydi: `asr.py` + `coach.py`.
        `quiet` — hech kim kutmayapti, ekranda "tekshirilmoqda" ko'rsatilmaydi.
        """
        if self._closing or self.state is None or self.state.current_question_id is None:
            return coach.fallback("no_question"), ""
        # Nutqsiz navbat baholanmaydi — hech qanday model chaqirilmaydi.
        #
        # Ilgari bu yerda teshik bor edi: `asr.transcribe` jimlikni rad etib
        # bo'sh satr qaytarardi, quvur esa Live'ning O'Z transkriptiga
        # qaytardi. Live esa shovqinni ham matnga aylantiradi — natijada
        # o'quvchi umuman gapirmagan bo'lsa ham AI "gapni tuzatib" ketardi.
        if audio and asr.is_silence(audio):
            logger.info("turn_dropped_silence %s bytes=%d", self.log_ctx, len(audio))
            return coach.fallback("nothing_heard"), ""
        if await self.store.count_llm_calls() >= settings.COACH_MAX_CALLS:
            logger.warning("coach_budget_exhausted %s", self.log_ctx)
            return coach.fallback("budget"), ""

        if not quiet:
            await self.send_json({"type": "state", "value": "evaluating"})
        ctx = await self._coach_context("", exclude_idx=exclude_idx)

        started = time.monotonic()
        if audio and settings.LISTEN_ENABLED:
            result, heard = await listen.evaluate(ctx, audio)
            await self.store.append_llm_call(result.usage, kind="listen")
            if result.ok:
                return result, heard

        # Zaxira yo'l ikkita ketma-ket chaqiruv — u faqat vaqt qolgandagina
        # ma'noli. Byudjet tugagach boshlansa, hold timeout'iga urilib navbat
        # BUTUNLAY yo'qolardi: model ham javob bermay, gap ham ekranga
        # chiqmay qolardi. Jim kutgandan ko'ra tuzatishsiz javob yaxshiroq.
        if time.monotonic() - started > settings.TURN_HOLD_MAX_SECONDS - FALLBACK_MIN_BUDGET:
            logger.warning("fallback_skipped_no_budget %s", self.log_ctx)
            return coach.fallback("nothing_heard"), ""

        # Zaxira: alohida transkript, keyin matn coach'i.
        heard = ""
        if audio:
            heard, usage = await asr.transcribe(audio, self.meta.get("target_structure", ""))
            await self.store.append_llm_call(usage, kind="asr")
        if audio and not heard:
            # Ikkala so'zma-so'z yo'l ham yiqildi — baholash Live transkriptida
            # ketadi, u esa xatolarni tuzatib beradi, ya'ni gap "toza" bo'lib
            # ko'rinadi. Bu jimgina yuz bersa platformaning ma'nosi yo'qoladi.
            logger.warning("verbatim_unavailable %s — grading on live transcript", self.log_ctx)
        ctx.learner_utterance = heard or live_text
        if not ctx.learner_utterance:
            return coach.fallback("nothing_heard"), heard
        result = await coach.evaluate(ctx)
        await self.store.append_llm_call(result.usage)
        return result, heard

    async def _steer_after_evaluation(
        self, utterance: str, turn_idx: int, result, *, silent: bool = False
    ):
        """`silent` — model allaqachon gapiryapti: ovoz kanaliga tegilmaydi."""
        if self._closing or self.state is None or self.state.is_ended:
            return
        current_qid = self.state.current_question_id
        if current_qid is None:
            return

        # Shadowingda navbat boshqacha o'lchanadi: gap TUZILMAYDI, aynan o'sha
        # gap takrorlanadi. Shuning uchun verdikt grammatikadan emas, takror
        # bahosidan keladi — progress ham shu mashqning haqiqiy natijasini
        # ko'rsatadi (§shadow.py).
        shadow_result = None
        if self.state.mode == SessionMode.SHADOWING:
            shadow_result = await self._shadow_score(utterance)
            result.verdict = (
                sm.Verdict.CORRECT.value
                if shadow_result.score >= SHADOW_PASS_SCORE
                else sm.Verdict.INCORRECT.value
            )

        attempt_before = self.state.attempt
        decision = sm.evaluate(self.state, current_qid, result.verdict, result.error_type)

        # Erkin suhbatda ovoz kanali BIRINCHI ketadi, yozuv-chizuv keyin.
        #
        # Bu satrlardan keyingi hamma narsa — holatni saqlash, baholashni
        # yozish, registrni moslash — Redis va DB borib-kelishlari. Ularning
        # birontasi ham modelning javobiga ta'sir qilmaydi, lekin ilgari
        # HAMMASI ko'rsatmadan oldin turardi: o'quvchi shuncha vaqt qo'shimcha
        # jim kutardi. Skript rejimlarida tartib o'zgarmaydi — u yerda
        # ko'rsatma `decision` va `pacing` ga bog'liq.
        voice_first = shadow_result is None and self.state.mode in FREE_FLOW
        # Daraja aniqlashda tuzatish EKRANGA ham chiqmaydi. Ovozda yo'qligi
        # promptda aytilgan (§modes/placement.md), lekin o'quvchi diffni
        # ekranda ko'rsa keyingi javobini o'shanga qarab tuzatadi — va o'lchov
        # u nimani bilganini emas, nechta tuzatishni o'qib olganini ko'rsatadi.
        # Baholash o'zi ishlashda davom etadi: xulosa aynan shundan chiqadi.
        show_corrections = self.state.mode != SessionMode.PLACEMENT
        if voice_first:
            if show_corrections:
                await self._send_correction(turn_idx, result)
            if not silent:
                next_question = await self._bridge_question(result)
                await self._deliver_directive(
                    self._turn_instruction(utterance, result, next_question),
                    drop_if_late=True,
                )

        await self.store.save_state(self.state)
        await self._record_evaluation(current_qid, attempt_before, utterance, result)
        pacing = await self._adapt_register()

        logger.info(
            "evaluation %s q=%s verdict=%s attempt=%s coach_ok=%s coach_ms=%d → %s",
            self.log_ctx,
            current_qid,
            result.verdict,
            attempt_before + 1,
            result.ok,
            result.latency_ms,
            decision.action.value,
        )

        if shadow_result is not None:
            # Ekranda — o'lchovlar (so'zlar, sur'at, ball), ovozda — bitta
            # qisqa jumla. Ikkalasi ham o'sha zahoti, mashq davom etayotganda.
            await self.send_json(
                {"type": "shadow_score", "turn_idx": turn_idx, **shadow_result.to_dict()}
            )
            if not silent and shadow_result.note:
                await self._deliver_directive(
                    "Say exactly this sentence and nothing else, then stop and "
                    f'wait: "{shadow_result.note}"',
                    drop_if_late=True,
                )
            return

        if voice_first:
            # Tuzatish ham, ko'rsatma ham yuqorida ketdi (ikki kanal parallel:
            # xatolar ekranga diff bo'lib chiqadi, ovozda esa modelning SHU
            # navbatdagi javobiga qo'shiladi). Bu yerda faqat qolgani.
            #
            # O'quvchi javobida yopilgan maqsadlar — keyingi savol shundan
            # keyin tanlanadi, ya'ni javob berilgan narsa qayta so'ralmaydi.
            await self._apply_covered_goals(result)
            if pacing:
                self._queue_directive(self._pacing_instruction(pacing))
        else:
            # Skript rejimlarida ko'rsatma tushib qolsa sessiya osilib qoladi:
            # model gapirayotganda u navbatga qo'yiladi va navbat yakunida
            # uzatiladi (§_flush_pending_directive).
            await self._apply_decision(decision, result, pacing=pacing, queue=silent)

        await self.send_json(
            {
                "type": "progress",
                # Adaptive rejimda "berilgan savol" tushunchasi yo'q — hozircha
                # qamrov o'lchovi sifatida to'g'ri javoblar soni ishlatiladi.
                "asked": (
                    self.state.correct_total
                    if self.state.mode in FREE_FLOW
                    else self.state.asked_total
                ),
                "total": self.state.max_questions,
                "correct": self.state.correct_total,
            }
        )

        if decision.action == sm.Action.END_SESSION:
            await self._graceful_end(EndReason.COMPLETED, already_instructed=True)

    # --- shadowing (§shadow.py) -------------------------------------------
    def _shadow_reference(self) -> dict:
        """Klient hozir o'ynatgan gap. Signal kelmagan bo'lsa — birinchisi."""
        lines = self.meta.get("shadow_lines") or []
        if not lines:
            return {}
        idx = min(self._shadow_idx, len(lines) - 1)
        return lines[idx]

    async def _shadow_score(self, utterance: str):
        """Takrorni etalon bilan solishtiradi va bitta qisqa xulosa yozadi.

        O'lchov ikki qismdan: so'zlar (matn ustida, tekin) va sur'at (yozuv
        uzunligi / klip uzunligi). Talaffuz esa alohida — modelga o'quvchi
        yozuvi eshittiriladi. Model chaqirilmasa yoki yiqilsa, xulosa o'sha
        o'lchovlardan yoziladi, ya'ni ekran hech qachon bo'sh qolmaydi.
        """
        line = self._shadow_reference()
        reference = (line.get("text") or "").strip()
        audio = self._last_turn_audio
        spoken_ms = int(len(audio) / (settings.GEMINI_INPUT_SAMPLE_RATE * 2) * 1000)

        result = shadow.compare(
            reference,
            utterance,
            spoken_ms=spoken_ms,
            clip_start_ms=line.get("start_ms"),
            clip_end_ms=line.get("end_ms"),
            played_ms=self._shadow_reference_ms,
        )
        result.idx = int(line.get("idx") or 0)

        language = self.meta.get("learner_language", "uz")
        note = ""
        if reference and await self.store.count_llm_calls() < settings.COACH_MAX_CALLS:
            try:
                note, usage = await shadow.pronunciation_note(audio, reference, language)
                if usage:
                    await self.store.append_llm_call(usage, kind="shadow")
            except Exception as exc:  # noqa: BLE001 — izoh mashqni to'xtatmaydi
                logger.warning("shadow_note_failed %s: %s", self.log_ctx, exc)
        result.note = note or shadow.fallback_note(result, language)

        logger.info(
            "shadow %s idx=%s score=%d words=%.2f tempo=%.2f (%s)",
            self.log_ctx,
            result.idx,
            result.score,
            result.word_accuracy,
            result.tempo,
            result.tempo_label,
        )
        return result

    async def _send_correction(self, turn_idx: int, result) -> None:
        """Grammatik tuzatishlar — ovozda emas, ekranda (§adaptive).

        Xato topilmagan bo'lsa ham yuboriladi: client aynan shu navbat tekshirib
        bo'linganini bilishi va "toza" belgisini qo'yishi kerak.
        """
        await self.send_json(
            {
                "type": "correction",
                "turn_idx": turn_idx,
                "errors": result.errors,
                "verdict": result.verdict,
                "fluency": result.fluency,
            }
        )

    # --- podkaska zinapoyasi (§Faza 4) -----------------------------------
    def _arm_silence_watchdog(self):
        """O'quvchi jim qolsa podkaska beradigan taymerni qo'yadi."""
        self._disarm_silence_watchdog()
        if self._closing or self.state is None or self.state.is_ended:
            return
        if self.state.current_question_id is None:
            return
        self._silence_task = asyncio.create_task(self._silence_watchdog())

    def _disarm_silence_watchdog(self):
        if self._silence_task and not self._silence_task.done():
            self._silence_task.cancel()
        self._silence_task = None

    async def _silence_watchdog(self):
        """Har jimlik oralig'ida bitta pog'ona. O'quvchi gapirsa bekor qilinadi."""
        delay = hints.silence_seconds(self.state.register)
        try:
            while not self._closing and not self.state.is_ended:
                await asyncio.sleep(delay)
                if self._closing or self.state.is_ended:
                    return
                if self.state.mode in FREE_FLOW:
                    await self._nudge_quiet_learner()
                else:
                    await self._give_hint(self.state.hint_rung + 1)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — podkaska sessiyani yiqitmaydi
            logger.exception("hint_failed %s: %s", self.log_ctx, exc)

    # --- ko'rsatma navbati -------------------------------------------------
    #
    # Coach model javobining O'RTASIDA tugaydi. O'sha payt yuborilgan ko'rsatma
    # javobni bo'ladi va model ketma-ket ikki marta gapirib yuboradi. Shuning
    # uchun model gapirayotgan bo'lsa ko'rsatma navbatga qo'yiladi va navbat
    # yakunida bittalab uzatiladi; model jim bo'lsa esa darhol ketadi — aks
    # holda uni uyg'otadigan hech narsa qolmaydi va ko'rsatma osilib qoladi.

    def _queue_directive(self, instruction: str, tone: str = "") -> None:
        if instruction:
            self._pending_directives.append((instruction, tone))

    async def _deliver_directive(
        self,
        instruction: str,
        tone: str = "",
        *,
        drop_if_late: bool = False,
        in_turn: bool = True,
    ) -> None:
        if not instruction or self._closing or not self.gemini:
            return
        if self._ai_turn_started_ms is not None:
            if drop_if_late:
                # Tuzatish faqat SHU navbatda ma'noli. Model allaqachon
                # gapiryapti — navbatga qo'ysak, u savoldan KEYIN aytiladi va
                # "gapirib bo'lding, endi xatoyingni aytaman" bo'lib eshitiladi.
                # Ekrandagi tuzatish (§_send_correction) baribir yetib bordi.
                logger.warning("correction_dropped_late %s", self.log_ctx)
                return
            self._queue_directive(instruction, tone)
            return
        await self.gemini.send_directive(instruction, tone=tone, in_turn=in_turn)

    async def _flush_pending_directive(self):
        """Navbat yakunida BITTA ko'rsatma. Qolgani keyingi navbatga qoladi.

        Bittalab: ikkitasi ketma-ket ketsa model ularni bitta navbatga qo'shib
        yuboradi va o'quvchi ikkita ko'rsatmani bir vaqtda eshitadi.
        """
        if not self._pending_directives or self._closing or not self.gemini:
            return
        instruction, tone = self._pending_directives.pop(0)
        # Navbat ichida emas: bu yerda o'quvchining ochiq oynasi yo'q, ya'ni
        # javobni ochadigan `activityEnd` ham kelmaydi. Ko'rsatma o'zi
        # generatsiyani boshlashi shart (§gemini.send_directive).
        await self.gemini.send_directive(instruction, tone=tone, in_turn=False)

    @staticmethod
    def _pacing_instruction(pacing: str) -> str:
        return (
            f"{pacing} This changes how you speak for the rest of the session. "
            "Say nothing now and do not ask another question — you have just "
            "asked one. Stay silent and wait for the learner."
        )

    def _turn_instruction(self, utterance: str, result, next_question: str = "") -> str:
        """Model javob berishdan OLDIN oladigan yagona ko'rsatma (§5.1a).

        Ikki vazifasi bor.

        1. Nima aytilganini qotiradi. Model o'z qulog'iga tayanganda o'quvchi
           "I from Swiss" deganda "Uzbekistan!" deb javob berardi — kontekstdan
           to'qib. Bu yerdagi matn so'zma-so'z transkript, ya'ni haqiqat.

        2. Xato bo'lsa uni SHU javobga qo'shadi. Ilgari tuzatish keyingi,
           alohida navbat bo'lib chiqardi va "avval gapirib, keyin xato
           qilding deyish" bo'lib eshitilardi.

        `model_answer` — gapning BARCHA xatosi tuzatilgan varianti, shuning
        uchun bitta qaytarish hamma xatoni tuzatadi. Farq faqat kuchda:
        darsning shakli buzilsa to'xtaydi va qayta aytishni so'raydi; kichik
        sirpanish bo'lsa javob ichida tuzatib, suhbat davom etadi.

        3. Keyingi savolni qotiradi. `next_question` — coach yozgan va
           tekshiruvdan o'tgan savol: u o'quvchi ALLAQACHON javob bergan
           narsani so'ramaydi va target strukturasiz javob berib bo'lmaydi.
           Model o'zi o'ylab topsa, ikkalasi ham kafolatlanmaydi. Tuzatish
           qayta aytishni talab qilgan navbatda savol qo'shilmaydi: u yerda
           o'quvchi gapirishi kerak, eshitishi emas.
        """
        follow = (
            f' Then ask exactly this, in these words: "{next_question}" Then stop and wait.'
            if next_question
            else ""
        )
        said = (
            f'The learner just said, word for word: "{utterance}". This is what '
            "they actually said — trust it over anything you think you heard."
        )
        correct = result.model_answer or (result.errors[0].get("fix") if result.errors else "")
        if not result.errors or not correct:
            return f"{said} Reply to it in one short sentence.{follow}"

        # Tushuntirish aniq bo'lishi uchun modelga AYNAN qaysi so'z buzilgani
        # beriladi. Busiz u butun gapni qayta aytib, "nimasi xato edi?" degan
        # savolni javobsiz qoldiradi (§correction_policy.md).
        top = result.errors[0]
        span = (top.get("span") or "").strip()
        fix = (top.get("fix") or "").strip()
        point = (
            f' The one thing to fix: they said "{span}" where it should be "{fix}".'
            if span and fix
            else ""
        )

        # To'xtatib qayta aytirish — kuchli vosita, u faqat o'quvchi to'liq gap
        # qurishga urinib, buzganda ma'noli. Qisqa ijtimoiy javob ("Hello",
        # "Yes", "Thanks") darsning shaklini ishlatmaydi, lekin bu xato emas:
        # unga "endi men bilan qaytaring" deyish suhbatni mantiqsiz qiladi.
        attempted_a_sentence = len(utterance.split()) >= MIN_SENTENCE_WORDS
        major = any(e.get("severity") == "high" for e in result.errors) or (
            not result.target_structure_used and attempted_a_sentence
        )
        logger.info(
            "recast %s major=%s streak=%s fix=%r",
            self.log_ctx,
            major,
            self.state.structure_miss_streak,
            correct,
        )

        if major and self.state.structure_miss_streak >= STRUCTURE_MISS_LIMIT:
            # Ketma-ket uchinchi marta — shama yetarli emas, birga aytiladi.
            return (
                f'{said}{point} Say "Let me help." Then tell them in ONE short '
                "sentence which word was wrong or missing. Then say this slowly "
                f'and clearly, stressing the words they got wrong: "{correct}" '
                'Then say "Say it with me." and say it once more, slowly. Then '
                "stop and wait for them to say it."
            )
        if major:
            return (
                f"{said}{point} Before anything else, correct them out loud. First "
                "tell them in ONE short sentence which word was wrong or missing, "
                "using the words themselves. Then say the whole sentence correctly, "
                f'stressing what you fixed: "{correct}" Then say "Now you say it." '
                "and stop and wait. Never name a grammar rule, never use grammar "
                "words, and do not ask a new question."
            )
        return (
            f"{said}{point} Start your reply with the fix and nothing else: name "
            "the wrong or missing word in three or four words, then say their "
            f'sentence back correctly, stressing what you fixed: "{correct}" Never '
            'say the word "mistake", never name a grammar rule and do not ask them '
            f"to repeat it — then carry on with the conversation.{follow}"
        )

    async def _nudge_quiet_learner(self):
        """Jim qolgan o'quvchiga ekranda 2-3 tayyor javob + ovozda dalda.

        Zinapoyaning eski 3-pog'onasi ("menga ergash, takrorla") bu rejimda
        yo'q: o'quvchi o'z gapini emas, birovning gapini takrorlashni o'rganib
        qolardi. O'rniga tanlov beriladi — ekrandan o'qib aytish ham gapirish,
        ham ma'no tanlash mashqi. AI esa javobni AYTMAYDI, faqat dalda beradi.
        """
        logger.info("adaptive_silence_nudge %s", self.log_ctx)
        # Daraja aniqlashda tayyor javob EKRANGA CHIQMAYDI.
        #
        # O'quvchi ekrandagi gapni o'qib aytadi va o'lchovda ravon ko'rinadi —
        # aslida u faqat o'qishni ko'rsatdi. Bu tuzatish diffi bilan bir xil
        # sabab (§_steer_after_evaluation): o'lchov o'quvchining O'Z nutqidan
        # chiqishi kerak. Ovozdagi dalda esa qoladi — jim qolgan o'quvchidan
        # hech qanday o'lchov chiqmaydi, ya'ni uni gapirtirish SHART.
        options = [] if self.state.mode == SessionMode.PLACEMENT else await self._answer_options()

        await self.gemini.send_directive(
            (
                "The learner is quiet. They can now see two or three possible "
                "answers on their screen. Encourage them warmly in one short "
                "sentence and wait. Do not answer for them and do not read the "
                "options out loud."
                if options
                else "The learner is quiet. Encourage them with one warm short "
                "sentence, then ask a simpler, more concrete version of your "
                "last question — or offer a two-way choice they can answer with "
                "one word. Do not answer for them and do not give them a "
                "sentence to repeat."
            ),
            tone="slow_encouraging",
            in_turn=False,
        )

        if options:
            await self.send_json({"type": "options", "items": options})

    async def _answer_options(self) -> list[dict]:
        """Coach yozgan tayyor javoblar. Byudjet tugasa — bo'sh ro'yxat."""
        if self.state.current_question_id is None:
            return []
        if await self.store.count_llm_calls() >= settings.COACH_MAX_CALLS:
            logger.warning("options_budget_exhausted %s", self.log_ctx)
            return []
        result = await coach.evaluate(await self._coach_context("", silent=True))
        await self.store.append_llm_call(result.usage)
        return result.options

    async def _give_hint(self, number: int):
        """Bitta pog'ona: ovozda (Live) va ekranda (matn) bir vaqtda."""
        question = await self._question_payload(self.state.current_question_id)
        result = coach.fallback("silence")

        # 1-pog'onada savol shunchaki takrorlanadi — LLM kerak emas, tekin.
        if number > 1 and await self.store.count_llm_calls() < settings.COACH_MAX_CALLS:
            result = await coach.evaluate(await self._coach_context("", silent=True))
            await self.store.append_llm_call(result.usage)

        ladder_finished = number >= hints.MAX_RUNG
        self.state.hint_rung = 0 if ladder_finished else number
        if ladder_finished:
            self.state.stuck_count += 1
        await self.store.save_state(self.state)

        rung = hints.rung(number)
        logger.info(
            "hint %s rung=%s kind=%s stuck=%s",
            self.log_ctx,
            number,
            rung.kind,
            self.state.stuck_count,
        )

        instruction, tone = hints.directive_for(number, result, question["question_text"])
        await self.gemini.send_directive(instruction, tone=tone, in_turn=False)

        await self.send_json(
            {
                "type": "hint",
                "rung": number,
                "kind": rung.kind,
                "label_uz": rung.label_uz,
                "text": hints.screen_text(number, result),
            }
        )

        # To'liq zinapoyadan ikki marta o'tdi va hamon jim — savolni yopamiz.
        # Busiz sessiya bitta savolda vaqt limitigacha osilib qolardi.
        if self.state.stuck_count >= hints.MAX_STUCK_BEFORE_MOVING_ON:
            self._disarm_silence_watchdog()
            decision = sm.evaluate(
                self.state, self.state.current_question_id, sm.Verdict.UNINTELLIGIBLE.value
            )
            await self.store.save_state(self.state)
            await self._apply_decision(decision, result, in_turn=False)
            if decision.action == sm.Action.END_SESSION:
                await self._graceful_end(EndReason.COMPLETED, already_instructed=True)

    async def _coach_context(self, utterance: str, *, silent: bool = False, exclude_idx: int = 0):
        turns = await self.store.get_turns()
        question_text, canonical_answer = await self._graded_against(turns, exclude_idx)
        return coach.CoachContext(
            register=self.state.register,
            target_structure=self.meta.get("target_structure", ""),
            focus_phrase=self.meta.get("focus_phrase", ""),
            mode=self.state.mode,
            question_text=question_text,
            canonical_answer=canonical_answer,
            attempt=self.state.attempt + 1,
            model_answer_given=self.state.model_answer_given,
            learner_utterance=utterance,
            recent_turns=turns[-coach.MAX_RECENT_TURNS :],
            recent_error_types=self.state.recent_error_types,
            structure_miss_streak=self.state.structure_miss_streak,
            open_goals=await self._open_goals(),
            learner_language=self.meta.get("learner_language", "uz"),
            silent=silent,
        )

    async def _open_goals(self) -> list[dict]:
        """Hali javob olinmagan maqsad-savollar.

        Erkin suhbatda bank savollari skript emas, qamrab olinishi kerak
        bo'lgan ro'yxat. O'quvchi bitta to'liq javobda bir nechtasini yopib
        ketishi mumkin — yopilgani boshqa so'ralmaydi (§coach.md).
        """
        if self.state.mode not in FREE_FLOW:
            return []
        covered = set(self.state.covered_question_ids)
        open_ids = [qid for qid in self.state.question_ids if qid not in covered]
        if not open_ids:
            return []
        return await self._goal_payloads(open_ids[: coach.MAX_OPEN_GOALS])

    @database_sync_to_async
    def _goal_payloads(self, question_ids: list[int]) -> list[dict]:
        from apps.content.models import Question

        rows = Question.objects.filter(pk__in=question_ids).values_list("id", "question_text")
        by_id = dict(rows)
        return [{"id": qid, "text": by_id[qid]} for qid in question_ids if by_id.get(qid)]

    async def _apply_covered_goals(self, result) -> None:
        """Coach yopilgan deb belgilagan maqsadlarni ro'yxatdan chiqaradi.

        Faqat shu sessiyaning savollari qabul qilinadi: coach o'ylab topgan
        raqam ro'yxatni buzmasligi kerak.
        """
        if self.state.mode not in FREE_FLOW or not result.covered_goal_ids:
            return
        known = set(self.state.question_ids)
        covered = set(self.state.covered_question_ids)
        fresh = [qid for qid in result.covered_goal_ids if qid in known and qid not in covered]
        if not fresh:
            return
        self.state.covered_question_ids.extend(fresh)
        await self.store.save_state(self.state)
        logger.info(
            "goals_covered %s ids=%s remaining=%d",
            self.log_ctx,
            fresh,
            len(known) - len(self.state.covered_question_ids),
        )

    async def _graded_against(self, turns: list[dict], exclude_idx: int = 0) -> tuple[str, str]:
        """Javob QAYSI savolga qarab baholanadi.

        Erkin suhbatda savolni model o'zi tanlaydi — bankdagi savol esa faqat
        GOALS ro'yxatidagi bir nuqta va u AYTILGAN savol emas. Bankdagi savol
        bilan solishtirilsa, coach o'quvchining gapini boshqa savolning
        javobiga tortadi: "Hello" → "My name is Aziz." Shuning uchun kontekst
        suhbatning o'zidan olinadi va etalon javob berilmaydi.
        """
        if self.state.mode in FREE_FLOW:
            for turn in reversed(turns):
                # Baholanayotgan gapning O'ZI. Live-first yo'lida navbat
                # baholashdan OLDIN yozib qo'yiladi (raqami tartib uchun kerak),
                # ya'ni u ro'yxatda allaqachon turadi. Chiqarib tashlanmasa
                # quyidagi tekshiruv o'sha gapni "oldingi javob" deb o'qib,
                # savolni hech qachon topmasdi.
                if exclude_idx and int(turn.get("idx") or 0) >= exclude_idx:
                    continue
                # O'quvchi navbati birinchi uchradi — demak AI ning oxirgi
                # savoli ALLAQACHON javob olgan va bu gap unga javob emas.
                #
                # Kuzatilgan xatti-harakat: "My name is Akbar." dan keyin
                # o'quvchi "What is your name?" deb SO'RADI, coach esa uni
                # o'sha eski "What is your name?" savoliga berilgan javob deb
                # baholab, "sizga 'My name is' kerak" deb tuzatdi. Sabab shu
                # sikl edi: u o'rtadagi o'quvchi navbatlarini sanamay, eng
                # oxirgi AI savoligacha orqaga qaytib ketardi.
                #
                # Matni bo'sh o'quvchi navbati ham hisoblanadi: live-first
                # yo'lida u BAND QILINGAN joy (§_append_learner_turn, reserve),
                # matni bir-ikki soniyadan keyin to'ldiriladi. O'tkazib
                # yuborilsa o'sha oynada aynan shu xato qaytib kelardi.
                if turn.get("speaker") == Speaker.LEARNER:
                    return "", ""
                if turn.get("speaker") == Speaker.AI and (turn.get("text") or "").strip():
                    return turn["text"].strip(), ""
            return "", ""

        q = await self._question_payload(self.state.current_question_id)
        return q["question_text"], q["canonical_answer"]

    async def _record_evaluation(self, question_id, attempt_before, utterance, result):
        """Baholash + coach topgan xatolar — post-session pipeline manbai (§4.6)."""
        if result.target_structure_used:
            self.state.structure_miss_streak = 0
        else:
            self.state.structure_miss_streak += 1
        for err in result.errors:
            self.state.recent_error_types.append(err["type"])
        del self.state.recent_error_types[:-6]
        self.state.recent_fluency.append(result.fluency)
        del self.state.recent_fluency[:-5]
        await self.store.save_state(self.state)

        await self.store.append_evaluation(
            {
                "question_id": question_id,
                "attempt": attempt_before + 1,
                "verdict": result.verdict,
                "target_structure_used": result.target_structure_used,
                "error_type": result.error_type,
                "learner_utterance": utterance,
                "recovered_after_model": (
                    result.verdict == sm.Verdict.CORRECT.value and self.state.model_answer_given
                ),
                "at_ms": self._elapsed_ms(),
            }
        )
        await self.store.append_coach(
            {
                "question_id": question_id,
                "attempt": attempt_before + 1,
                "utterance": utterance,
                "verdict": result.verdict,
                "target_structure_used": result.target_structure_used,
                "errors": result.errors,
                "fluency": result.fluency,
                "ok": result.ok,
                "at_ms": self._elapsed_ms(),
            }
        )

    async def _adapt_register(self) -> str:
        """AI registrini o'quvchi nutqiga moslaydi. LLM kerak emas — tekin."""
        answered = (
            self.state.evaluated_total if self.state.mode in FREE_FLOW else self.state.asked_total
        )
        signals = adaptive.signals_from_state(
            self.state, self.state.recent_fluency, answered=answered
        )
        new_register = adaptive.next_register(self.state.register, signals)
        if new_register == self.state.register:
            return ""

        logger.info(
            "register %s %s → %s accuracy=%.2f fluency=%.1f stuck=%s",
            self.log_ctx,
            self.state.register,
            new_register,
            signals.first_attempt_accuracy,
            signals.avg_fluency,
            signals.stuck_count,
        )
        self.state.register = new_register
        await self.store.save_state(self.state)
        # Keyingi sessiya shu nuqtadan boshlanadi — o'quvchi har safar
        # o'zini qaytadan "tanishtirmasligi" kerak (§users.speaking_register).
        await self._persist_register(new_register)
        await self.send_json({"type": "register", "value": new_register})
        return adaptive.pacing_clause(new_register)

    @database_sync_to_async
    def _persist_register(self, register: int) -> None:
        from apps.users.models import User

        User.objects.filter(pk=self.user.id).update(speaking_register=register)

    async def _apply_decision(
        self,
        decision: sm.Decision,
        result,
        *,
        pacing: str = "",
        queue: bool = False,
        in_turn: bool = True,
    ):
        """`state.py` qarorini Live uchun sahna ko'rsatmasiga aylantiradi.

        Bo'linish qat'iy: NIMA bo'lishini `state.py` hal qiladi (deterministik,
        testlanadigan), NIMA DEYISHNI coach yozadi (tabiiy, jonli). Shuning
        uchun LLM hech qachon sessiya oqimini buzib yubora olmaydi.
        """
        action = decision.action
        instruction, tone = await self._directive_for(action, decision, result)
        if not instruction:
            return
        # Registr o'zgarishi alohida navbat sifatida yuborilmaydi — u shu
        # ko'rsatmaning boshiga qo'shiladi, ya'ni qo'shimcha audio sarflamaydi.
        if pacing:
            instruction = f"{pacing} {instruction}"
        if not tone:
            tone = adaptive.tone_for(
                self.state.register,
                result.verdict,
                result.fluency,
                stuck=self.state.stuck_count > 0,
            )
        if queue:
            self._queue_directive(instruction, tone)
            return
        await self.gemini.send_directive(instruction, tone=tone, in_turn=in_turn)

    async def _bridge_question(self, result) -> str:
        """Coach yozgan dinamik savol — tekshiruvdan o'tsa ishlatiladi.

        Drill rejimida u faqat o'quvchi strukturani ketma-ket ishlatmayotgan
        bo'lsa qo'shiladi: takrorlash mashqining ritmini behuda buzmaslik kerak.
        Guided rejimida esa har safar — suhbat aynan shu bilan tirik qoladi.
        """
        question = (result.next_question or "").strip()
        if not question:
            return ""
        if (
            self.state.mode == "anticipation_drill"
            and self.state.structure_miss_streak < STRUCTURE_MISS_LIMIT
        ):
            return ""

        problems = validators.validate_generated_question(
            question,
            self.meta.get("target_structure", ""),
            self.state.register,
        )
        if problems:
            logger.info("generated_question_rejected %s %s: %s", self.log_ctx, question, problems)
            return ""

        # Sifatli savol bankka qoralama bo'lib qaytadi — bank o'z-o'zidan o'sadi.
        await self._save_generated_question(question)
        return question

    @database_sync_to_async
    def _save_generated_question(self, text: str) -> None:
        from apps.content.models import Question, QuestionSource, QuestionStatus

        topic_id = self.meta.get("topic_id")
        if not topic_id:
            return
        Question.objects.get_or_create(
            topic_id=topic_id,
            question_text=text,
            defaults={
                "canonical_answer": "",
                "elicitation_note": "Sessiyada real vaqtda generatsiya qilindi.",
                "status": QuestionStatus.DRAFT,
                "source": QuestionSource.GENERATED,
                "order": 999,
            },
        )

    async def _directive_for(self, action, decision: sm.Decision, result) -> tuple[str, str]:
        reaction = result.reaction

        if action == sm.Action.RETRY:
            q = await self._question_payload(self.state.current_question_id)
            nudge = reaction or "Almost — try again."
            return (
                f'Say "{nudge}" and then ask this question again, word for word: '
                f'"{q["question_text"]}". Do not give the answer. Then stop and wait.',
                "slow_encouraging",
            )

        if action == sm.Action.CLARIFY:
            return (
                'Say "Sorry, could you say that again?" and then stop and wait.',
                "slow_encouraging",
            )

        if action == sm.Action.GIVE_MODEL_ANSWER:
            q = await self._question_payload(self.state.current_question_id)
            # Coach o'quvchining o'z gapini tuzatadi; bo'lmasa DB etaloni (§4.4).
            model_answer = result.model_answer or q["canonical_answer"]
            return (
                f'Say exactly: "{model_answer}" Then say "Repeat after me:" and say '
                "that same sentence once more. Wait for the learner to repeat it out "
                f'loud. Then ask this question again, word for word: "{q["question_text"]}".',
                "slow_encouraging",
            )

        if action in (sm.Action.NEXT_QUESTION, sm.Action.ASK_QUESTION):
            qid = decision.payload.get("question_id") or self.state.current_question_id
            q = await self._question_payload(qid)
            self._pending_question_id = qid
            lead = f'Say "{reaction}" and then ' if reaction else "Then "

            # Bank savoli — o'lchanadigan element, har doim so'zma-so'z beriladi.
            # Coach yozgan savol esa ko'prik: javobga bog'lanadi va target
            # strukturani yana bir bor majburlaydi (§Faza 5).
            bridge = await self._bridge_question(result)

            if self.state.mode == "anticipation_drill":
                if bridge:
                    return (
                        f'{lead}ask this question, word for word: "{bridge}". Listen to '
                        f'the answer, then ask: "{q["question_text"]}". Then stop and wait.',
                        "",
                    )
                return (
                    f'{lead}ask this new question, word for word: "{q["question_text"]}". '
                    "Then stop and wait.",
                    "",
                )

            follow_up = (
                f'ask this follow-up, word for word: "{bridge}"'
                if bridge
                else "ask one short improvised follow-up about what they just said"
            )
            return (
                f"{lead}{follow_up}, listen to the answer, and only then ask this "
                f'question word for word: "{q["question_text"]}".',
                "",
            )

        if action == sm.Action.END_SESSION:
            return (
                "The session is over. Say one warm closing sentence praising "
                "something specific the learner did, then stop.",
                "warm",
            )

        return "", ""

    @database_sync_to_async
    def _question_payload(self, question_id) -> dict:
        from apps.content.models import Question

        q = Question.objects.filter(pk=question_id).first()
        if not q:
            return {
                "question_id": question_id,
                "question_text": "",
                "canonical_answer": "",
                "elicitation_note": "",
            }
        return {
            "question_id": q.id,
            "question_text": q.question_text,
            "canonical_answer": q.canonical_answer,
            "elicitation_note": q.elicitation_note or "",
        }

    # --- transkript buferi ------------------------------------------------
    async def _send_transcript(self, speaker: str, text: str, *, final: bool, idx: int = 0):
        """Jonli transkript (§5.1). `final=False` — o'sib borayotgan bo'lak.

        Client bo'laklarni ketma-ket qo'shib boradi, `final` kelganda esa butun
        gapni almashtiradi: yakuniy matn buferdan emas, tool call'dan ham kelishi
        mumkin, ya'ni bo'laklar yig'indisidan farq qilishi mumkin.
        """
        if not (text or "").strip():
            return
        await self.send_json(
            {"type": "transcript", "speaker": speaker, "text": text, "final": final, "idx": idx}
        )

    async def _flush_ai_turn(self):
        text = "".join(self._ai_buffer).strip()
        if self._ai_leaked:
            text, leaked = strip_director_leak(text)
            if leaked:
                # Prompt regressiyasining yagona o'lchanadigan signali (§base.md).
                logger.warning("director_leak %s mode=%s", self.log_ctx, self.state.mode)
            self._ai_leaked = False
        started = self._ai_turn_started_ms
        self._ai_buffer = []
        self._ai_turn_started_ms = None
        ended = self._elapsed_ms()
        self._ai_turn_ended_ms = ended
        if not text and started is None:
            return
        idx = self._next_turn_idx()
        await self.store.append_turn(
            {
                "idx": idx,
                "speaker": Speaker.AI,
                "text": text,
                "started_at_ms": started if started is not None else ended,
                "ended_at_ms": ended,
                "question_id": self._pending_question_id,
            }
        )
        await self._send_transcript(Speaker.AI, text, final=True, idx=idx)
        if text:
            self._translate_tasks.add(asyncio.create_task(self._translate_turn(idx, text)))

    async def _translate_turn(self, idx: int, text: str):
        """AI gapining o'zbekchasi — ovoz aytilib bo'lgach, ekranga.

        Fon vazifasi: tarjima kechiksa ham suhbat kutmaydi. Yiqilsa gap
        tarjimasiz qoladi — bu sessiyani to'xtatadigan hodisa emas.
        """
        try:
            text_uz, usage = await translate.to_learner_language(
                text, self.meta.get("learner_language", "")
            )
            await self.store.append_llm_call(usage, kind="translate")
            if not text_uz or self._closing:
                return
            await self.store.update_turn(idx, text_uz=text_uz)
            await self.send_json({"type": "translation", "idx": idx, "text_uz": text_uz})
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — tarjima sessiyani yiqitmaydi
            logger.warning("translate_task_failed %s: %s", self.log_ctx, exc)
        finally:
            self._translate_tasks.discard(asyncio.current_task())

    def _take_learner_turn(self) -> tuple[str, int | None, int]:
        """Live transkript buferini bo'shatadi: (matn, boshlanish, tugash).

        Buferni navbat YOPILGANDA olish muhim: live-first yo'lida baholash
        fonda ~2 s ketadi va o'sha vaqt ichida keyingi gapning bo'laklari
        kelib qoladi. Buferni keyin o'qisak, ikki navbat bir-biriga qo'shilib
        ketardi.
        """
        text = "".join(self._learner_buffer).strip()
        started = self._learner_turn_started_ms
        ended = self._learner_last_ms or self._elapsed_ms()
        self._learner_buffer = []
        self._learner_turn_started_ms = None
        self._learner_last_ms = None
        return text, started, ended

    async def _append_learner_turn(
        self, text: str, started: int | None, ended: int, *, reserve: bool = False
    ) -> int:
        """Gapni yozadi va navbat raqamini qaytaradi.

        `reserve` — matn hali yo'q, lekin RAQAM hozir kerak. Live-first yo'lida
        so'zma-so'z matn baholashdan keyin keladi, o'sha vaqt ichida esa AI
        navbati ham yozilib qoladi: raqam keyin olinsa transkript tartibi
        buzilardi. Bo'sh yozuv ekranga chiqmaydi (§_send_transcript) va coach
        kontekstiga ham tushmaydi — matn kelgach o'sha joyga to'ldiriladi.
        """
        if not text and not reserve:
            return 0
        idx = self._next_turn_idx()
        await self.store.append_turn(
            {
                "idx": idx,
                "speaker": Speaker.LEARNER,
                "text": text,
                "started_at_ms": started if started is not None else ended,
                "ended_at_ms": ended,
                "question_id": self._pending_question_id,
                # Javob kechikishi shu yerdan hisoblanadi (§4.6.2).
                "prev_ai_end_ms": self._ai_turn_ended_ms,
            }
        )
        await self._send_transcript(Speaker.LEARNER, text, final=True, idx=idx)
        return idx

    async def _flush_learner_turn(self, verbatim: str = "") -> int:
        """Yakuniy o'quvchi gapini yozadi va uning navbat raqamini qaytaradi.

        `verbatim` — ASR ning so'zma-so'z matni. Berilgan bo'lsa u USTUN
        turadi: Live transkripti "I from Uzbekistan" ni jimgina "I'm from
        Uzbekistan" qilib beradi, ekranda esa o'quvchi o'z gapini xatosi
        bilan ko'rishi kerak — tuzatish diffi ham aynan shunga qo'yiladi
        (§asr.py). ASR jim qolsa Live transkripti ishlatiladi.
        """
        buffered, started, ended = self._take_learner_turn()
        text = (verbatim or "").strip() or buffered
        return await self._append_learner_turn(text, started, ended)

    def _next_turn_idx(self) -> int:
        self._turn_idx += 1
        return self._turn_idx

    # --- yakunlash --------------------------------------------------------
    async def _deadline_watchdog(self):
        """Sessiya vaqt limiti (§4.4)."""
        limit = self.session.time_limit_seconds
        elapsed = self._elapsed_ms() / 1000
        remaining = max(0.0, limit - elapsed)
        try:
            await asyncio.sleep(remaining)
        except asyncio.CancelledError:
            return
        logger.info("session_time_limit %s", self.log_ctx)
        await self._graceful_end(EndReason.TIME_LIMIT)

    async def _graceful_end(self, reason: str, *, already_instructed: bool = False):
        if self._closing:
            return
        if self.gemini and self.gemini.connected and not already_instructed:
            try:
                await self.gemini.send_text(
                    "The session time is up. Say one warm closing sentence and stop."
                )
                # Yakunlovchi gap aytilishiga qisqa vaqt beramiz.
                await asyncio.sleep(CLOSING_GRACE_SECONDS)
            except Exception:  # noqa: BLE001
                pass
        elif already_instructed:
            await asyncio.sleep(CLOSING_GRACE_SECONDS)
        await self._teardown(reason)

    async def _teardown(self, reason: str):
        if self._closing:
            return
        self._closing = True
        await self._flush_ai_turn()
        await self._flush_learner_turn()
        if self.state is not None:
            self.state.phase = sm.Phase.ENDED.value
            self.state.ended_reason = reason
            await self.store.save_state(self.state)
        await self._cancel_tasks()
        if self.gemini:
            await self.gemini.close()
        await self.send_json({"type": "session_end", "reason": reason})
        await self._finalize_db(reason)
        await self.store.release_lock()
        await self.store.close()
        await self.close()

    async def _cancel_tasks(self):
        tasks = (self._reader_task, self._deadline_task, self._silence_task)
        for task in (*tasks, *tuple(self._coach_tasks), *tuple(self._translate_tasks)):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
        self._coach_tasks.clear()
        self._translate_tasks.clear()
        self._silence_task = None
        self._close_task = None
        self._speculative = None

    @database_sync_to_async
    def _finalize_db(self, reason: str):
        from .services import finalize_session

        session = Session.objects.filter(pk=self.session_id).first()
        if session:
            finalize_session(session, reason, int(self._elapsed_ms() / 1000))

    @database_sync_to_async
    def _schedule_grace_finalize(self):
        from .tasks import finalize_if_abandoned

        finalize_if_abandoned.apply_async(
            args=[str(self.session_id)],
            countdown=settings.SESSION_RESUME_GRACE_SECONDS,
        )

    @database_sync_to_async
    def _load_session(self):
        return Session.objects.select_related("user", "topic").filter(pk=self.session_id).first()

    @database_sync_to_async
    def _mark_started(self):
        now = timezone.now()
        Session.objects.filter(pk=self.session_id, started_at__isnull=True).update(started_at=now)
        self.session.started_at = now
        return now

    # --- yordamchilar -----------------------------------------------------
    def _token_from_query(self) -> str:
        raw = (self.scope.get("query_string") or b"").decode()
        for pair in raw.split("&"):
            if pair.startswith("token="):
                from urllib.parse import unquote

                return unquote(pair[6:])
        # Sarlavha orqali ham qabul qilinadi (desktop klientlar uchun).
        for key, value in self.scope.get("headers", []):
            if key == b"authorization":
                parts = value.decode().split()
                if len(parts) == 2 and parts[0].lower() == "bearer":
                    return parts[1]
        return ""

    def _elapsed_ms(self) -> int:
        """Sessiya boshidan o'tgan vaqt — reconnect'dan keyin ham uzluksiz."""
        if getattr(self, "_started_wall", None) is None:
            return int((time.monotonic() - self._t0) * 1000)
        return max(0, int((timezone.now() - self._started_wall).total_seconds() * 1000))

    async def send_json(self, payload: dict):
        try:
            await self.send(text_data=json.dumps(payload))
        except Exception:  # noqa: BLE001 — client allaqachon ketgan bo'lishi mumkin
            pass
