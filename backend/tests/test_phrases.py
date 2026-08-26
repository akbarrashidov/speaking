"""Iboralar yo'nalishi (§track=phrases).

Nima tekshiriladi:
  - iboralar ro'yxati grammatikadan MUSTAQIL (o'z tartibi, o'z ochilishi);
  - iboraning grammatika bilan bog'lami API'da ko'rinadi;
  - "qayerda ishlatiladi" matni o'quvchi tilida keladi;
  - sessiya promptida aynan o'sha ibora majburlanadi.
"""

import json

import pytest
from django.conf import settings
from django.core.management import call_command

from apps.content.models import Material, Topic, TopicTrack
from apps.content.validators import check_question
from apps.practice import prompts
from apps.progress import services
from apps.progress.models import TopicProgress, TopicStatus
from conftest import make_topic

PHRASES_FIXTURE = settings.BASE_DIR / "fixtures" / "seed_phrases.json"


def fixture_phrases() -> list[dict]:
    return json.loads(PHRASES_FIXTURE.read_text(encoding="utf-8"))["topics"]


def make_phrase_topic(order=1, *, phrase="look forward to + -ing", related=()):
    topic = Topic.objects.create(
        track=TopicTrack.PHRASES,
        order=order,
        title_uz=f"Ibora {order}",
        target_structure=f"phrase_test_{order}",
        focus_phrase=phrase,
        status="published",
    )
    if related:
        topic.related_topics.set(related)
    Material.objects.create(
        topic=topic,
        rule_uz="To dan keyin -ing.",
        usage_uz="Xat oxirida ishlatiladi.",
        usage_ru="Используется в конце письма.",
        examples=[{"en": "I look forward to seeing you.", "uz": "Ko'rishishni kutaman."}],
    )
    return topic


# --- fixture sifati -------------------------------------------------------


def test_phrase_fixture_is_complete():
    """Har ibora: shakl, qayerda ishlatiladi, bog'lam va ikki til — to'liq."""
    gaps = []
    for t in fixture_phrases():
        m = t["material"]
        for field in ("rule_uz", "rule_ru", "usage_uz", "usage_ru"):
            if not (m.get(field) or "").strip():
                gaps.append(f"{t['target_structure']}: {field}")
        if not t.get("focus_phrase"):
            gaps.append(f"{t['target_structure']}: focus_phrase")
        if not t.get("related_structures"):
            gaps.append(f"{t['target_structure']}: related_structures")
        if not t.get("title_ru"):
            gaps.append(f"{t['target_structure']}: title_ru")
        for example in m["examples"]:
            if not all(example.get(k) for k in ("en", "uz", "ru")):
                gaps.append(f"{t['target_structure']}: misol tarjimasi")
        for chunk in t["chunks"]:
            if not chunk.get("translation_ru"):
                gaps.append(f"{t['target_structure']}: chunk ruschasi")
    assert gaps == []


def test_phrase_questions_pass_quality_rules():
    problems = {}
    for t in fixture_phrases():
        for i, q in enumerate(t["questions"], start=1):
            found = check_question(q)
            if found:
                problems[f"{t['target_structure']}#{i}"] = found
    assert problems == {}


@pytest.mark.django_db
def test_seed_loads_phrases_into_their_own_track():
    call_command("seed_content", verbosity=0)
    call_command("seed_content", file=str(PHRASES_FIXTURE), verbosity=0)

    phrases = Topic.objects.filter(track=TopicTrack.PHRASES).order_by("order")
    assert phrases.count() == len(fixture_phrases())
    # Tartib yo'nalish ichida 1..N — grammatikaning 1-mavzusi ham joyida qoladi.
    assert list(phrases.values_list("order", flat=True)) == list(range(1, phrases.count() + 1))
    assert Topic.objects.filter(track=TopicTrack.GRAMMAR, order=1).exists()

    # Har ibora grammatik mavzuga bog'landi.
    for topic in phrases:
        related = list(topic.related_topics.all())
        assert related, topic.target_structure
        assert all(r.track == TopicTrack.GRAMMAR for r in related)
        assert topic.focus_phrase


@pytest.mark.django_db
def test_seeding_phrases_does_not_renumber_grammar():
    call_command("seed_content", verbosity=0)
    before = dict(Topic.objects.filter(track=TopicTrack.GRAMMAR).values_list("id", "order"))
    call_command("seed_content", file=str(PHRASES_FIXTURE), verbosity=0)
    after = dict(Topic.objects.filter(track=TopicTrack.GRAMMAR).values_list("id", "order"))
    assert before == after


# --- progress: yo'nalishlar mustaqil -------------------------------------


