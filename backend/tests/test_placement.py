"""Ro'yxatdan o'tishning 2-qadami + daraja aniqlash suhbati.

Uchta narsa tekshiriladi va ular bir zanjir:

1. O'quvchi o'zi aytgan daraja `speaking_register` ga URUG' bo'ladi — daraja
   maydoni emas, taxmin (§users.DeclaredLevel).
2. Daraja aniqlash suhbati alohida rejim: mavzu yo'q, tuzatish yo'q, o'lchov
   bor (§prompts, §placement).
3. Suhbat "gapirolmaydi" degan xulosa bersa — o'quvchi boshlang'ich qismga
   qaytariladi (§progress.reset_to_first_topic).
"""

import json

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.content.models import ContentStatus, SessionMode, Topic, TopicTrack
from apps.practice import adaptive, placement
from apps.practice.models import EndReason, Session, SessionStatus
from apps.practice.tasks import process_session
from apps.progress import services as progress_services
from apps.progress.models import TopicProgress, TopicStatus
from apps.users.models import DeclaredLevel


@pytest.fixture
def placement_topic(db):
    """Daraja aniqlash mavzusi.

    Migratsiya uni har o'rnatishda yaratadi, lekin `transaction=True` testlari
    jadvallarni TRUNCATE qiladi va migratsiya ma'lumoti ular bilan birga
    yo'qoladi. Shu bois bu yerda migratsiyadagi bilan bir xil qatorni tiklaydi.
    """
    from apps.content.models import Question, QuestionStatus

    topic, created = Topic.objects.get_or_create(
        target_structure="placement_probe",
        defaults={
            "track": TopicTrack.PLACEMENT,
            "order": 1,
            "title_uz": "Darajani aniqlash",
            "session_mode": SessionMode.PLACEMENT,
            "status": ContentStatus.PUBLISHED,
            "max_questions": 8,
        },
    )
    if created or not topic.questions.exists():
        for i, text in enumerate(
            [
                "What is your name?",
                "Where do you live?",
                "What do you do every day?",
                "What did you do yesterday?",
                "What are you going to do tomorrow?",
                "Why do you want to learn English?",
            ],
            start=1,
        ):
            Question.objects.get_or_create(
                topic=topic,
                question_text=text,
                defaults={
                    "canonical_answer": "...",
                    "status": QuestionStatus.APPROVED,
                    "order": i,
                },
            )
    return topic


# --- 1-qadam -> 2-qadam ---------------------------------------------------


@pytest.mark.django_db
def test_a_new_account_has_neither_step_finished(auth_client):
    """Klient yo'lni shu ikki bayroq bilan tanlaydi — ular javobda bo'lishi shart."""
    body = auth_client.get(reverse("me")).json()
    assert body["user"]["onboarding_completed"] is False
    assert body["user"]["placement_done"] is False


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("level", "register"),
    [
        (DeclaredLevel.BEGINNER, 0),
        (DeclaredLevel.ELEMENTARY, 1),
        (DeclaredLevel.INTERMEDIATE, 3),
        (DeclaredLevel.ADVANCED, adaptive.MAX_REGISTER),
    ],
)
def test_the_declared_level_seeds_the_register(auth_client, user, level, register):
    """Aytilgan daraja registrga aylanadi — yangi "daraja" maydoni tug'ilmaydi."""
    response = auth_client.post(
        reverse("me-onboarding"),
        {"declared_level": level.value, "learning_background": "maktabda 5 yil o'qidim"},
        format="json",
    )
    assert response.status_code == 200

    user.refresh_from_db()
    assert user.speaking_register == register
    assert user.declared_level == level.value
    assert user.learning_background == "maktabda 5 yil o'qidim"
    assert user.onboarding_completed is True
    # O'lchov hali bo'lmagan: bu taxmin, xulosa emas.
    assert user.placement_done is False


