"""§10 — kontent sifat qoidalari, generatsiya sxemasi, seed fixture."""

import json

import pytest
from django.conf import settings
from django.core.management import call_command

from apps.content.generation import GenerationError, parse_questions
from apps.content.models import LEARNER_TRACKS, Question, QuestionStatus, Topic
from apps.content.validators import check_batch, check_question


def seeded_topics():
    """Seed buyrug'i boshqaradigan mavzular.

    `placement` treki bu yerda YO'Q: daraja aniqlash mavzusi kontent emas,
    infratuzilma va u migratsiyada yaratiladi (§content migration 0012).
    Seed fayli bilan solishtirilsa, har safar bitta ortiqcha mavzu chiqadi.
    """
    return Topic.objects.filter(track__in=LEARNER_TRACKS)


GOOD = {
    "question_text": "What do you do every morning?",
    "canonical_answer": "I drink tea every morning.",
    "answer_variants": ["I make breakfast every morning."],
    "elicitation_note": "Full sentence required.",
}


# --- sifat qoidalari (§4.2) ----------------------------------------------


def test_good_question_passes():
    assert check_question(GOOD) == []


@pytest.mark.parametrize(
    "text",
    [
        "Do you like tea?",
        "Are you a student?",
        "Have you been to Samarkand?",
        "Can you swim?",
        "Did you go home?",
    ],
)
def test_yes_no_questions_are_flagged(text):
    problems = check_question({**GOOD, "question_text": text})
    assert any("yes/no" in p for p in problems)


@pytest.mark.parametrize("text", ["How many brothers do you have?", "What time do you get up?"])
def test_one_word_answer_questions_are_flagged(text):
    problems = check_question({**GOOD, "question_text": text})
    assert any("bir so'zli" in p for p in problems)


def test_imperative_prompts_are_valid_without_question_mark():
    """'Tell me about...' yes/no javobga yo'l qo'ymaydi — bu to'g'ri format."""
    for text in [
        "Tell me about your room.",
        "Compare summer and winter in your country.",
        "Describe your street.",
        "Ask me where I live.",
    ]:
        assert check_question({**GOOD, "question_text": text}) == []


def test_statement_without_question_mark_is_flagged():
    problems = check_question({**GOOD, "question_text": "Your morning routine"})
    assert any("imperativ" in p for p in problems)


def test_too_short_canonical_answer_is_flagged():
    problems = check_question({**GOOD, "canonical_answer": "Tea."})
    assert any("juda qisqa" in p for p in problems)


def test_empty_fields_are_flagged():
    problems = check_question({"question_text": "", "canonical_answer": ""})
    assert len(problems) == 2


def test_too_many_variants_are_flagged():
    problems = check_question({**GOOD, "answer_variants": ["a b c", "d e f", "g h i", "j k l"]})
    assert any("maksimum 3" in p for p in problems)


def test_check_batch_reports_only_problem_indexes():
    result = check_batch([GOOD, {**GOOD, "question_text": "Do you sleep?"}, GOOD])
    assert list(result.keys()) == [1]


# --- generatsiya chiqishi sxemasi (§10.2, §11) ---------------------------


def test_parse_questions_accepts_valid_payload():
    payload = json.dumps({"questions": [GOOD]})
    items = parse_questions(payload)
    assert items[0]["question_text"] == GOOD["question_text"]
    assert items[0]["answer_variants"] == GOOD["answer_variants"]


def test_parse_questions_strips_markdown_fences():
    payload = "```json\n" + json.dumps({"questions": [GOOD]}) + "\n```"
    assert len(parse_questions(payload)) == 1


def test_parse_questions_accepts_bare_array():
    assert len(parse_questions(json.dumps([GOOD, GOOD]))) == 2


def test_parse_questions_caps_variants_at_three():
    noisy = {**GOOD, "answer_variants": ["a", "b", "c", "d", "e"]}
    assert len(parse_questions(json.dumps({"questions": [noisy]}))[0]["answer_variants"]) == 3


def test_parse_questions_rejects_invalid_json():
    with pytest.raises(GenerationError):
        parse_questions("not json at all")


def test_parse_questions_rejects_wrong_shape():
    with pytest.raises(GenerationError):
        parse_questions(json.dumps({"items": [GOOD]}))


# --- management komandalar -----------------------------------------------


def fixture_topics() -> list[dict]:
    """Seed faylining o'zi — kutilgan sonlar qo'lda yozilmaydi.

    Dastur o'sib boradi (mavzular Cambridge sillabusi bo'yicha qo'shiladi),
    shuning uchun test raqamni emas, FAYL bilan DB mosligini tekshiradi.
    """
    path = settings.BASE_DIR / "fixtures" / "seed_content.json"
    return json.loads(path.read_text(encoding="utf-8"))["topics"]


