"""Shadowing va rol suhbat yo'nalishlari.

Asosiy da'volar:
  - to'rt yo'nalish ham mustaqil ro'yxat (o'z tartibi, o'z ochilishi);
  - shadowing matni ham GRAMMATIKAGA, ham IBORAGA bog'langan;
  - ikkala rejim ham sessiya mashinasida ishlaydi (strategiya + prompt fayl);
  - shadowing prompti "gapni ayt, o'quvchi takrorlaydi" tartibini beradi,
    rol suhbat prompti esa AI'ni roldan chiqarmaydi.
"""

import json

import pytest
from django.conf import settings
from django.core.management import call_command

from apps.content.models import (
    FREE_FLOW_MODES,
    IMPLEMENTED_MODES,
    LEARNER_TRACKS,
    SessionMode,
    Topic,
    TopicTrack,
)
from apps.content.validators import check_question
from apps.practice import prompts, state
from apps.progress import services
from apps.progress.models import TopicProgress, TopicStatus

FIXTURES = {
    TopicTrack.PHRASES: settings.BASE_DIR / "fixtures" / "seed_phrases.json",
    TopicTrack.SHADOWING: settings.BASE_DIR / "fixtures" / "seed_shadowing.json",
    TopicTrack.ROLEPLAY: settings.BASE_DIR / "fixtures" / "seed_roleplay.json",
}


def topics_of(track) -> list[dict]:
    return json.loads(FIXTURES[track].read_text(encoding="utf-8"))["topics"]


def seed_everything():
    call_command("seed_content", verbosity=0)
    for path in FIXTURES.values():
        call_command("seed_content", file=str(path), verbosity=0)


# --- fixture sifati -------------------------------------------------------


@pytest.mark.parametrize("track", [TopicTrack.SHADOWING, TopicTrack.ROLEPLAY])
def test_fixture_is_complete(track):
    gaps = []
    for t in topics_of(track):
        m = t["material"]
        for field in ("rule_uz", "rule_ru", "usage_uz", "usage_ru"):
            if not (m.get(field) or "").strip():
                gaps.append(f"{t['target_structure']}: {field}")
        if not t.get("title_ru"):
            gaps.append(f"{t['target_structure']}: title_ru")
        if t.get("session_mode") != track:
            gaps.append(f"{t['target_structure']}: session_mode")
        for example in m["examples"]:
            if not all(example.get(k) for k in ("en", "uz", "ru")):
                gaps.append(f"{t['target_structure']}: misol tarjimasi")
        for chunk in t["chunks"]:
            if not chunk.get("translation_ru"):
                gaps.append(f"{t['target_structure']}: chunk ruschasi")
        for i, q in enumerate(t["questions"], start=1):
            for problem in check_question(q):
                gaps.append(f"{t['target_structure']}#{i}: {problem}")
    assert gaps == []


def test_every_shadowing_text_names_a_grammar_and_a_phrase():
    """Foydalanuvchi talabi: shadowingda ishlatilgan ibora va grammatika
    ko'rinib turishi kerak — ya'ni ikkala bog'lam ham majburiy."""
    phrase_keys = {t["target_structure"] for t in topics_of(TopicTrack.PHRASES)}
    grammar_keys = {
        t["target_structure"]
        for t in json.loads(
            (settings.BASE_DIR / "fixtures" / "seed_content.json").read_text(encoding="utf-8")
        )["topics"]
    }

    for t in topics_of(TopicTrack.SHADOWING):
        links = t.get("related_structures") or []
        assert any(k in grammar_keys for k in links), f"{t['target_structure']}: grammatika yo'q"
        assert any(k in phrase_keys for k in links), f"{t['target_structure']}: ibora yo'q"


def test_shadowing_lines_are_repeatable_verbatim():
    """Shadowingda kutilgan javob — AYNAN aytilgan gap, o'z gapi emas."""
    for t in topics_of(TopicTrack.SHADOWING):
        for q in t["questions"]:
            assert q["canonical_answer"] in q["question_text"], q["question_text"]


# --- seed va yo'nalishlar mustaqilligi ------------------------------------


@pytest.mark.django_db
def test_all_four_tracks_keep_their_own_numbering():
    seed_everything()
    for track in TopicTrack.values:
        orders = list(
            Topic.objects.filter(track=track).order_by("order").values_list("order", flat=True)
        )
        assert orders == list(range(1, len(orders) + 1)), track
        assert orders, track


@pytest.mark.django_db
def test_links_reach_across_tracks():
    seed_everything()
    for topic in Topic.objects.filter(track=TopicTrack.SHADOWING):
        tracks = {t.track for t in topic.related_topics.all()}
        assert TopicTrack.GRAMMAR in tracks, topic.target_structure
        assert TopicTrack.PHRASES in tracks, topic.target_structure


