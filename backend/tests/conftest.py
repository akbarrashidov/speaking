"""Umumiy test fixture'lari. Tashqi servislar (Redis, Postgres, LLM) ishlatilmaydi."""

import fakeredis
import fakeredis.aioredis
import pytest
from django.utils import timezone

from apps.content.models import (
    Chunk,
    ContentStatus,
    Material,
    Question,
    QuestionStatus,
    SessionMode,
    Topic,
)
from apps.practice import store as store_mod
from apps.users.models import Plan, User


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    """Barcha Redis chaqiruvlari xotiradagi soxta serverga yo'naltiriladi."""
    server = fakeredis.FakeServer()
    sync = fakeredis.FakeRedis(server=server, decode_responses=True)

    monkeypatch.setattr(store_mod, "sync_client", lambda: sync)
    monkeypatch.setattr(store_mod, "_sync_pool", sync, raising=False)
    # `services` moduli `sync_client` ni O'ZIGA import qilgan, ya'ni yuqoridagi
    # patch unga yetib bormaydi. Shu bog'lam ham almashtiriladi — aks holda
    # sessiya meta'si soxta emas, HAQIQIY Redis'ga yozilib ketadi.
    monkeypatch.setattr("apps.practice.services.sync_client", lambda: sync)
    monkeypatch.setattr(
        store_mod,
        "async_client",
        lambda: fakeredis.aioredis.FakeRedis(server=server, decode_responses=True),
    )
    return sync


@pytest.fixture
def user(db):
    return User.objects.create_user(
        email="learner@example.com",
        password="TestParol123",
        first_name="Ali",
    )


@pytest.fixture
def premium_user(db):
    return User.objects.create_user(
        email="pro@example.com",
        password="TestParol123",
        first_name="Pro",
        plan=Plan.PREMIUM,
    )


def make_topic(order=1, *, questions=4, mode="", status=ContentStatus.PUBLISHED):
    topic = Topic.objects.create(
        order=order,
        title_uz=f"Mavzu {order}",
        title_en=f"Topic {order}",
        # `target_structure` DB darajasida unikal — har mavzuga o'ziniki.
        target_structure=f"present_simple_affirmative_{order}",
        session_mode=mode,
        status=status,
        max_questions=10,
    )
    Material.objects.create(
        topic=topic,
        rule_uz="Qisqa qoida.",
        examples=[{"en": "I live here.", "uz": "Men shu yerda yashayman."}],
    )
    Chunk.objects.create(topic=topic, text="every day", translation_uz="har kuni")
    for i in range(1, questions + 1):
        Question.objects.create(
            topic=topic,
            order=i,
            question_text=f"What do you do on day {i}?",
            canonical_answer=f"I work on day {i}.",
            answer_variants=[f"I rest on day {i}."],
            elicitation_note="Full sentence required.",
            status=QuestionStatus.APPROVED,
        )
    return topic


@pytest.fixture
def topic(db):
    return make_topic(order=1, mode=SessionMode.ANTICIPATION_DRILL)


@pytest.fixture
def topic2(db):
    return make_topic(order=2, mode=SessionMode.ANTICIPATION_DRILL)


@pytest.fixture
def b1_topic(db):
    return make_topic(order=1, mode=SessionMode.GUIDED_CONVERSATION)


@pytest.fixture
def adaptive_topic(db):
    """Erkin suhbat — ro'yxatdagi birinchi mavzu (`ensure_bootstrapped` ochadi)."""
    return make_topic(order=1, mode=SessionMode.ADAPTIVE_CONVERSATION)


@pytest.fixture
def active_progress(db, user, topic):
    from apps.progress.models import TopicProgress, TopicStatus

    return TopicProgress.objects.create(user=user, topic=topic, status=TopicStatus.ACTIVE)