@pytest.mark.django_db
def test_seed_content_loads_all_topics():
    call_command("seed_content", verbosity=0)
    topics = fixture_topics()

    assert seeded_topics().filter(status="published").count() == len(topics)
    # Ro'yxat tekis va uzluksiz: darajalar yo'q, tartib 1..N.
    assert list(seeded_topics().order_by("order").values_list("order", flat=True)) == list(
        range(1, len(topics) + 1)
    )
    assert Question.objects.filter(
        status=QuestionStatus.APPROVED, topic__track__in=LEARNER_TRACKS
    ).count() == sum(len(t["questions"]) for t in topics)


@pytest.mark.django_db
def test_seed_content_is_idempotent():
    topics = fixture_topics()
    call_command("seed_content", verbosity=0)
    call_command("seed_content", verbosity=0)
    assert seeded_topics().count() == len(topics)
    assert Question.objects.filter(topic__track__in=LEARNER_TRACKS).count() == sum(
        len(t["questions"]) for t in topics
    )


@pytest.mark.django_db
def test_seed_content_keeps_topic_identity_when_order_changes():
    """Ro'yxat orasiga yangi mavzu qo'shilsa, eski mavzu ID'si saqlanadi.

    O'quvchi progressi mavzu ID'siga bog'langan. Ilgari seed `order` bo'yicha
    yozardi: 7-o'ringa boshqa mavzu tushsa, o'quvchining "o'tilgan" mavzusi
    jimgina BOSHQA mavzuga aylanib qolardi.
    """
    call_command("seed_content", verbosity=0)
    topics = fixture_topics()
    last = topics[-1]["target_structure"]
    before = Topic.objects.get(target_structure=last)

    # Faylni "o'zgartiramiz": oxirgi mavzuni birinchi o'ringa ko'chiramiz.
    shuffled = [dict(t) for t in topics]
    moved = shuffled.pop()
    shuffled.insert(0, moved)
    for i, t in enumerate(shuffled, start=1):
        t["order"] = i

    path = settings.BASE_DIR / "fixtures" / "_reorder_test.json"
    path.write_text(json.dumps({"topics": shuffled}, ensure_ascii=False), encoding="utf-8")
    try:
        call_command("seed_content", file=str(path), verbosity=0)
    finally:
        path.unlink()

    after = Topic.objects.get(target_structure=last)
    assert after.id == before.id, "mavzu ID'si o'zgarib ketdi — progress uziladi"
    assert after.order == 1
    assert seeded_topics().count() == len(topics)


@pytest.mark.django_db
def test_seed_content_passes_quality_checks():
    """Repo bilan kelgan barcha savollar §4.2 qoidasidan o'tishi shart."""
    call_command("seed_content", verbosity=0)

    failures = []
    for q in Question.objects.all():
        problems = check_question(
            {
                "question_text": q.question_text,
                "canonical_answer": q.canonical_answer,
                "answer_variants": q.answer_variants,
            }
        )
        if problems:
            failures.append((q.question_text, problems))

    assert failures == []


@pytest.mark.django_db
def test_seeded_topics_have_material_and_chunks():
    call_command("seed_content", verbosity=0)
    for topic in seeded_topics():
        assert hasattr(topic, "material")
        assert len(topic.material.examples) >= 3
        assert topic.chunks.count() >= 2


@pytest.mark.django_db
def test_import_questions_writes_drafts(tmp_path, topic):
    payload = {"topic_id": topic.id, "questions": [GOOD]}
    path = tmp_path / "questions.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    call_command("import_questions", file=str(path), verbosity=0)

    imported = Question.objects.filter(question_text=GOOD["question_text"]).first()
    assert imported.status == QuestionStatus.DRAFT
    assert imported.source == "generated"


@pytest.mark.django_db
def test_import_questions_validate_only_writes_nothing(tmp_path, topic):
    before = Question.objects.count()
    path = tmp_path / "q.json"
    path.write_text(json.dumps({"topic_id": topic.id, "questions": [GOOD]}), encoding="utf-8")

    call_command("import_questions", file=str(path), validate_only=True, verbosity=0)

    assert Question.objects.count() == before


@pytest.mark.django_db
def test_generate_topic_content_from_file_writes_drafts(tmp_path, topic):
    path = tmp_path / "generated.json"
    path.write_text(json.dumps({"questions": [GOOD]}), encoding="utf-8")

    call_command(
        "generate_topic_content",
        topic_id=topic.id,
        from_file=str(path),
        verbosity=0,
    )

    created = Question.objects.filter(question_text=GOOD["question_text"]).first()
    assert created.status == QuestionStatus.DRAFT
    assert created.source == "generated"


@pytest.mark.django_db
def test_generate_topic_content_strict_mode_drops_bad_questions(tmp_path, topic):
    bad = {**GOOD, "question_text": "Do you like tea?"}
    path = tmp_path / "generated.json"
    path.write_text(json.dumps({"questions": [bad]}), encoding="utf-8")

    before = Question.objects.count()
    call_command(
        "generate_topic_content",
        topic_id=topic.id,
        from_file=str(path),
        strict=True,
        verbosity=0,
    )
    # Sifat tekshiruvidan o'tmagan savol DB'ga umuman tushmaydi.
    assert Question.objects.count() == before
    assert not Question.objects.filter(question_text=bad["question_text"]).exists()