@pytest.mark.django_db
def test_seeding_one_track_leaves_the_others_untouched():
    seed_everything()
    before = dict(
        Topic.objects.exclude(track=TopicTrack.ROLEPLAY).values_list("target_structure", "order")
    )
    call_command("seed_content", file=str(FIXTURES[TopicTrack.ROLEPLAY]), verbosity=0)
    after = dict(
        Topic.objects.exclude(track=TopicTrack.ROLEPLAY).values_list("target_structure", "order")
    )
    assert before == after


@pytest.mark.django_db
def test_every_track_opens_its_first_topic(user):
    seed_everything()
    services.ensure_bootstrapped(user)
    opened = set(
        TopicProgress.objects.filter(user=user)
        .exclude(status=TopicStatus.LOCKED)
        .values_list("topic__track", "topic__order")
    )
    # `placement` bu yerda YO'Q: daraja aniqlash ketma-ketlikning bir qismi
    # emas, ya'ni uning progress yozuvi ham bo'lmaydi
    # (§progress.services.is_topic_accessible).
    assert opened == {(track, 1) for track in LEARNER_TRACKS}


@pytest.mark.django_db
def test_mastering_a_shadowing_text_unlocks_the_next_shadowing_text(user):
    seed_everything()
    first, second = Topic.objects.filter(track=TopicTrack.SHADOWING).order_by("order")[:2]
    assert services.unlock_next_topic(user, first) == second


# --- sessiya mashinasi ----------------------------------------------------


@pytest.mark.parametrize("mode", [SessionMode.SHADOWING, SessionMode.ROLEPLAY])
def test_mode_is_implemented_and_free_flowing(mode):
    assert mode in IMPLEMENTED_MODES
    assert mode in FREE_FLOW_MODES
    assert state.get_strategy(mode).name == mode


@pytest.mark.parametrize("mode", [SessionMode.SHADOWING, SessionMode.ROLEPLAY])
def test_mode_has_its_own_prompt_file(mode):
    prompt = prompts.build_system_prompt(
        mode=mode,
        register=2,
        target_structure="shadow_small_talk",
        questions=["Say this back to me: Hey, how's it going?"],
    )
    assert f"MODE: {mode}" in prompt.lower() or mode in prompt.lower()
    # Erkin oqim: savollar GOALS bo'lib kiradi va DIRECTOR kutilmaydi.
    assert "SESSION GOALS" in prompt
    assert "The first question will arrive in a DIRECTOR message" not in prompt


def test_shadowing_prompt_protects_the_repeat_loop():
    prompt = prompts.build_system_prompt(
        mode=SessionMode.SHADOWING, register=2, target_structure="shadow_small_talk"
    )
    assert "Never say two lines in the same turn" in prompt
    assert "Never change the words of a line" in prompt


def test_roleplay_prompt_keeps_the_ai_in_character():
    prompt = prompts.build_system_prompt(
        mode=SessionMode.ROLEPLAY, register=2, target_structure="roleplay_cafe_order"
    )
    assert "STAY IN ROLE" in prompt
    assert "Never do their part for them" in prompt


@pytest.mark.django_db
def test_session_starts_on_a_roleplay_topic(user):
    """Rol suhbat mavzusida sessiya ochiladi va promptga rol ko'rsatmasi tushadi."""
    from apps.practice.services import start_session
    from apps.practice.store import SyncSessionStore

    seed_everything()
    topic = Topic.objects.filter(track=TopicTrack.ROLEPLAY).order_by("order").first()
    payload = start_session(user, topic.id)

    assert payload["mode"] == SessionMode.ROLEPLAY
    meta = SyncSessionStore(payload["session_id"]).get_meta()
    assert "STAY IN ROLE" in meta["system_prompt"]
    assert meta["mode"] == SessionMode.ROLEPLAY


@pytest.mark.django_db
def test_session_starts_on_a_shadowing_topic(user):
    from apps.practice.services import start_session
    from apps.practice.store import SyncSessionStore

    seed_everything()
    topic = Topic.objects.filter(track=TopicTrack.SHADOWING).order_by("order").first()
    payload = start_session(user, topic.id)
    store = SyncSessionStore(payload["session_id"])
    meta = store.get_meta()
    assert payload["mode"] == SessionMode.SHADOWING
    assert "Never say two lines in the same turn" in meta["system_prompt"]
    # Shadowingda ibora majburlanmaydi: o'quvchi AI aytgan gapni takrorlaydi.
    assert "PHRASE FOCUS" not in meta["system_prompt"]
