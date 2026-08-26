"""§10 — `generate_topic_content --topic-id N --count 20`.

Generatsiya qilingan savollar `status=draft, source=generated` bilan yoziladi;
inson review'i admin panelda (§9).
"""

import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.content.generation import (
    GENERATION_PROMPT_VERSION,
    GenerationError,
    generate_questions,
    parse_questions,
)
from apps.content.models import Question, QuestionSource, QuestionStatus, Topic
from apps.content.validators import check_question


class Command(BaseCommand):
    help = "Mavzu uchun savollar generatsiya qiladi (draft holatida yoziladi)."

    def add_arguments(self, parser):
        parser.add_argument("--topic-id", type=int, required=True)
        parser.add_argument("--count", type=int, default=20)
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="DB'ga yozmasdan natijani chiqaradi",
        )
        parser.add_argument(
            "--from-file",
            help="LLM o'rniga tayyor JSON fayldan o'qiydi (offline test uchun)",
        )
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Sifat tekshiruvidan o'tmagan savollarni umuman yozmaydi",
        )

    def handle(self, *args, **options):
        try:
            topic = Topic.objects.get(pk=options["topic_id"])
        except Topic.DoesNotExist as exc:
            raise CommandError(f"Mavzu topilmadi: {options['topic_id']}") from exc

        existing = list(topic.questions.values_list("question_text", flat=True))

        self.stdout.write(
            f"Mavzu: {topic} | struktura: {topic.target_structure} | "
            f"prompt: {GENERATION_PROMPT_VERSION}"
        )

        try:
            if options["from_file"]:
                with open(options["from_file"], encoding="utf-8") as fh:
                    items = parse_questions(fh.read())
            else:
                items = generate_questions(
                    target_structure=topic.target_structure,
                    topic_title_en=topic.title_en,
                    count=options["count"],
                    existing_questions=existing,
                )
        except GenerationError as exc:
            raise CommandError(str(exc)) from exc

        if not items:
            raise CommandError("Generatsiya bo'sh natija qaytardi")

        accepted, rejected = [], []
        seen = {q.strip().lower() for q in existing}
        for item in items:
            problems = check_question(item)
            key = item["question_text"].strip().lower()
            if key in seen:
                problems.append("takrorlanuvchi savol")
            if problems:
                rejected.append((item, problems))
                if options["strict"]:
                    continue
            seen.add(key)
            accepted.append(item)

        self.stdout.write(
            f"Generatsiya: {len(items)} ta | qabul: {len(accepted)} | muammoli: {len(rejected)}"
        )
        for item, problems in rejected:
            self.stdout.write(
                self.style.WARNING(f"  [!] {item['question_text'][:70]} - {'; '.join(problems)}")
            )

        if options["dry_run"]:
            self.stdout.write(json.dumps(accepted, ensure_ascii=False, indent=2))
            self.stdout.write(self.style.SUCCESS("dry-run: DB'ga yozilmadi"))
            return

        with transaction.atomic():
            start_order = (
                topic.questions.order_by("-order").values_list("order", flat=True).first() or 0
            )
            Question.objects.bulk_create(
                [
                    Question(
                        topic=topic,
                        order=start_order + i,
                        question_text=item["question_text"],
                        canonical_answer=item["canonical_answer"],
                        answer_variants=item["answer_variants"],
                        elicitation_note=item["elicitation_note"],
                        status=QuestionStatus.DRAFT,
                        source=QuestionSource.GENERATED,
                    )
                    for i, item in enumerate(accepted, start=1)
                ]
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"{len(accepted)} ta savol draft holatida yozildi. "
                f"Admin panelda review qiling: /admin/content/question/?topic__id__exact={topic.id}"
            )
        )
