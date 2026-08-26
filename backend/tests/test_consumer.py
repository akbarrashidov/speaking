"""§5.1 / §7.2 — WS consumer: mock Gemini + ssenariylashtirilgan coach.

Faza 3 dan keyin Live modeli baholamaydi. O'quvchi javobi tugagach backend
`coach.evaluate` ni fon vazifasi sifatida chaqiradi, natijani `state.py` ga
beradi va faqat shundan keyin Live'ga `[DIRECTOR]` ko'rsatmasini yuboradi.
Shuning uchun bu testlar tool call emas, **direktivlarni** tekshiradi.
"""

import asyncio
import base64
import json

import pytest
from channels.db import database_sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator

from apps.practice import adaptive
from apps.practice import coach as coach_mod
from apps.practice import consumer as consumer_mod
from apps.practice.models import Session, SessionStatus
from apps.practice.routing import websocket_urlpatterns
from apps.practice.services import start_session
from apps.users.jwt_utils import issue_token
from conftest import coach_result

application = URLRouter(websocket_urlpatterns)


@database_sync_to_async
def questions_of(topic):
    """ORM'ga async testdan xavfsiz kirish."""
    return list(topic.questions.order_by("order"))


async def open_session(user, topic):
    payload = await database_sync_to_async(start_session)(user, topic.id)
    token, _ = await database_sync_to_async(issue_token)(user)
    communicator = WebsocketCommunicator(
        application, f"/ws/session/{payload['session_id']}/?token={token}"
    )
    connected, _ = await communicator.connect()
    assert connected
    return communicator, payload


async def drain_until(communicator, msg_type, limit=30):
    """Kerakli turdagi xabar kelguncha o'qiydi."""
    for _ in range(limit):
        message = json.loads(await communicator.receive_from(timeout=3))
        if message["type"] == msg_type:
            return message
    raise AssertionError(f"'{msg_type}' xabari kelmadi")


async def learner_says(communicator, gemini, text, *, ai_reply="Okay."):
    """O'quvchi gapiradi va jim bo'ladi.

    Ketma-ketlik haqiqiy client'niki: `speech_start` → transkript →
    `speech_end`. Navbatni `speech_end` yopadi (§5.1a): backend avval
    baholaydi va faqat shundan keyin modelga javob berishga ruxsat beradi.
    Shuning uchun modelning javobi shu yerda — baholashdan KEYIN — keladi.

    `speech_start` shart: faqat u yangi navbat ochadi. Navbat yopilgach kelgan
    transkript o'sha aytilgan gapning kechikkan nusxasi deb e'tiborsiz
    qoldiriladi (§_handle_gemini_event).
    """
    await communicator.send_to(text_data=json.dumps({"type": "speech_start"}))
    await asyncio.sleep(0.05)
    await gemini.emit({"type": "input_transcript", "text": text})
    await communicator.send_to(text_data=json.dumps({"type": "speech_end"}))
    await asyncio.sleep(0.2)  # baholash quvuri tugashini kutamiz
    if ai_reply:
        await gemini.emit({"type": "output_transcript", "text": ai_reply})
        await asyncio.sleep(0.05)


def last_directive(gemini) -> str:
    assert gemini.directives, "Live'ga hech qanday direktiv yuborilmadi"
    return gemini.directives[-1]["text"]


# --- auth -----------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_connection_without_token_is_rejected(fake_gemini, user, topic):
    payload = await database_sync_to_async(start_session)(user, topic.id)
    communicator = WebsocketCommunicator(application, f"/ws/session/{payload['session_id']}/")
    connected, code = await communicator.connect()
    assert connected is False
    assert code == consumer_mod.CLOSE_UNAUTHORIZED


@pytest.mark.django_db(transaction=True)
async def test_other_users_session_is_forbidden(fake_gemini, user, topic):
    from apps.users.models import User

    payload = await database_sync_to_async(start_session)(user, topic.id)
    stranger = await database_sync_to_async(User.objects.create_user)(
        email="stranger-ws@example.com"
    )
    token, _ = await database_sync_to_async(issue_token)(stranger)

    communicator = WebsocketCommunicator(
        application, f"/ws/session/{payload['session_id']}/?token={token}"
    )
    connected, code = await communicator.connect()
    assert connected is False
    assert code == consumer_mod.CLOSE_FORBIDDEN