@pytest.mark.django_db
def test_an_unknown_level_is_refused(auth_client, user):
    response = auth_client.post(reverse("me-onboarding"), {"declared_level": "C2"}, format="json")
    assert response.status_code == 400
    assert "declared_level" in response.json()["fields"]
    user.refresh_from_db()
    assert user.onboarding_completed is False


@pytest.mark.django_db
def test_the_background_text_is_optional(auth_client, user):
    """Izoh ixtiyoriy: uni majburlash ro'yxatdan o'tishni to'xtatib qo'yardi."""
    response = auth_client.post(
        reverse("me-onboarding"),
        {"declared_level": DeclaredLevel.ELEMENTARY.value},
        format="json",
    )
    assert response.status_code == 200
    user.refresh_from_db()
    assert user.learning_background == ""
    assert user.onboarding_completed is True


# --- daraja aniqlash suhbati ---------------------------------------------


@pytest.mark.django_db
def test_the_placement_topic_ships_with_the_migration(placement_topic):
    """Kontent emas, infratuzilma: busiz yangi foydalanuvchi hech qayerga bormaydi."""
    topic = Topic.objects.get(track=TopicTrack.PLACEMENT)
    assert topic.status == ContentStatus.PUBLISHED
    assert topic.effective_mode == SessionMode.PLACEMENT
    assert topic.approved_questions().count() >= 5


@pytest.mark.django_db
def test_placement_starts_without_the_client_knowing_the_topic(auth_client, user, placement_topic):
    """Klient mavzu raqamini bilmaydi — u ro'yxatlarda ko'rinmaydi ham."""
    response = auth_client.post(reverse("placement-start"), format="json")
    assert response.status_code == 201, response.json()

    body = response.json()
    session = Session.objects.get(pk=body["session_id"])
    assert session.mode == SessionMode.PLACEMENT
    assert session.topic.track == TopicTrack.PLACEMENT


@pytest.mark.django_db
def test_placement_is_not_gated_by_progress(user, placement_topic):
    """Uni ochib beradigan oldingi mavzu yo'q — u BIRINCHI ish."""
    topic = Topic.objects.get(track=TopicTrack.PLACEMENT)
    assert progress_services.is_topic_accessible(user, topic) is True
    # Va u progress ro'yxatiga yozilmaydi.
    progress_services.ensure_bootstrapped(user)
    assert not TopicProgress.objects.filter(user=user, topic=topic).exists()


@pytest.mark.django_db
def test_placement_start_reports_a_missing_topic_instead_of_failing_quietly(
    auth_client, placement_topic
):
    Topic.objects.filter(track=TopicTrack.PLACEMENT).update(status=ContentStatus.DRAFT)
    response = auth_client.post(reverse("placement-start"), format="json")
    assert response.status_code == 503
    assert response.json()["error"] == "placement_unavailable"


