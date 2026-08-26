"""§9 — `import_questions --file questions.json`.

Generatsiya sxemasini (§10) validatsiya qiladi va draft holatida import qiladi.
Fayl formati: {"topic_id": N, "questions": [...]} yoki [{"topic_id": N, ...}].
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.content.models import Question, QuestionSource, QuestionStatus, Topic
from apps.content.validators import check_question

REQUIRED_FIELDS = ("question_text", "canonical_answer")


class Command(BaseCommand):
    help = "JSON fayldan savollarni import qiladi (sxema validatsiyasi bilan)."

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True)
        parser.add_argument(
            "--topic-id",
            type=int,
            help="Fayl ichida topic_id bo'lmasa, shu mavzuga yoziladi",
        )
        parser.add_argument(
            "--status",
            default=QuestionStatus.DRAFT,
            choices=[c[0] for c in QuestionStatus.choices],
        )
        parser.add_argument("--validate-only", action="store_true")

    def handle(self, *args, **options):
        path = Path(options["file"])
        if not path.exists():
            raise CommandError(f"Fayl topilmadi: {path}")

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CommandError(f"JSON xato: {exc}") from exc

        groups = self._normalize(data, options.get("topic_id"))
        if not groups:
            raise CommandError("Import qilinadigan savol topilmadi")

        total, problems_total = 0, 0
        to_create = []

        for topic_id, items in groups.items():
            try:
                topic = Topic.objects.get(pk=topic_id)
            except Topic.DoesNotExist as exc:
                raise CommandError(f"Mavzu topilmadi: {topic_id}") from exc

            start_order = (
                topic.questions.order_by("-order").values_list("order", flat=True).first() or 0
            )
            for i, item in enumerate(items, start=1):
                missing = [f for f in REQUIRED_FIELDS if not item.get(f)]
                if missing:
                    raise CommandError(
                        f"Mavzu {topic_id}, savol #{i}: majburiy maydonlar yo'q: "
                        f"{', '.join(missing)}"
                    )
                problems = check_question(item)
                if problems:
                    problems_total += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f"  [!] {topic}: {item['question_text'][:60]} - {'; '.join(problems)}"
                        )
                    )
                total += 1
                to_create.append(
                    Question(
                        topic=topic,
                        order=start_order + i,
                        question_text=item["question_text"],
                        canonical_answer=item["canonical_answer"],
                        answer_variants=item.get("answer_variants") or [],
                        elicitation_note=item.get("elicitation_note") or "",
                        status=options["status"],
                        source=item.get("source", QuestionSource.GENERATED),
                    )
                )

        if options["validate_only"]:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Validatsiya: {total} ta savol, {problems_total} ta ogohlantirish. "
                    "DB'ga yozilmadi."
                )
            )
            return

        with transaction.atomic():
            Question.objects.bulk_create(to_create)

        self.stdout.write(
            self.style.SUCCESS(
                f"{total} ta savol import qilindi (status={options['status']}), "
                f"{problems_total} ta ogohlantirish."
            )
        )

    def _normalize(self, data, default_topic_id) -> dict[int, list[dict]]:
        groups: dict[int, list[dict]] = {}

        def add(topic_id, items):
            if topic_id is None:
                raise CommandError("topic_id ko'rsatilmagan (faylda ham, --topic-id ham yo'q)")
            groups.setdefault(int(topic_id), []).extend(items)

        if isinstance(data, dict):
            if "questions" in data:
                add(data.get("topic_id", default_topic_id), data["questions"])
            else:
                for topic_id, items in data.items():
                    add(topic_id, items)
        elif isinstance(data, list):
            if data and isinstance(data[0], dict) and "questions" in data[0]:
                for block in data:
                    add(block.get("topic_id", default_topic_id), block["questions"])
            else:
                add(default_topic_id, data)
        return groups