# --- asosiy oqim ----------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_first_question_is_pushed_to_the_model(fake_gemini, user, topic):
    communicator, _ = await open_session(user, topic)
    await drain_until(communicator, "session_ready")

    gemini = fake_gemini.instances[-1]
    first_question = (await questions_of(topic))[0]

    assert len(gemini.sent_text) == 1
    assert first_question.question_text in gemini.sent_text[0]
    # Savollar ro'yxati promptga kirmaydi (§5.2.3) — faqat bittasi beriladi.
    assert first_question.question_text not in gemini.system_prompt

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_correct_answer_advances_to_next_question(fake_gemini, fake_coach, user, topic):
    communicator, _ = await open_session(user, topic)
    await drain_until(communicator, "session_ready")

    gemini = fake_gemini.instances[-1]
    questions = await questions_of(topic)

    fake_coach.scripted.append(coach_result("correct", reaction="Nice one!"))
    await learner_says(communicator, gemini, "I work in a bank")

    directive = last_directive(gemini)
    assert questions[1].question_text in directive
    # Coach yozgan reaksiya direktivga tushadi — suhbat quruq bo'lmasin.
    assert "Nice one!" in directive

    progress = await drain_until(communicator, "progress")
    assert progress["correct"] == 1

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_full_retry_then_model_answer_sequence(fake_gemini, fake_coach, user, topic):
    """§4.4 ning to'liq shoxobchasi — endi coach verdiktlari bilan."""
    communicator, _ = await open_session(user, topic)
    await drain_until(communicator, "session_ready")

    gemini = fake_gemini.instances[-1]
    questions = await questions_of(topic)

    fake_coach.scripted.append(coach_result("incorrect", error_type="wrong_tense"))
    await learner_says(communicator, gemini, "I go yesterday")
    assert "Do not give the answer" in last_directive(gemini)
    assert questions[0].question_text in last_directive(gemini)

    fake_coach.scripted.append(
        coach_result(
            "incorrect",
            error_type="wrong_tense",
            model_answer="I went to work yesterday.",
        )
    )
    await learner_says(communicator, gemini, "I go yesterday again")
    directive = last_directive(gemini)
    assert "Repeat after me" in directive
    # Coach o'quvchining O'Z gapini tuzatadi — quruq etalon emas.
    assert "I went to work yesterday." in directive

    fake_coach.scripted.append(coach_result("correct"))
    await learner_says(communicator, gemini, "I went to work yesterday")
    assert questions[1].question_text in last_directive(gemini)

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_model_answer_falls_back_to_the_canonical_answer(
    fake_gemini, fake_coach, user, topic
):
    """Coach gapni tiklay olmasa — DB'dagi etalon javob ishlatiladi (§4.4)."""
    communicator, _ = await open_session(user, topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]
    questions = await questions_of(topic)

    for _ in range(2):
        fake_coach.scripted.append(coach_result("incorrect", model_answer=""))
        await learner_says(communicator, gemini, "mmm")

    assert questions[0].canonical_answer in last_directive(gemini)

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_unintelligible_gets_clarify_signal(fake_gemini, fake_coach, user, topic):
    communicator, _ = await open_session(user, topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    fake_coach.scripted.append(coach_result("unintelligible"))
    await learner_says(communicator, gemini, "mmm hrrm")

    assert "say that again" in last_directive(gemini)
    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_backend_owns_the_question_id(fake_gemini, fake_coach, user, topic):
    """Coach savol tanlamaydi — u qaysi savol berilganini ham bilmaydi.

    Ilgari model tool call'da `question_id` yuborar va oldinga sakrashga
    urinardi. Endi bunday sinf muammosi umuman yo'q: navbatdagi savolni
    faqat `state.py` biladi.
    """
    from apps.practice.store import SyncSessionStore

    communicator, payload = await open_session(user, topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]
    questions = await questions_of(topic)

    fake_coach.scripted.append(coach_result("correct"))
    await learner_says(communicator, gemini, "I work in a bank")

    evaluations = SyncSessionStore(payload["session_id"]).get_evaluations()
    assert [e["question_id"] for e in evaluations] == [questions[0].id]

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_coach_failure_does_not_stop_the_session(fake_gemini, fake_coach, user, topic):
    """LLM yiqilsa ham suhbat deterministik mantiq bilan davom etadi."""
    communicator, _ = await open_session(user, topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    fake_coach.scripted.append(coach_mod.fallback("Timeout"))
    await learner_says(communicator, gemini, "I work in a bank")

    # Fallback verdikti `unintelligible` — clarify tarmog'i ishlaydi.
    assert "say that again" in last_directive(gemini)
    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_coach_call_budget_is_enforced(fake_gemini, fake_coach, user, topic, settings):
    """Narx tomi: chegaradan keyin coach jim bo'ladi, sessiya buzilmaydi."""
    settings.COACH_MAX_CALLS = 1
    communicator, _ = await open_session(user, topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    await learner_says(communicator, gemini, "first answer")
    await learner_says(communicator, gemini, "second answer")

    assert len(fake_coach.calls) == 1
    await communicator.disconnect()


# --- dinamik savollar (§Faza 5) -------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_guided_mode_uses_the_coach_follow_up(fake_gemini, fake_coach, user, b1_topic):
    """Suhbat rejimida ko'prik savol har safar coach tomonidan yoziladi."""
    from apps.progress.models import TopicProgress, TopicStatus

    await database_sync_to_async(TopicProgress.objects.create)(
        user=user, topic=b1_topic, status=TopicStatus.ACTIVE
    )
    communicator, _ = await open_session(user, b1_topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    fake_coach.scripted.append(
        coach_result("correct", next_question="What do you usually do after work?")
    )
    await learner_says(communicator, gemini, "I work in a bank every day")

    assert "What do you usually do after work?" in last_directive(gemini)
    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_invalid_generated_question_is_dropped(fake_gemini, fake_coach, user, b1_topic):
    """Tekshiruvdan o'tmagan savol aytilmaydi — bank savoliga qaytiladi."""
    from apps.progress.models import TopicProgress, TopicStatus

    await database_sync_to_async(TopicProgress.objects.create)(
        user=user, topic=b1_topic, status=TopicStatus.ACTIVE
    )
    communicator, _ = await open_session(user, b1_topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    # Yes/no savoli — to'liq gapli javobni majburlamaydi.
    fake_coach.scripted.append(coach_result("correct", next_question="Do you like it?"))
    await learner_says(communicator, gemini, "I work in a bank every day")

    directive = last_directive(gemini)
    assert "Do you like it?" not in directive
    assert "improvised follow-up" in directive
    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_drill_mode_keeps_its_rhythm_until_the_structure_is_missed(
    fake_gemini, fake_coach, user, topic
):
    """Drill — takrorlash mashqi; struktura ishlatilayotgan ekan aralashmaymiz."""
    communicator, _ = await open_session(user, topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    fake_coach.scripted.append(
        coach_result("correct", next_question="What do you usually do at home?")
    )
    await learner_says(communicator, gemini, "I work every day")
    assert "What do you usually do at home?" not in last_directive(gemini)

    # Ikki marta ketma-ket struktura ishlatilmadi — endi majburlaymiz.
    for _ in range(2):
        fake_coach.scripted.append(
            coach_result(
                "correct",
                target_structure_used=False,
                next_question="What do you usually do at home?",
            )
        )
        await learner_says(communicator, gemini, "shop")

    assert "What do you usually do at home?" in last_directive(gemini)
    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_accepted_generated_question_grows_the_bank(fake_gemini, fake_coach, user, b1_topic):
    """Sifatli savol qoralama bo'lib bankka qaytadi — admin review'ga tushadi."""
    from apps.content.models import Question, QuestionSource, QuestionStatus
    from apps.progress.models import TopicProgress, TopicStatus

    await database_sync_to_async(TopicProgress.objects.create)(
        user=user, topic=b1_topic, status=TopicStatus.ACTIVE
    )
    communicator, _ = await open_session(user, b1_topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    fake_coach.scripted.append(
        coach_result("correct", next_question="What do you usually do after work?")
    )
    await learner_says(communicator, gemini, "I work in a bank every day")

    @database_sync_to_async
    def saved():
        return list(
            Question.objects.filter(
                topic=b1_topic,
                source=QuestionSource.GENERATED,
                status=QuestionStatus.DRAFT,
            ).values_list("question_text", flat=True)
        )

    assert await saved() == ["What do you usually do after work?"]
    await communicator.disconnect()


# --- erkin suhbat (adaptive_conversation) ---------------------------------


@pytest.mark.django_db(transaction=True)
async def test_adaptive_mode_does_not_push_a_first_question(fake_gemini, user, adaptive_topic):
    """Savollar promptdagi GOALS ro'yxatida — bittalab berilmaydi."""
    communicator, _ = await open_session(user, adaptive_topic)
    await drain_until(communicator, "session_ready")

    gemini = fake_gemini.instances[-1]
    first_question = (await questions_of(adaptive_topic))[0]

    assert gemini.sent_text == ["SESSION_START. Follow your FLOW instruction."]
    # Ammo savollar system promptda GOALS bo'lib turibdi — aksincha, drill rejimi.
    assert first_question.question_text in gemini.system_prompt
    assert "SESSION GOALS" in gemini.system_prompt

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_adaptive_mode_sends_corrections_to_the_screen(
    fake_gemini, fake_coach, user, adaptive_topic
):
    """Coach natijasi ekranga diff bo'lib chiqadi."""
    communicator, _ = await open_session(user, adaptive_topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    fake_coach.scripted.append(coach_result("incorrect", error_type="wrong_tense", fluency=2))
    await learner_says(communicator, gemini, "I go yesterday")

    correction = await drain_until(communicator, "correction")
    assert correction["verdict"] == "incorrect"
    assert correction["fluency"] == 2
    assert correction["errors"] == [
        {"span": "x", "fix": "y", "type": "wrong_tense", "severity": "medium"}
    ]
    assert len(fake_coach.calls) == 1

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_an_ordinary_slip_is_echoed_without_stopping_the_conversation(
    fake_gemini, fake_coach, user, adaptive_topic, hold_turn
):
    """Kichik xato ham ovozda tuzatiladi — lekin suhbat to'xtamaydi.

    Gapirish platformasida aytilmagan xato yillar davomida qoladi, shuning
    uchun artikl ham eshitilishi kerak. Ammo har kichik sirpanishda to'xtab
    "qayta ayting" desa, bu suhbat emas, mashq bo'lib qoladi.
    """
    communicator, _ = await open_session(user, adaptive_topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    fake_coach.scripted.append(
        coach_result(
            "correct",
            error_type="missing_article",
            target_structure_used=True,
            model_answer="I went to the bazaar.",
        )
    )
    await learner_says(communicator, gemini, "I went to bazaar")

    await drain_until(communicator, "correction")

    directive = last_directive(gemini)
    assert "I went to the bazaar." in directive
    assert "carry on with the conversation" in directive
    assert "Now you say it." not in directive
    assert "do not ask them to repeat" in directive
    # Qaysi so'z buzilgani modelga aniq beriladi — "nimasi xato edi?" savoli
    # javobsiz qolmasin (§correction_policy.md).
    assert 'they said "x" where it should be "y"' in directive
    assert "name the wrong or missing word" in directive

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_missing_the_lessons_own_structure_is_said_out_loud(
    fake_gemini, fake_coach, user, adaptive_topic, hold_turn
):
    """ "I from" — ekrandagi diff yetarli emas, o'quvchi gapirayotgan payt.

    Sessiya AYNAN o'rgatayotgan shakl buzilganda AI gapni to'g'ri shaklda,
    urg'u bilan qaytaradi va yana bir marta aytishni so'raydi. Ekrandagi
    tuzatish esa parallel ravishda baribir chiqadi.
    """
    communicator, _ = await open_session(user, adaptive_topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    fake_coach.scripted.append(
        coach_result(
            "incorrect",
            error_type="missing_auxiliary",
            target_structure_used=False,
            model_answer="I am from Uzbekistan.",
        )
    )
    await learner_says(communicator, gemini, "I from Uzbekistan")

    # Ekran kanali.
    correction = await drain_until(communicator, "correction")
    assert correction["errors"][0]["type"] == "missing_auxiliary"

    # Ovoz kanali — parallel, bir xil navbat uchun.
    directive = last_directive(gemini)
    assert "I am from Uzbekistan." in directive
    assert "stressing what you fixed" in directive
    assert "Now you say it." in directive
    # Xato AYTILADI: o'quvchi qaysi so'z buzilganini eshitishi kerak.
    assert "which word was wrong or missing" in directive
    # ...lekin grammatika darsi emas — qoida nomlanmaydi.
    assert "never use grammar words" in directive

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_a_repeated_miss_escalates_to_saying_it_together(
    fake_gemini, fake_coach, user, adaptive_topic, hold_turn
):
    """Ketma-ket uchinchi marta — shama yetarli emas, birga aytiladi."""
    communicator, _ = await open_session(user, adaptive_topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    for _ in range(3):
        fake_coach.scripted.append(
            coach_result(
                "incorrect",
                error_type="missing_auxiliary",
                target_structure_used=False,
                model_answer="I am from Uzbekistan.",
            )
        )
        await learner_says(communicator, gemini, "I from Uzbekistan")

    directive = last_directive(gemini)
    assert "Say it with me." in directive
    assert "I am from Uzbekistan." in directive

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_adaptive_correction_is_bound_to_the_learner_turn(
    fake_gemini, fake_coach, user, adaptive_topic
):
    """Tuzatish kechikib keladi — u aynan o'sha gapga `turn_idx` bilan bog'lanadi."""
    communicator, _ = await open_session(user, adaptive_topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    fake_coach.scripted.append(coach_result("incorrect", error_type="word_order"))
    await gemini.emit({"type": "input_transcript", "text": "Yesterday I go bazaar"})
    await gemini.emit({"type": "output_transcript", "text": "Nice."})
    await asyncio.sleep(0.15)

    learner_turn = None
    for _ in range(30):
        message = json.loads(await communicator.receive_from(timeout=3))
        if message["type"] == "transcript" and message["final"] and message["speaker"] == "learner":
            learner_turn = message
        if message["type"] == "correction":
            assert learner_turn is not None, "tuzatish gapdan oldin keldi"
            assert message["turn_idx"] == learner_turn["idx"]
            break
    else:
        raise AssertionError("'correction' xabari kelmadi")

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_adaptive_clean_answer_still_reports_a_correction(
    fake_gemini, fake_coach, user, adaptive_topic
):
    """Xatosiz javob ham yuboriladi — frontend "toza" belgisini ko'rsatadi."""
    communicator, _ = await open_session(user, adaptive_topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    fake_coach.scripted.append(coach_result("correct"))
    await learner_says(communicator, gemini, "Yesterday I went to the bazaar")

    correction = await drain_until(communicator, "correction")
    assert correction["errors"] == []
    assert correction["verdict"] == "correct"

    await communicator.disconnect()


async def learner_speaks(communicator, text_chunks, gemini, *, pause=0.05):
    """Client VAD ssenariysi: `speech_start` → transkript → `speech_end`."""
    await communicator.send_to(text_data=json.dumps({"type": "speech_start"}))
    await asyncio.sleep(0.05)
    for chunk in text_chunks:
        await gemini.emit({"type": "input_transcript", "text": chunk})
    await communicator.send_to(text_data=json.dumps({"type": "speech_end"}))
    await asyncio.sleep(pause)


@pytest.mark.django_db(transaction=True)
async def test_a_mid_sentence_pause_does_not_split_the_turn(
    fake_gemini, fake_coach, user, adaptive_topic, monkeypatch
):
    """Gap o'rtasidagi pauza bitta navbatni ikkiga bo'lib yubormaydi.

    Client VAD 700 ms jimlikda `speech_end` beradi, o'quvchi esa gap o'rtasida
    undan uzoq o'ylanadi. Bo'linib ketsa yarim gap baholanadi, model javob bera
    boshlaydi, ikkinchi yarmining tuzatishi esa keyingi navbatga suriladi.
    """
    monkeypatch.setattr(consumer_mod, "TURN_END_GRACE_SECONDS", 0.3)

    communicator, _ = await open_session(user, adaptive_topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    # Birinchi bo'lak — va oyna ichidagi pauza.
    await learner_speaks(communicator, ["I went to the bazaar"], gemini, pause=0.1)
    # Davomi: yopish bekor qilinadi, gap o'sha navbatda qoladi.
    await learner_speaks(communicator, [" with my mother"], gemini, pause=0.5)

    assert len(fake_coach.calls) == 1, "bitta gap ikki marta baholandi"
    assert fake_coach.calls[0].learner_utterance == "I went to the bazaar with my mother"
    # Ochiq turgan oynaga ikkinchi `activityStart` yuborilmaydi.
    assert gemini.activity_starts == 1

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_a_late_live_transcript_does_not_repeat_the_sentence(
    fake_gemini, fake_coach, user, adaptive_topic
):
    """Gemini 3.1 Live kirish transkriptini navbat YAKUNIDA yuboradi.

    Ya'ni u gap ekranga chiqib bo'lgandan keyin keladi. Qabul qilinsa, o'sha
    gap ikkinchi marta ekranga chiqadi va yangi navbat ochib, ikkinchi marta
    baholanadi — o'quvchi o'z gapini ikki marta ko'radi.
    """
    communicator, _ = await open_session(user, adaptive_topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    fake_coach.scripted.append(coach_result("correct"))
    await learner_says(communicator, gemini, "I am a programmer", ai_reply="")
    await drain_until(communicator, "progress")

    # Live o'sha gapni endi yubordi — navbat allaqachon yopilgan.
    await gemini.emit({"type": "input_transcript", "text": "I am a programmer"})
    await asyncio.sleep(0.2)

    assert len(fake_coach.calls) == 1, "kechikkan nusxa ikkinchi marta baholandi"
    assert await communicator.receive_nothing(timeout=0.2), "kechikkan nusxa ekranga chiqdi"

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_a_short_burst_waits_for_the_rest_of_the_sentence(
    fake_gemini, fake_coach, user, adaptive_topic, monkeypatch
):
    """Qisqa bo'lak — tugallangan javob emas, gap o'rtasidagi pauza.

    Busiz bitta gap "bedroom bedroom" / "dining room and" bo'lib bir nechta
    navbatga bo'linadi va har bo'lagi alohida baholanib, alohida qator bo'lib
    ekranga chiqadi.
    """
    from apps.practice import asr

    async def no_verbatim(pcm, target_structure=""):
        return "", {}

    monkeypatch.setattr(asr, "transcribe", no_verbatim)
    monkeypatch.setattr(consumer_mod, "SHORT_UTTERANCE_EXTRA_GRACE", 0.4)

    communicator, _ = await open_session(user, adaptive_topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    # 0.5 s nutq — qisqa bo'lak.
    chunk = base64.b64encode(b"\x00\x40" * 4000).decode()
    await communicator.send_to(text_data=json.dumps({"type": "speech_start"}))
    await communicator.send_to(text_data=json.dumps({"type": "audio_chunk", "data": chunk}))
    await gemini.emit({"type": "input_transcript", "text": "I went to the bazaar"})
    await communicator.send_to(text_data=json.dumps({"type": "speech_end"}))
    await asyncio.sleep(0.15)  # qo'shimcha oyna ichida

    # O'quvchi gapida davom etdi.
    await communicator.send_to(text_data=json.dumps({"type": "speech_start"}))
    await gemini.emit({"type": "input_transcript", "text": " with my mother"})
    await communicator.send_to(text_data=json.dumps({"type": "speech_end"}))
    await asyncio.sleep(0.8)

    assert len(fake_coach.calls) == 1, "bitta gap bir necha marta baholandi"
    assert fake_coach.calls[0].learner_utterance == "I went to the bazaar with my mother"

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_speech_after_the_turn_closed_opens_a_fresh_live_window(
    fake_gemini, fake_coach, user, adaptive_topic, monkeypatch
):
    """Oyna yopilgach kelgan gap YANGI navbat bo'ladi — yutilib ketmaydi.

    Kuzatilgan xatti-harakat: o'quvchi "gapimni to'liq eshitmadi" deydi.
    Sababi shu yerda edi. `speech_start` `_turn_handled` ni tushirar, lekin
    `_activity_open` True bo'lib qolardi — ya'ni Live'ga `activityStart`
    YUBORILMASDI. Gapning davomi hech qaysi ochiq oynaga tushmay, modelga
    umuman yetib bormasdi.
    """
    from apps.practice import asr

    async def no_verbatim(pcm, target_structure=""):
        return "", {}

    monkeypatch.setattr(asr, "transcribe", no_verbatim)

    communicator, _ = await open_session(user, adaptive_topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    chunk = base64.b64encode(bytes([0, 64]) * 16000).decode()  # 2 s nutq

    # Birinchi navbat: oyna 0 (conftest), ya'ni `speech_end` uni darhol yopadi.
    await communicator.send_to(text_data=json.dumps({"type": "speech_start"}))
    await asyncio.sleep(0.05)
    await communicator.send_to(text_data=json.dumps({"type": "audio_chunk", "data": chunk}))
    await gemini.emit({"type": "input_transcript", "text": "I went to the bazaar"})
    await communicator.send_to(text_data=json.dumps({"type": "speech_end"}))
    await asyncio.sleep(0.4)
    assert gemini.activity_starts == 1

    # Oyna yopilgandan KEYIN o'quvchi yana gapiradi.
    await communicator.send_to(text_data=json.dumps({"type": "speech_start"}))
    await asyncio.sleep(0.05)
    await communicator.send_to(text_data=json.dumps({"type": "audio_chunk", "data": chunk}))
    await gemini.emit({"type": "input_transcript", "text": "with my mother"})
    await communicator.send_to(text_data=json.dumps({"type": "speech_end"}))
    await asyncio.sleep(0.4)

    assert gemini.activity_starts == 2, "ikkinchi gapga Live'da oyna ochilmadi"
    assert len(fake_coach.calls) == 2, "ikkinchi gap baholanmadi"

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_an_already_answered_question_is_not_graded_against_again(
    fake_gemini, fake_coach, user, adaptive_topic
):
    """AI savoli javob olgach, keyingi gap unga javob deb baholanmaydi.

    Kuzatilgan xatti-harakat: o'quvchi "My name is Akbar." dedi, keyin O'ZI
    "What is your name?" deb so'radi — coach esa uni o'sha eski
    "What is your name?" savoliga berilgan javob deb olib, "sizga 'My name is'
    kerak" deb tuzatdi. Savolni qaytarib so'rash — suhbatning o'zi, xato emas.
    """
    communicator, _ = await open_session(user, adaptive_topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    # AI savol berdi va navbatini yakunladi.
    await gemini.emit({"type": "output_transcript", "text": "What is your name?"})
    await gemini.emit({"type": "turn_complete"})
    await asyncio.sleep(0.1)

    await learner_says(communicator, gemini, "My name is Akbar", ai_reply="")
    assert fake_coach.calls[-1].question_text == "What is your name?"

    # Savol allaqachon javob oldi — endi o'quvchi O'ZI so'raydi.
    await learner_says(communicator, gemini, "What is your name?", ai_reply="")

    assert len(fake_coach.calls) == 2
    assert fake_coach.calls[-1].question_text == "", (
        "javob olingan savol keyingi gapga yana etalon bo'lib berildi"
    )

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_one_turn_opens_exactly_one_generation(
    fake_gemini, fake_coach, user, adaptive_topic, monkeypatch, hold_turn
):
    """Bitta navbat — bitta javob. Ko'rsatma navbat ichida javob ochmaydi.

    Kuzatilgan xatti-harakat: model bir vaqtda ikkita matn generatsiya qilardi.
    Navbat ichida ko'rsatma `activityEnd` bilan BIRGA javob ochsa, server
    bitta navbatga ikkita generatsiya boshlaydi. Shuning uchun navbat ichidagi
    ko'rsatma faqat kontekst: javobni yolg'iz `activityEnd` ochadi.

    Bu zaxira yo'l (`hold_turn`) — u yerda ko'rsatma hamon bor. Odatiy yo'lda
    ko'rsatma umuman yuborilmaydi (quyidagi testga qarang).
    """
    from apps.practice import asr

    async def no_verbatim(pcm, target_structure=""):
        return "", {}

    monkeypatch.setattr(asr, "transcribe", no_verbatim)

    communicator, _ = await open_session(user, adaptive_topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    fake_coach.scripted.append(coach_result("correct"))
    chunk = base64.b64encode(bytes([0, 64]) * 16000).decode()  # 2 s nutq
    await communicator.send_to(text_data=json.dumps({"type": "speech_start"}))
    await asyncio.sleep(0.05)
    await communicator.send_to(text_data=json.dumps({"type": "audio_chunk", "data": chunk}))
    await gemini.emit({"type": "input_transcript", "text": "I am from Uzbekistan"})
    await communicator.send_to(text_data=json.dumps({"type": "speech_end"}))
    await asyncio.sleep(0.4)

    assert gemini.directives, "navbat ko'rsatmasi yuborilmadi"
    assert gemini.directives[-1]["in_turn"] is True
    assert gemini.activity_ends == 1, "bitta navbatga bitta activityEnd"

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_a_live_first_turn_does_not_wait_for_the_coach(
    fake_gemini, fake_coach, user, adaptive_topic, monkeypatch
):
    """Erkin suhbatda navbat baholashni KUTMAYDI (§LIVE_FIRST_ENABLED).

    Model xatoni o'z qulog'i bilan topadi (§prompts/self_correction.md), ya'ni
    ovozga hech qanday ko'rsatma ketmaydi. Coach fonda ishlaydi va uning
    natijasi faqat EKRANGA — o'sha navbat raqamiga bog'lanib — chiqadi.
    """
    from apps.practice import asr

    heard = asyncio.Event()

    async def slow_verbatim(pcm, target_structure=""):
        heard.set()
        await asyncio.sleep(0.5)  # coach sekin — navbat bunga qaramaydi
        return "I from Uzbekistan", {}

    monkeypatch.setattr(asr, "transcribe", slow_verbatim)

    communicator, _ = await open_session(user, adaptive_topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    fake_coach.scripted.append(coach_result("incorrect", error_type="missing_auxiliary"))
    chunk = base64.b64encode(bytes([0, 64]) * 16000).decode()  # 2 s nutq
    await communicator.send_to(text_data=json.dumps({"type": "speech_start"}))
    await asyncio.sleep(0.05)
    await communicator.send_to(text_data=json.dumps({"type": "audio_chunk", "data": chunk}))
    await communicator.send_to(text_data=json.dumps({"type": "speech_end"}))

    # Baholash hali ketmoqda, navbat esa allaqachon modelga ochilgan.
    await asyncio.wait_for(heard.wait(), timeout=2)
    assert gemini.activity_ends == 1, "model javob berishga qo'yilmadi"
    assert gemini.directives == [], "erkin suhbatda ovozga ko'rsatma ketdi"

    # Tuzatish kechikib, lekin yetib keladi — va gap ham ekranda o'sha raqamda.
    correction = await drain_until(communicator, "correction")
    assert correction["errors"][0]["type"] == "missing_auxiliary"
    assert correction["turn_idx"] > 0
    assert gemini.directives == []

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_geminis_transcript_fills_the_screen_before_the_verbatim_arrives(
    fake_gemini, fake_coach, user, adaptive_topic, monkeypatch
):
    """Gap ekranda darhol turadi, keyin so'zma-so'z matn bilan almashtiriladi.

    Live-first yo'lida navbat baholashni kutmaydi, ya'ni so'zma-so'z matn
    1.5-2.5 s keyin keladi. O'sha vaqt o'quvchi o'z gapini ko'rmay turmasligi
    kerak — Gemini transkripti o'sha bo'shliqni to'ldiradi.

    Lekin u YAKUNIY emas: Live "I from Uzbekistan" ni jimgina "I'm from
    Uzbekistan" qilib beradi, tuzatish diffi esa aytilgan so'zga qo'yiladi.
    Shuning uchun so'zma-so'z matn kelgach o'sha qator almashtiriladi.
    """
    from apps.practice import asr

    async def slow_verbatim(pcm, target_structure=""):
        await asyncio.sleep(0.3)
        return "I from Uzbekistan", {}

    monkeypatch.setattr(asr, "transcribe", slow_verbatim)

    communicator, _ = await open_session(user, adaptive_topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    fake_coach.scripted.append(coach_result("incorrect", error_type="missing_auxiliary"))
    chunk = base64.b64encode(bytes([0, 64]) * 16000).decode()  # 2 s nutq
    await communicator.send_to(text_data=json.dumps({"type": "speech_start"}))
    await asyncio.sleep(0.05)
    await communicator.send_to(text_data=json.dumps({"type": "audio_chunk", "data": chunk}))
    await communicator.send_to(text_data=json.dumps({"type": "speech_end"}))
    await asyncio.sleep(0.05)

    # Navbat yopilgan, baholash ketmoqda — Gemini transkripti endi keldi.
    await gemini.emit({"type": "input_transcript", "text": "I'm from"})
    await gemini.emit({"type": "input_transcript", "text": " Uzbekistan"})

    # Har bo'lakda matn o'sib boradi — bir xil `idx` da, ya'ni qator
    # almashtiriladi, yangisi qo'shilmaydi.
    first = await drain_until(communicator, "transcript")
    assert first["final"] is True
    assert first["speaker"] == "learner"
    assert first["text"] == "I'm from"
    idx = first["idx"]

    grown = await drain_until(communicator, "transcript")
    assert grown["text"] == "I'm from Uzbekistan"
    assert grown["idx"] == idx

    # So'zma-so'z matn keldi — O'SHA qator almashtiriladi, yangisi qo'shilmaydi.
    while True:
        message = json.loads(await communicator.receive_from(timeout=3))
        if message["type"] == "transcript" and message["text"] == "I from Uzbekistan":
            break
    assert message["idx"] == idx, "so'zma-so'z matn yangi qator bo'lib qo'shildi"

    # Diff aynan o'sha qatorga bog'lanadi.
    correction = await drain_until(communicator, "correction")
    assert correction["turn_idx"] == idx

    # Kechikkan transkript navbat ham ochmaydi, ikkinchi marta ham baholanmaydi.
    assert len(fake_coach.calls) == 1

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_a_directive_outside_a_turn_opens_its_own_generation(
    fake_gemini, fake_coach, user, adaptive_topic, monkeypatch
):
    """Jimlik turtkisida ochiq navbat yo'q — ko'rsatma javobni O'ZI ochishi kerak.

    Aks holda u kontekstda osilib qoladi va KEYINGI navbatning javobiga
    qo'shilib chiqadi: model bitta generatsiyada ikkita ishni bajarib, o'quvchi
    bir vaqtda ikkita matn oladi.
    """
    from apps.practice import hints

    monkeypatch.setattr(hints, "SILENCE_SECONDS", {adaptive.DEFAULT_REGISTER: 0.05})
    communicator, _ = await open_session(user, adaptive_topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    await gemini.emit({"type": "turn_complete"})  # navbat o'quvchida — taymer qo'yiladi
    await asyncio.sleep(0.35)

    assert gemini.directives, "jimlikdan keyin turtki yuborilmadi"
    assert all(d["in_turn"] is False for d in gemini.directives)

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_a_late_correction_is_not_spoken_after_the_model_has_moved_on(
    fake_gemini, user, adaptive_topic, monkeypatch
):
    """Kechikkan tuzatish navbatga qo'yilmaydi — u endi faqat ekranda qoladi.

    Baholash model gapirib turganda tugasa, direktiv navbat oxirida uzatilardi:
    o'quvchi avval keyingi savolni, keyin esa o'tib ketgan gapining tuzatishini
    eshitardi. Bu suhbat emas, kechikkan hisobot.
    """
    communicator, _ = await open_session(user, adaptive_topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    async def evaluate_while_the_model_speaks(ctx):
        # Baholash tugagunicha model allaqachon gapira boshladi.
        await gemini.emit({"type": "audio", "data": "AAAA"})
        return coach_result(
            "incorrect",
            error_type="missing_auxiliary",
            target_structure_used=False,
            model_answer="I am from Uzbekistan.",
        )

    monkeypatch.setattr(consumer_mod.coach, "evaluate", evaluate_while_the_model_speaks)

    await learner_speaks(communicator, ["I from Uzbekistan"], gemini, pause=0.3)

    # Ekran kanali baribir ishlaydi — xato yo'qolmaydi.
    correction = await drain_until(communicator, "correction")
    assert correction["errors"][0]["type"] == "missing_auxiliary"

    # Navbat yakunlandi: kechikkan tuzatish endi ovozga chiqmaydi.
    await gemini.emit({"type": "turn_complete"})
    await asyncio.sleep(0.1)
    assert all("I am from Uzbekistan." not in d["text"] for d in gemini.directives)

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_adaptive_silence_asks_a_simpler_question_instead_of_the_hint_ladder(
    fake_gemini, fake_coach, user, adaptive_topic, monkeypatch
):
    """Podkaska zinapoyasi o'chirilgan: model javobni hech qachon aytib bermaydi."""
    from apps.practice import hints

    monkeypatch.setattr(hints, "SILENCE_SECONDS", {adaptive.DEFAULT_REGISTER: 0.05})
    communicator, _ = await open_session(user, adaptive_topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    await gemini.emit({"type": "turn_complete"})  # navbat o'quvchida — taymer qo'yiladi
    await asyncio.sleep(0.35)

    assert gemini.directives, "jimlikdan keyin turtki yuborilmadi"
    nudge = gemini.directives[-1]
    assert "simpler, more concrete version" in nudge["text"]
    assert "Do not answer for them" in nudge["text"]
    # Zinapoyaning eski 3-pog'onasi qaytmasligi kerak: takrorlash uchun gap
    # berilsa, o'quvchi o'z gapini emas, birovning gapini mashq qiladi.
    assert "do not give them a sentence to repeat" in nudge["text"]
    assert "Repeat after me" not in nudge["text"]
    assert nudge["tone"] == "slow_encouraging"
    # Zinapoyaning birinchi pog'onasi (savolni so'zma-so'z takrorlash) ham yo'q.
    assert not any("Take your time." in d["text"] for d in gemini.directives)

    # Turtki cheklovsiz takrorlanadi — MAX_STUCK bo'yicha savol yopilmaydi.
    assert len(gemini.directives) > 1
    assert all(d["text"] == nudge["text"] for d in gemini.directives)

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_the_coach_grades_what_was_said_not_what_live_cleaned_up(
    fake_gemini, fake_coach, user, adaptive_topic, monkeypatch
):
    """Eng muhim da'vo: grammatika baholashi so'zma-so'z matn ustida bo'ladi.

    Gemini Live transkripti "I from Uzbekistan" ni jimgina "I'm from
    Uzbekistan." qilib beradi. Coach o'sha matnni ko'rsa, xato yo'q deb
    hisoblaydi va o'quvchi xatosini bilmay qoladi (§asr.py).
    """
    from apps.practice import asr

    async def fake_transcribe(pcm, target_structure=""):
        return "I from Uzbekistan", {"model": "test-asr", "in": 120, "out": 8}

    monkeypatch.setattr(asr, "transcribe", fake_transcribe)

    communicator, _ = await open_session(user, adaptive_topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    # O'quvchi gapiradi — audio backendga oqadi.
    # Amplituda ataylab baland: jimlik darvozasi (§asr.is_silence) buni nutq
    # deb qabul qilishi kerak, aks holda navbat umuman baholanmaydi.
    chunk = base64.b64encode(b"\x00\x20" * 16000).decode()
    await communicator.send_to(text_data=json.dumps({"type": "audio_chunk", "data": chunk}))
    await asyncio.sleep(0.05)

    fake_coach.scripted.append(coach_result("incorrect", error_type="missing_auxiliary"))
    await learner_says(communicator, gemini, "I'm from Uzbekistan.")

    assert fake_coach.calls[0].learner_utterance == "I from Uzbekistan"

    # Ekranda ham aynan aytilgani turadi — o'quvchi xatosini ko'rishi kerak.
    for _ in range(30):
        message = json.loads(await communicator.receive_from(timeout=3))
        if message["type"] == "transcript" and message.get("speaker") == "learner":
            if message["text"] == "I from Uzbekistan":
                break
    else:
        raise AssertionError("so'zma-so'z transkript ekranga yuborilmadi")

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_verbatim_transcript_falls_back_to_live_when_asr_is_silent(
    fake_gemini, fake_coach, user, adaptive_topic, monkeypatch
):
    """ASR yiqilsa sessiya to'xtamaydi — eski xatti-harakat qoladi."""
    from apps.practice import asr

    async def fake_transcribe(pcm, target_structure=""):
        return "", {}

    monkeypatch.setattr(asr, "transcribe", fake_transcribe)

    communicator, _ = await open_session(user, adaptive_topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    # Amplituda ataylab baland: jimlik darvozasi (§asr.is_silence) buni nutq
    # deb qabul qilishi kerak, aks holda navbat umuman baholanmaydi.
    chunk = base64.b64encode(b"\x00\x20" * 16000).decode()
    await communicator.send_to(text_data=json.dumps({"type": "audio_chunk", "data": chunk}))
    await asyncio.sleep(0.05)

    fake_coach.scripted.append(coach_result("correct"))
    await learner_says(communicator, gemini, "I'm from Uzbekistan.")

    assert fake_coach.calls[0].learner_utterance == "I'm from Uzbekistan."

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_ai_turns_get_an_uzbek_translation_on_screen(
    fake_gemini, user, adaptive_topic, monkeypatch
):
    """O'quvchi AI nima deganini tushunmasa suhbat behuda — tarjima ekranda."""
    from apps.practice import translate

    async def fake_translate(text, language=""):
        return f"[uz] {text}", {"model": "test-translate", "in": 40, "out": 30}

    monkeypatch.setattr(translate, "to_learner_language", fake_translate)

    communicator, _ = await open_session(user, adaptive_topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    await gemini.emit({"type": "output_transcript", "text": "Where do you work?"})
    await gemini.emit({"type": "turn_complete"})

    message = await drain_until(communicator, "translation")
    assert message["text_uz"] == "[uz] Where do you work?"
    # Tarjima gapga navbat raqami orqali bog'lanadi — u ovozdan keyin keladi.
    assert message["idx"] > 0

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_translation_budget_is_separate_from_the_coach_budget(
    fake_gemini, fake_coach, user, adaptive_topic, monkeypatch
):
    """Uzun sessiyada tarjima tuzatishlarni siqib chiqarmasligi kerak."""
    from apps.practice import translate
    from apps.practice.store import SyncSessionStore

    async def fake_translate(text, language=""):
        return "[uz]", {"model": "test-translate", "in": 40, "out": 30}

    monkeypatch.setattr(translate, "to_learner_language", fake_translate)

    communicator, payload = await open_session(user, adaptive_topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    fake_coach.scripted.append(coach_result("correct"))
    await learner_says(communicator, gemini, "I work in a bank")
    await gemini.emit({"type": "turn_complete"})
    await asyncio.sleep(0.15)

    kinds = [c.get("kind") for c in SyncSessionStore(payload["session_id"]).get_llm_calls()]
    assert sorted(kinds) == ["coach", "translate"]

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_a_stuck_learner_gets_answers_to_read_not_answers_to_repeat(
    fake_gemini, fake_coach, user, adaptive_topic, monkeypatch
):
    """§Faza 4 — ekranda 2-3 variant, ovozda esa javob AYTILMAYDI."""
    from apps.practice import hints

    monkeypatch.setattr(hints, "SILENCE_SECONDS", {adaptive.DEFAULT_REGISTER: 0.05})
    fake_coach.scripted.append(
        coach_result(
            "unintelligible",
            options=[
                {"en": "I went to the bazaar.", "uz": "Men bozorga bordim."},
                {"en": "I stayed at home.", "uz": "Men uyda qoldim."},
            ],
        )
    )

    communicator, _ = await open_session(user, adaptive_topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    await gemini.emit({"type": "turn_complete"})  # navbat o'quvchida — taymer qo'yiladi

    message = await drain_until(communicator, "options")
    assert [o["en"] for o in message["items"]] == [
        "I went to the bazaar.",
        "I stayed at home.",
    ]
    assert message["items"][0]["uz"] == "Men bozorga bordim."

    # Ovozda: dalda bor, javob yo'q.
    directive = last_directive(gemini)
    assert "do not read the options out loud" in directive
    assert "I went to the bazaar." not in directive
    assert "Repeat after me" not in directive

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_a_leaked_directive_never_reaches_the_learners_screen(
    fake_gemini, user, adaptive_topic
):
    """Model kontraktni buzsa ham (`base.md` — THE DIRECTOR) ekran toza qoladi.

    Real regressiya: `realtimeInput.text` orqali kelgan ko'rsatmani model
    o'quvchi gapi deb qabul qilib, ovoz chiqarib o'qib yubordi.
    """
    communicator, _ = await open_session(user, adaptive_topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    await gemini.emit({"type": "output_transcript", "text": '[DIRECTOR] Say, "Okay." '})
    await gemini.emit({"type": "output_transcript", "text": 'Then ask, "Where are you from?" '})
    await gemini.emit(
        {"type": "output_transcript", "text": "word for word. Okay. Where are you from?"}
    )
    await gemini.emit({"type": "turn_complete"})

    final = await drain_until(communicator, "transcript")
    assert final["final"] is True, "sizib chiqqan bo'lak ekranga oqib o'tdi"
    assert final["text"] == "Okay. Where are you from?"
    assert "DIRECTOR" not in final["text"]

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_adaptive_level_change_waits_for_the_model_to_finish_speaking(
    fake_gemini, fake_coach, user, adaptive_topic
):
    """Registr o'zgarishi navbat o'rtasida emas, navbat yakunida yetkaziladi.

    Suhbat o'rtasida yuborilsa model javobini bo'lib, ketma-ket ikkinchi savol
    berib yuborardi. Har navbatning o'z ko'rsatmasi (§_turn_instruction) esa
    baholashdan keyin, model gapirishidan OLDIN ketaveradi.
    """
    communicator, _ = await open_session(user, adaptive_topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    # `adaptive.MIN_SAMPLES` — uchta javobdan oldin daraja qimirlamaydi.
    for _ in range(3):
        fake_coach.scripted.append(coach_result("correct", fluency=4))
        await learner_says(communicator, gemini, "I am a programmer in Tashkent")

    assert not any("natural conversational pace" in d["text"] for d in gemini.directives), (
        "registr suhbat o'rtasida yuborildi"
    )

    await gemini.emit({"type": "turn_complete"})
    await asyncio.sleep(0.1)

    assert gemini.directives, "daraja o'zgardi, lekin modelga yetkazilmadi"
    pacing = gemini.directives[-1]["text"]
    assert "natural conversational pace" in pacing
    assert "Stay silent and wait for the learner." in pacing

    await communicator.disconnect()


# --- audio relay ----------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_audio_is_relayed_both_ways(fake_gemini, user, topic):
    communicator, _ = await open_session(user, topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    chunk = base64.b64encode(b"\x00\x01" * 100).decode()
    await communicator.send_to(text_data=json.dumps({"type": "audio_chunk", "data": chunk}))
    await asyncio.sleep(0.05)
    assert gemini.audio_chunks == [chunk]

    ai_chunk = base64.b64encode(b"\x02\x03" * 50).decode()
    await gemini.emit({"type": "audio", "data": ai_chunk, "mime": "audio/pcm;rate=24000"})

    message = await drain_until(communicator, "ai_audio")
    assert message["data"] == ai_chunk

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_interruption_is_forwarded_for_barge_in(fake_gemini, user, topic):
    communicator, _ = await open_session(user, topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    await gemini.emit({"type": "interrupted"})
    assert (await drain_until(communicator, "ai_audio_interrupt"))["type"] == "ai_audio_interrupt"

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_transcripts_are_buffered_for_the_pipeline(fake_gemini, fake_coach, user, topic):
    from apps.practice.store import SyncSessionStore

    communicator, payload = await open_session(user, topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]
    qid = (await questions_of(topic))[0].id

    await gemini.emit({"type": "output_transcript", "text": "What do you do?"})
    await gemini.emit({"type": "turn_complete"})
    fake_coach.scripted.append(coach_result("correct"))
    await learner_says(communicator, gemini, "I work in a shop")

    store = SyncSessionStore(payload["session_id"])
    turns = store.get_turns()
    speakers = [t["speaker"] for t in turns]
    assert "ai" in speakers and "learner" in speakers
    assert any(t["text"] == "I work in a shop" for t in turns)

    evaluations = store.get_evaluations()
    assert evaluations[0]["verdict"] == "correct"
    assert evaluations[0]["question_id"] == qid

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_coach_findings_are_buffered_for_the_analysis(fake_gemini, fake_coach, user, topic):
    """Grammatik xatolar real vaqtda yoziladi — yakuniy tahlil ularni qayta qidirmaydi."""
    from apps.practice.store import SyncSessionStore

    communicator, payload = await open_session(user, topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    fake_coach.scripted.append(coach_result("incorrect", error_type="wrong_tense", fluency=2))
    await learner_says(communicator, gemini, "I go yesterday")

    records = SyncSessionStore(payload["session_id"]).get_coach()
    assert records[0]["errors"][0]["type"] == "wrong_tense"
    assert records[0]["fluency"] == 2
    assert records[0]["utterance"] == "I go yesterday"

    # Har chaqiruvning token sarfi ham narx hisobi uchun saqlanadi.
    calls = SyncSessionStore(payload["session_id"]).get_llm_calls()
    # `kind` byudjet uchun: tarjima chaqiruvlari coach tomiga kirmaydi.
    assert calls == [{"model": "test-coach", "in": 300, "out": 90, "kind": "coach"}]

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_speech_end_finalises_the_turn_immediately(fake_gemini, user, topic):
    """Gibrid VAD: client jimlikni sezsa, server o'z taymerini kutmaydi."""
    communicator, _ = await open_session(user, topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    chunk = base64.b64encode(b"\x00\x01" * 10).decode()
    await communicator.send_to(text_data=json.dumps({"type": "audio_chunk", "data": chunk}))
    await communicator.send_to(text_data=json.dumps({"type": "speech_end"}))
    await asyncio.sleep(0.05)
    assert gemini.stream_ends == 1

    # Audio yuborilmagan bo'lsa bo'sh navbat ochilmaydi.
    await communicator.send_to(text_data=json.dumps({"type": "speech_end"}))
    await asyncio.sleep(0.05)
    assert gemini.stream_ends == 1

    await communicator.disconnect()


# --- yakunlash ------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_client_can_end_the_session(fake_gemini, user, topic):
    communicator, payload = await open_session(user, topic)
    await drain_until(communicator, "session_ready")

    await communicator.send_to(text_data=json.dumps({"type": "end_session"}))
    end = await drain_until(communicator, "session_end")
    assert end["reason"] == "completed"

    session = await database_sync_to_async(Session.objects.get)(pk=payload["session_id"])
    assert session.status in (SessionStatus.PROCESSING, SessionStatus.DONE)
    assert session.started_at is not None

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_bank_exhaustion_ends_the_session(fake_gemini, fake_coach, user):
    from apps.content.models import SessionMode
    from conftest import make_topic

    @database_sync_to_async
    def build_small_topic():
        from apps.progress.models import TopicProgress, TopicStatus

        created = make_topic(order=3, questions=2, mode=SessionMode.ANTICIPATION_DRILL)
        TopicProgress.objects.create(user=user, topic=created, status=TopicStatus.ACTIVE)
        return created

    small_topic = await build_small_topic()

    communicator, _ = await open_session(user, small_topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    fake_coach.scripted.extend([coach_result("correct"), coach_result("correct")])
    await learner_says(communicator, gemini, "first answer")
    await learner_says(communicator, gemini, "second answer")

    assert "closing sentence" in last_directive(gemini)

    end = await drain_until(communicator, "session_end")
    assert end["reason"] == "completed"

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_second_connection_to_live_session_is_rejected(fake_gemini, user, topic):
    communicator, payload = await open_session(user, topic)
    await drain_until(communicator, "session_ready")

    token, _ = await database_sync_to_async(issue_token)(user)
    second = WebsocketCommunicator(
        application, f"/ws/session/{payload['session_id']}/?token={token}"
    )
    connected, code = await second.connect()
    assert connected is False
    assert code == consumer_mod.CLOSE_CONFLICT

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_ping_is_answered(fake_gemini, user, topic):
    communicator, _ = await open_session(user, topic)
    await drain_until(communicator, "session_ready")

    await communicator.send_to(text_data=json.dumps({"type": "ping"}))
    pong = await drain_until(communicator, "pong")
    assert "elapsed_s" in pong

    await communicator.disconnect()


# --- jonli transkript -----------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_transcript_is_streamed_to_the_client(fake_gemini, user, topic):
    """Bo'laklar oqim bilan, turn tugaganda esa yakuniy matn yuboriladi."""
    communicator, _ = await open_session(user, topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    await gemini.emit({"type": "output_transcript", "text": "Hello, "})
    first = await drain_until(communicator, "transcript")
    assert (first["speaker"], first["text"], first["final"]) == ("ai", "Hello, ", False)

    await gemini.emit({"type": "output_transcript", "text": "where do you work?"})
    second = await drain_until(communicator, "transcript")
    assert second["text"] == "where do you work?"
    assert second["final"] is False

    await gemini.emit({"type": "turn_complete"})
    final = await drain_until(communicator, "transcript")
    assert final["final"] is True
    assert final["text"] == "Hello, where do you work?"
    assert final["idx"] > 0

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_learner_turn_closes_when_the_model_starts_speaking(
    fake_gemini, fake_coach, user, topic
):
    """O'quvchi navbati Live javob bera boshlagan payt yopiladi.

    Ilgari bu chegara tool call bilan belgilanardi; endi bo'laklar yig'iladi
    va model gapira boshlashi bilan yakuniy matn chiqadi.
    """
    communicator, _ = await open_session(user, topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    await gemini.emit({"type": "input_transcript", "text": "I work "})
    partial = await drain_until(communicator, "transcript")
    assert (partial["speaker"], partial["final"]) == ("learner", False)

    await gemini.emit({"type": "input_transcript", "text": "in a bank"})
    await drain_until(communicator, "transcript")

    await gemini.emit({"type": "output_transcript", "text": "Okay."})
    final = await drain_until(communicator, "transcript")
    assert final["speaker"] == "learner"
    assert final["final"] is True
    assert final["text"] == "I work in a bank"

    await asyncio.sleep(0.15)
    # Coach aynan shu to'liq gapni ko'radi, bo'laklarni emas.
    assert fake_coach.calls[-1].learner_utterance == "I work in a bank"

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_empty_transcript_fragments_are_not_sent(fake_gemini, user, topic):
    """Bo'sh bo'lak suhbat oynasida bo'sh xabar yaratmasligi kerak."""
    communicator, _ = await open_session(user, topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    await gemini.emit({"type": "output_transcript", "text": "   "})
    await gemini.emit({"type": "audio", "data": base64.b64encode(b"x").decode()})

    # Transkript o'rniga darrov audio kelishi kerak.
    message = json.loads(await communicator.receive_from(timeout=3))
    assert message["type"] == "state"  # ai_speaking
    message = json.loads(await communicator.receive_from(timeout=3))
    assert message["type"] == "ai_audio"

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_free_conversation_is_graded_against_what_the_ai_actually_asked(
    fake_gemini, fake_coach, user, adaptive_topic, hold_turn
):
    """Erkin suhbatda savolni model tanlaydi — bankdagi savol AYTILGAN savol emas.

    Bank savoli bilan solishtirilganda coach o'quvchining gapini boshqa
    savolning javobiga tortadi: "Hello" → "My name is Aziz."
    """
    communicator, _ = await open_session(user, adaptive_topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    # Model o'z savolini berdi.
    await gemini.emit({"type": "output_transcript", "text": "How are you today?"})
    await gemini.emit({"type": "turn_complete"})

    fake_coach.scripted.append(coach_result("correct"))
    await learner_says(communicator, gemini, "Hello", ai_reply="")
    await drain_until(communicator, "correction")

    ctx = fake_coach.calls[-1]
    assert ctx.question_text == "How are you today?"
    assert ctx.canonical_answer == "", "bank etaloni erkin suhbatga tortildi"

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_an_answered_goal_is_never_asked_again(fake_gemini, fake_coach, user, adaptive_topic):
    """To'liq javob bir nechta maqsadni yopadi va ular ro'yxatdan chiqadi.

    Bu suhbat bilan so'roqning farqi. O'quvchi "I am a programmer in Tashkent
    and I work every morning" desa, uchta maqsadga birdan javob bergan bo'ladi;
    ularni yana so'rash — u aytgan gapni eshitmaganini bildiradi.
    """
    communicator, _ = await open_session(user, adaptive_topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]
    bank = await questions_of(adaptive_topic)

    # Birinchi navbatda coach butun ro'yxatni ko'radi.
    fake_coach.scripted.append(coach_result("correct", covered_goal_ids=[bank[0].id, bank[1].id]))
    await learner_says(communicator, gemini, "I worked every morning and I visited my friend")
    await drain_until(communicator, "correction")

    first_goals = [g["id"] for g in fake_coach.calls[0].open_goals]
    assert bank[0].id in first_goals and bank[1].id in first_goals

    # Keyingi navbatda yopilganlari ko'rinmaydi.
    fake_coach.scripted.append(coach_result("correct"))
    await learner_says(communicator, gemini, "I ate bread")
    await drain_until(communicator, "correction")

    later_goals = [g["id"] for g in fake_coach.calls[-1].open_goals]
    assert bank[0].id not in later_goals
    assert bank[1].id not in later_goals
    assert bank[2].id in later_goals, "qolgan maqsadlar ham yo'qolib ketdi"

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_invented_goal_ids_are_ignored(fake_gemini, fake_coach, user, adaptive_topic):
    """Coach o'ylab topgan raqam ro'yxatni buza olmaydi."""
    communicator, _ = await open_session(user, adaptive_topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]
    bank = await questions_of(adaptive_topic)

    fake_coach.scripted.append(coach_result("correct", covered_goal_ids=[999_999]))
    await learner_says(communicator, gemini, "I worked yesterday")
    await drain_until(communicator, "correction")

    fake_coach.scripted.append(coach_result("correct"))
    await learner_says(communicator, gemini, "I ate bread")
    await drain_until(communicator, "correction")

    goals = [g["id"] for g in fake_coach.calls[-1].open_goals]
    assert goals == [q.id for q in bank][: coach_mod.MAX_OPEN_GOALS]

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_backend_hands_the_model_the_next_question(
    fake_gemini, fake_coach, user, adaptive_topic, hold_turn
):
    """Keyingi savolni backend beradi — model o'zi o'ylab topmaydi.

    Coach yozgan savol tekshiruvdan o'tadi (strukturani majburlaydi, yes/no
    emas, registrga mos), shundan keyin ko'rsatmaga so'zma-so'z qo'yiladi.
    """
    communicator, _ = await open_session(user, adaptive_topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    fake_coach.scripted.append(coach_result("correct", next_question="What do you usually cook?"))
    await learner_says(communicator, gemini, "I worked yesterday", ai_reply="")
    await drain_until(communicator, "correction")

    directive = last_directive(gemini)
    assert 'Then ask exactly this, in these words: "What do you usually cook?"' in directive

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_a_rejected_question_is_never_spoken(
    fake_gemini, fake_coach, user, adaptive_topic, hold_turn
):
    """Yes/no savoli mashqni buzadi — u ko'rsatmaga umuman tushmaydi."""
    communicator, _ = await open_session(user, adaptive_topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    fake_coach.scripted.append(coach_result("correct", next_question="Do you cook every day?"))
    await learner_says(communicator, gemini, "I worked yesterday", ai_reply="")
    await drain_until(communicator, "correction")

    directive = last_directive(gemini)
    assert "Do you cook every day?" not in directive
    assert "Then ask exactly this" not in directive

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_a_repeat_correction_never_carries_a_new_question(
    fake_gemini, fake_coach, user, adaptive_topic, hold_turn
):
    """Qayta aytirilayotgan navbatda o'quvchi gapiradi — savol qo'shilmaydi."""
    communicator, _ = await open_session(user, adaptive_topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    fake_coach.scripted.append(
        coach_result(
            "incorrect",
            error_type="wrong_tense",
            errors=[{"span": "I go", "fix": "I went", "type": "wrong_tense", "severity": "high"}],
            model_answer="I went to the bazaar yesterday.",
            next_question="What do you usually buy?",
        )
    )
    await learner_says(communicator, gemini, "I go to the bazaar yesterday", ai_reply="")
    await drain_until(communicator, "correction")

    directive = last_directive(gemini)
    assert "Now you say it." in directive
    assert "What do you usually buy?" not in directive

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_a_one_word_answer_is_never_stopped_for_a_repeat(
    fake_gemini, fake_coach, user, adaptive_topic, hold_turn
):
    """ "Hello" darsning shaklini ishlatmaydi — bu xato emas, to'xtatilmaydi."""
    communicator, _ = await open_session(user, adaptive_topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    fake_coach.scripted.append(
        coach_result(
            "incorrect",
            error_type="missing_auxiliary",
            target_structure_used=False,
            model_answer="My name is Aziz.",
        )
    )
    await learner_says(communicator, gemini, "Hello", ai_reply="")
    await drain_until(communicator, "correction")

    directive = last_directive(gemini)
    assert "Now you say it." not in directive, "qisqa javob uchun qayta aytirish so'raldi"
    assert "carry on with the conversation" in directive

    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_a_finished_answer_is_graded_while_the_pause_window_runs(
    fake_gemini, fake_coach, user, adaptive_topic, monkeypatch
):
    """Kutish oynasi va tarmoq kutishi ustma-ust tushadi.

    Oyna "davomi bormi?" degan savolga javob kutadi, chaqiruv esa audio
    tayyorligi bilan yuborilaveradi — ikkalasi ham sof kutish. Audio o'sha
    audio, model o'sha model: sifat o'zgarmaydi, faqat jimlik qisqaradi.
    """
    from apps.practice import asr

    async def no_verbatim(pcm, target_structure=""):
        return "", {}

    monkeypatch.setattr(asr, "transcribe", no_verbatim)
    monkeypatch.setattr(consumer_mod, "TURN_END_GRACE_SECONDS", 0.4)

    communicator, _ = await open_session(user, adaptive_topic)
    await drain_until(communicator, "session_ready")
    gemini = fake_gemini.instances[-1]

    # 2 s nutq (16 kHz, 16-bit) — tugallangan javob.
    chunk = base64.b64encode(b"\x00\x40" * 32000).decode()
    await communicator.send_to(text_data=json.dumps({"type": "speech_start"}))
    await communicator.send_to(text_data=json.dumps({"type": "audio_chunk", "data": chunk}))
    await gemini.emit({"type": "input_transcript", "text": "I went to the bazaar"})

    fake_coach.scripted.append(coach_result("correct"))
    await communicator.send_to(text_data=json.dumps({"type": "speech_end"}))

    # Oyna hali tugamagan, lekin baholash allaqachon boshlangan.
    await asyncio.sleep(0.15)
    assert len(fake_coach.calls) == 1, "baholash oyna tugashini kutdi"

    # Oyna yakunida qayta so'ralmaydi — o'sha natija ishlatiladi.
    await asyncio.sleep(0.5)
    assert len(fake_coach.calls) == 1, "o'sha audio ikkinchi marta baholandi"
    await drain_until(communicator, "correction")

    await communicator.disconnect()