@pytest.mark.django_db
def test_each_track_opens_its_own_first_topic(user):
    make_topic(order=1)
    make_topic(order=2)
    phrase = make_phrase_topic(order=1)
    make_phrase_topic(order=2)

    services.ensure_bootstrapped(user)

    opened = set(
        TopicProgress.objects.filter(user=user)
        .exclude(status=TopicStatus.LOCKED)
        .values_list("topic__track", "topic__order")
    )
    assert opened == {(TopicTrack.GRAMMAR, 1), (TopicTrack.PHRASES, 1)}
    assert TopicProgress.objects.get(user=user, topic=phrase).status == TopicStatus.ACTIVE


@pytest.mark.django_db
def test_next_topic_stays_inside_the_track(user):
    make_topic(order=1)
    grammar_second = make_topic(order=2)
    first_phrase = make_phrase_topic(order=1)
    second_phrase = make_phrase_topic(order=2)

    assert services.unlock_next_topic(user, first_phrase) == second_phrase
    assert services.published_topics(TopicTrack.PHRASES).count() == 2
    assert grammar_second not in services.published_topics(TopicTrack.PHRASES)


@pytest.mark.django_db
def test_previous_topic_stays_inside_the_track():
    make_topic(order=1)
    make_phrase_topic(order=1)
    second_phrase = make_phrase_topic(order=2)
    assert services.previous_topic(second_phrase).track == TopicTrack.PHRASES


# --- API ------------------------------------------------------------------


@pytest.mark.django_db
def test_topics_endpoint_defaults_to_grammar(auth_client):
    make_topic(order=1)
    make_phrase_topic(order=1)
    data = auth_client.get("/api/topics").json()
    assert data["track"] == TopicTrack.GRAMMAR
    assert [t["track"] for t in data["topics"]] == [TopicTrack.GRAMMAR]


@pytest.mark.django_db
def test_topics_endpoint_returns_phrases_when_asked(auth_client):
    make_topic(order=1)
    make_phrase_topic(order=1, phrase="had better + verb")
    data = auth_client.get("/api/topics?track=phrases").json()
    assert data["track"] == TopicTrack.PHRASES
    assert len(data["topics"]) == 1
    assert data["topics"][0]["focus_phrase"] == "had better + verb"


@pytest.mark.django_db
def test_unknown_track_is_rejected(auth_client):
    assert auth_client.get("/api/topics?track=poetry").status_code == 400


@pytest.mark.django_db
def test_material_exposes_usage_and_grammar_link(auth_client):
    grammar = make_topic(order=1)
    phrase = make_phrase_topic(order=1, related=[grammar])

    payload = auth_client.get(f"/api/topics/{phrase.id}/material").json()

    assert payload["track"] == TopicTrack.PHRASES
    assert payload["focus_phrase"] == "look forward to + -ing"
    assert payload["usage"] == "Xat oxirida ishlatiladi."
    assert [r["topic_id"] for r in payload["related"]] == [grammar.id]
    assert payload["related"][0]["track"] == TopicTrack.GRAMMAR


@pytest.mark.django_db
def test_usage_follows_the_learner_language(auth_client, user):
    phrase = make_phrase_topic(order=1)
    user.language_code = "ru"
    user.save(update_fields=["language_code"])

    payload = auth_client.get(f"/api/topics/{phrase.id}/material").json()
    assert payload["usage"] == "Используется в конце письма."


@pytest.mark.django_db
def test_grammar_material_has_no_usage_block(auth_client):
    grammar = make_topic(order=1)
    payload = auth_client.get(f"/api/topics/{grammar.id}/material").json()
    assert payload["usage"] == ""
    assert payload["related"] == []
    assert payload["focus_phrase"] == ""


# --- sessiya prompti -----------------------------------------------------


def test_prompt_forces_the_exact_phrase():
    prompt = prompts.build_system_prompt(
        mode="adaptive_conversation",
        register=2,
        target_structure="phrase_had_better",
        focus_phrase="had better + verb",
    )
    assert "PHRASE FOCUS" in prompt
    assert '"had better + verb"' in prompt
    # Ibora nomlanmasligi kerak — o'quvchi qoida eshitmaydi, suhbat eshitadi.
    assert "Never spell it out as a rule" in prompt


def test_grammar_prompt_has_no_phrase_block():
    prompt = prompts.build_system_prompt(
        mode="adaptive_conversation",
        register=2,
        target_structure="past_simple_affirmative",
    )
    assert "PHRASE FOCUS" not in prompt


def test_coach_context_passes_the_phrase_only_when_set():
    from apps.practice.coach import CoachContext

    with_phrase = json.loads(
        CoachContext(focus_phrase="to be honest", learner_utterance="I think so").to_user_prompt()
    )
    assert with_phrase["focus_phrase"] == "to be honest"

    without = json.loads(CoachContext(learner_utterance="I think so").to_user_prompt())
    assert "focus_phrase" not in without