@pytest.mark.django_db(transaction=True)
async def test_placement_shows_no_corrections_on_screen(
    fake_gemini, fake_coach, user, placement_topic
):
    """O'lchov toza bo'lishi kerak: diff ham ovoz kabi yo'q.

    O'quvchi ekranda tuzatishni ko'rsa keyingi javobini o'shanga qarab
    tuzatadi — va o'lchov u nimani bilganini emas, nechta tuzatishni o'qib
    olganini ko'rsatadi. Baholash o'zi ishlaydi: xulosa aynan shundan chiqadi.
    """
    import asyncio
    import base64
    import contextlib

    from channels.db import database_sync_to_async
    from channels.routing import URLRouter
    from channels.testing import WebsocketCommunicator

    from apps.practice import asr
    from apps.practice.routing import websocket_urlpatterns
    from apps.practice.services import start_session
    from apps.users.jwt_utils import issue_token
    from conftest import coach_result

    async def verbatim(pcm, target_structure=""):
        return "I from Uzbekistan", {}

    original = asr.transcribe
    asr.transcribe = verbatim
    try:
        payload = await database_sync_to_async(start_session)(user, placement_topic.id)
        token, _ = await database_sync_to_async(issue_token)(user)
        communicator = WebsocketCommunicator(
            URLRouter(websocket_urlpatterns),
            f"/ws/session/{payload['session_id']}/?token={token}",
        )
        connected, _ = await communicator.connect()
        assert connected
        try:
            await asyncio.sleep(0.3)
            gemini = fake_gemini.instances[-1]
            fake_coach.scripted.append(coach_result("incorrect", error_type="missing_auxiliary"))

            chunk = base64.b64encode(bytes([0, 64]) * 16000).decode()
            await communicator.send_to(text_data=json.dumps({"type": "speech_start"}))
            await asyncio.sleep(0.05)
            await communicator.send_to(text_data=json.dumps({"type": "audio_chunk", "data": chunk}))
            await communicator.send_to(text_data=json.dumps({"type": "speech_end"}))
            await asyncio.sleep(0.6)

            messages = []
            while True:
                try:
                    messages.append(json.loads(await communicator.receive_from(timeout=0.2)))
                except Exception:  # noqa: BLE001 — navbat bo'shadi
                    break

            assert not [m for m in messages if m["type"] == "correction"], (
                "daraja aniqlashda tuzatish ekranga chiqdi"
            )
            # Baholash esa ishladi — xulosa shu yozuvlardan chiqadi.
            assert fake_coach.calls, "daraja aniqlashda baholash umuman ishlamadi"
            # Va ovozga ham hech qanday ko'rsatma ketmadi.
            assert gemini.directives == []
            # Sessiya o'z-o'zidan yakunlanmadi: o'lchov davom etishi kerak.
            assert not [m for m in messages if m["type"] == "session_end"]
        finally:
            # Consumer bu paytda o'zini yopib bo'lgan bo'lishi mumkin (fon
            # vazifalari + testdagi nol kutish oynalari). Yopilgan ulanishga
            # `disconnect` yuborish CancelledError beradi va u tekshirilgan
            # xatti-harakatga aloqasiz — yuqoridagi tasdiqlar allaqachon o'tdi.
            # `CancelledError` — `BaseException`, ya'ni `Exception` uni tutmaydi.
            with contextlib.suppress(asyncio.CancelledError):
                await communicator.disconnect()
    finally:
        asr.transcribe = original


@pytest.mark.django_db(transaction=True)
async def test_a_quiet_learner_is_nudged_by_voice_not_by_the_screen(
    fake_gemini, fake_coach, user, placement_topic, monkeypatch
):
    """Jim qolganda dalda OVOZDA keladi, tayyor javoblar ekranga chiqmaydi.

    Ekrandagi gapni o'quvchi o'qib aytadi va o'lchovda ravon ko'rinadi — aslida
    u faqat o'qishni ko'rsatdi. Lekin jim o'quvchidan ham hech qanday o'lchov
    chiqmaydi, ya'ni turtki kerak: shuning uchun ovoz qoladi, ekran ketadi.
    """
    import asyncio
    import contextlib

    from channels.db import database_sync_to_async
    from channels.routing import URLRouter
    from channels.testing import WebsocketCommunicator

    from apps.practice import hints
    from apps.practice.routing import websocket_urlpatterns
    from apps.practice.services import start_session
    from apps.users.jwt_utils import issue_token

    monkeypatch.setattr(hints, "SILENCE_SECONDS", {user.speaking_register: 0.05})

    payload = await database_sync_to_async(start_session)(user, placement_topic.id)
    token, _ = await database_sync_to_async(issue_token)(user)
    communicator = WebsocketCommunicator(
        URLRouter(websocket_urlpatterns),
        f"/ws/session/{payload['session_id']}/?token={token}",
    )
    connected, _ = await communicator.connect()
    assert connected
    try:
        await asyncio.sleep(0.3)
        gemini = fake_gemini.instances[-1]
        # Model gapirib bo'ldi — navbat o'quvchida, jimlik taymeri qo'yiladi.
        await gemini.emit({"type": "turn_complete"})
        await asyncio.sleep(0.35)

        assert gemini.directives, "jim qolgan o'quvchiga turtki yuborilmadi"
        nudge = gemini.directives[-1]
        assert nudge["tone"] == "slow_encouraging"
        assert "Do not answer for them" in nudge["text"]
        assert "do not give them a sentence to repeat" in nudge["text"]

        messages = []
        while True:
            try:
                messages.append(json.loads(await communicator.receive_from(timeout=0.2)))
            except Exception:  # noqa: BLE001 — navbat bo'shadi
                break
        assert not [m for m in messages if m["type"] == "options"], (
            "daraja aniqlashda tayyor javoblar ekranga chiqdi"
        )
    finally:
        with contextlib.suppress(asyncio.CancelledError):
            await communicator.disconnect()