@pytest.fixture
def auth_client(user):
    from rest_framework.test import APIClient

    from apps.users.jwt_utils import issue_token

    client = APIClient()
    token, _ = issue_token(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


@pytest.fixture
def now():
    return timezone.now()


# --- WS sessiyasi uchun umumiy soxta servislar ----------------------------
# `test_consumer.py` va `test_hints.py` ikkalasi ham shulardan foydalanadi.


class FakeGemini:
    """Gemini Live o'rniga: yuborilganlarni yozib boradi, eventlarni test beradi."""

    instances: list = []

    def __init__(self, system_prompt, *, session_id="", model="fake-live-model", **kwargs):
        import asyncio

        self.system_prompt = system_prompt
        self.session_id = session_id
        self.model = model
        self.queue = asyncio.Queue()
        self.sent_text = []
        self.directives = []
        self.audio_chunks = []
        self.stream_ends = 0
        self.activity_starts = 0
        self.activity_ends = 0
        self.closed = False
        FakeGemini.instances.append(self)

    # --- klient interfeysi ---
    async def connect(self, timeout=15.0):
        return None

    async def wait_for_setup(self, timeout=15.0):
        return None

    @property
    def connected(self):
        return not self.closed

    async def send_text(self, text, *, role="user", turn_complete=True):
        self.sent_text.append(text)

    async def send_directive(self, instruction, *, tone="", in_turn=True):
        # `in_turn` — javobni kim ochadi: `activityEnd` (True) yoki
        # ko'rsatmaning o'zi (False). Noto'g'ri bo'lsa model bir navbatda
        # ikkita javob aytadi (§gemini.send_directive), shuning uchun yoziladi.
        self.directives.append({"text": instruction, "tone": tone, "in_turn": in_turn})

    async def send_audio_chunk(self, b64):
        self.audio_chunks.append(b64)

    async def send_audio_stream_end(self):
        self.stream_ends += 1

    # §5.1a — navbat yakunini backend hal qiladi, server VAD'i emas.
    async def send_activity_start(self):
        self.activity_starts += 1

    async def send_activity_end(self):
        self.stream_ends += 1
        self.activity_ends += 1

    async def close(self):
        self.closed = True
        await self.queue.put(None)

    async def events(self):
        while True:
            item = await self.queue.get()
            if item is None:
                break
            yield item

    # --- test yordamchilari ---
    async def emit(self, event):
        import asyncio

        await self.queue.put(event)
        await asyncio.sleep(0.05)  # consumer ishlab bo'lishini kutamiz


@pytest.fixture
def fake_gemini(monkeypatch):
    from apps.practice import consumer as consumer_mod

    FakeGemini.instances = []
    monkeypatch.setattr(consumer_mod, "GeminiLiveClient", FakeGemini)
    monkeypatch.setattr(consumer_mod, "CLOSING_GRACE_SECONDS", 0)
    monkeypatch.setattr(consumer_mod, "TURN_END_GRACE_SECONDS", 0)
    monkeypatch.setattr(consumer_mod, "SHORT_UTTERANCE_EXTRA_GRACE", 0)
    return FakeGemini


def coach_result(verdict, *, error_type="", **kwargs):
    """Coach natijasi — testlar uchun qisqa konstruktor."""
    from apps.practice.coach import CoachResult

    errors = (
        [{"span": "x", "fix": "y", "type": error_type, "severity": "medium"}] if error_type else []
    )
    defaults = {
        "verdict": verdict,
        "target_structure_used": verdict == "correct",
        "errors": errors,
        "ok": True,
        "usage": {"model": "test-coach", "in": 300, "out": 90},
    }
    defaults.update(kwargs)
    return CoachResult(**defaults)


@pytest.fixture
def hold_turn(settings):
    """Eski yo'l: model coach javobini kutadi (§settings.LIVE_FIRST_ENABLED).

    Erkin suhbatning ODATIY yo'li endi live-first — xatoni model o'zi topadi
    va ovozga hech qanday DIRECTOR ketmaydi. Ko'rsatma MATNINI tekshiradigan
    testlar shu bois aynan zaxira yo'lni so'raydi: u hamon mavjud (skript
    rejimlari butunlay shu yo'lda ishlaydi) va sinovsiz qolmasligi kerak.
    """
    settings.LIVE_FIRST_ENABLED = False
    return settings


@pytest.fixture
def fake_coach(monkeypatch):
    """Coach javoblarini ssenariylashtiradi (LLM chaqirilmaydi)."""
    from types import SimpleNamespace

    from apps.practice import consumer as consumer_mod

    scripted = []
    calls = []

    async def fake_evaluate(ctx):
        calls.append(ctx)
        if scripted:
            return scripted.pop(0)
        return coach_result("correct")

    monkeypatch.setattr(consumer_mod.coach, "evaluate", fake_evaluate)
    return SimpleNamespace(scripted=scripted, calls=calls)