# --- xulosa mantiqi (sof funksiya) --------------------------------------


def coach_turns(count, fluency, utterance="I work in a shop", *, correct=None):
    """Coach yozuvlari. `correct` — nechtasi to'g'ri (berilmasa: hammasi).

    Verdikt ham, ravonlik ham SHU ro'yxatdan o'qiladi — xulosa bitta manbadan
    chiqadi (§placement.outcome).
    """
    correct = count if correct is None else correct
    return [
        {
            "utterance": utterance,
            "fluency": fluency,
            "verdict": "correct" if i < correct else "incorrect",
        }
        for i in range(count)
    ]


def test_silence_is_not_a_low_level_it_is_no_measurement():
    """Ikki gapdan daraja chiqmaydi. Lekin qaror bir xil: boshidan."""
    result = placement.outcome(coach_turns(2, 3))
    assert result.reason == "not_enough_speech"
    assert result.register == adaptive.MIN_REGISTER
    assert result.back_to_start is True


def test_empty_utterances_do_not_count_as_turns():
    result = placement.outcome([{"utterance": "  ", "fluency": 4}] * 6)
    assert result.graded_turns == 0
    assert result.back_to_start is True


def test_a_fluent_accurate_learner_keeps_their_place():
    result = placement.outcome(coach_turns(6, 4))
    assert result.register == adaptive.MAX_REGISTER
    assert result.reason == "measured"
    assert result.back_to_start is False


def test_fragments_send_the_learner_back_to_the_start():
    result = placement.outcome(coach_turns(6, 1))
    assert result.register == 1
    assert result.reason == "low_register"
    assert result.back_to_start is True


def test_fluent_but_wrong_is_capped_and_sent_back():
    """Ravon gapirish tushunish demas — har gapi xato bo'lsa tezlik yordam bermaydi."""
    result = placement.outcome(coach_turns(8, 4, correct=0))
    assert result.register == placement.CAPPED_REGISTER
    assert result.reason == "many_mistakes"
    assert result.back_to_start is True


def test_the_accuracy_comes_from_the_same_records_as_the_fluency():
    """Ikkita manba bo'lsa ular zid kelishi mumkin — bitta manba, bitta haqiqat.

    Ilgari aniqlik `Evaluation` yozuvlaridan hisoblanardi. Coach oltita gapni
    baholab, `Evaluation` yozuvlari yetib kelmagan holatda aniqlik 0 chiqar va
    ravon gapirgan o'quvchi "ko'p xato qiladi" degan xulosa olardi.
    """
    all_right = placement.outcome(coach_turns(6, 4))
    assert all_right.accuracy == 1.0
    assert all_right.register == adaptive.MAX_REGISTER

    half = placement.outcome(coach_turns(6, 4, correct=3))
    assert half.accuracy == 0.5
    assert half.register == adaptive.MAX_REGISTER, "yarmi to'g'ri — hali chegara emas"


def test_short_complete_sentences_land_in_the_middle():
    result = placement.outcome(coach_turns(5, 2))
    assert result.register == 2
    assert result.back_to_start is False


# --- suhbat -> profil + progress (to'liq quvur) -------------------------


def finished_placement_session(user):
    topic = Topic.objects.get(track=TopicTrack.PLACEMENT)
    return Session.objects.create(
        user=user,
        topic=topic,
        mode=SessionMode.PLACEMENT,
        status=SessionStatus.PROCESSING,
        end_reason=EndReason.COMPLETED,
        started_at=timezone.now(),
        ended_at=timezone.now(),
        duration_seconds=240,
    )


def seed_placement_redis(fake_redis, session, coach_records):
    key = f"sess:{session.id}"
    for i, record in enumerate(coach_records, start=1):
        fake_redis.rpush(f"{key}:coach", json.dumps(record))
        fake_redis.rpush(
            f"{key}:turns",
            json.dumps(
                {
                    "idx": i,
                    "speaker": "learner",
                    "text": record.get("utterance") or "",
                    "started_at_ms": i * 1000,
                    "ended_at_ms": i * 1000 + 800,
                }
            ),
        )
    fake_redis.hset(
        f"{key}:meta",
        mapping={
            "mode": json.dumps(SessionMode.PLACEMENT.value),
            "learner_language": json.dumps("uz"),
        },
    )


@pytest.mark.django_db(transaction=True)
def test_a_weak_placement_sends_the_learner_to_the_first_topic(
    fake_redis, user, topic, topic2, placement_topic
):
    """Ikkinchi mavzu ochiq bo'lsa ham yopiladi — boshlang'ich qismga qaytariladi."""
    user.speaking_register = 4
    user.save(update_fields=["speaking_register"])
    TopicProgress.objects.create(user=user, topic=topic, status=TopicStatus.MASTERED)
    TopicProgress.objects.create(user=user, topic=topic2, status=TopicStatus.ACTIVE)

    session = finished_placement_session(user)
    seed_placement_redis(fake_redis, session, coach_turns(6, 1, "I from shop", correct=1))

    process_session.apply(args=[str(session.id)])

    user.refresh_from_db()
    assert user.placement_done is True
    assert user.speaking_register == 1
    assert TopicProgress.objects.get(user=user, topic=topic).status == TopicStatus.ACTIVE
    assert TopicProgress.objects.get(user=user, topic=topic2).status == TopicStatus.LOCKED


@pytest.mark.django_db(transaction=True)
def test_a_strong_placement_leaves_progress_alone(fake_redis, user, topic, topic2, placement_topic):
    TopicProgress.objects.create(user=user, topic=topic, status=TopicStatus.MASTERED)
    TopicProgress.objects.create(user=user, topic=topic2, status=TopicStatus.ACTIVE)

    session = finished_placement_session(user)
    seed_placement_redis(fake_redis, session, coach_turns(6, 4, "I work in a shop every day"))

    process_session.apply(args=[str(session.id)])

    user.refresh_from_db()
    assert user.placement_done is True
    assert user.speaking_register == adaptive.MAX_REGISTER
    assert TopicProgress.objects.get(user=user, topic=topic).status == TopicStatus.MASTERED
    assert TopicProgress.objects.get(user=user, topic=topic2).status == TopicStatus.ACTIVE


@pytest.mark.django_db(transaction=True)
def test_placement_writes_no_topic_progress_and_no_error_log(fake_redis, user, placement_topic):
    """Daraja aniqlash dars EMAS: u progressga ham, xato jurnaliga ham yozilmaydi."""
    from apps.progress.models import ErrorLog

    session = finished_placement_session(user)
    seed_placement_redis(fake_redis, session, coach_turns(6, 3))

    process_session.apply(args=[str(session.id)])

    assert not TopicProgress.objects.filter(user=user, topic=session.topic).exists()
    assert ErrorLog.objects.filter(user=user).count() == 0
