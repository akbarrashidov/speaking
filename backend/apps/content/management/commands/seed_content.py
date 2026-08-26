"""Seed kontent yuklash (§10): grammatik mavzular, bitta tekis ro'yxat."""

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F

from apps.content.models import (
    Chunk,
    Material,
    Question,
    QuestionSource,
    QuestionStatus,
    Topic,
    TopicTrack,
)
from apps.content.validators import check_question

DEFAULT_FIXTURE = Path(settings.BASE_DIR) / "fixtures" / "seed_content.json"

# Qayta raqamlash paytida `order` unikalligi buzilmasligi uchun barcha mavzular
# vaqtincha shu qiymatga suriladi. Ro'yxat orasiga yangi mavzu qo'shilsa,
# eski 7-mavzu 9-o'ringa ko'chishi mumkin — o'sha 9 hali band bo'lishi mumkin.
ORDER_OFFSET = 10_000


class Command(BaseCommand):
    help = "Mavzular, materiallar, savollar va chunklarni yuklaydi (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--file", default=str(DEFAULT_FIXTURE))
        parser.add_argument(
            "--reset-questions",
            action="store_true",
            help="Mavzudagi mavjud savollarni o'chirib, fayldagilarni qayta yozadi",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        path = Path(options["file"])
        if not path.exists():
            raise CommandError(f"Fayl topilmadi: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))

        topics_created = questions_created = warnings = 0

        items = data.get("topics", [])
        for t in items:
            t.setdefault("track", TopicTrack.GRAMMAR)
        self._make_room(items)

        # Bog'lamlar OXIRIDA o'rnatiladi: bog'lanadigan mavzu shu faylning
        # pastida yoki boshqa faylda (grammatika, iboralar) turgan bo'lishi
        # mumkin, ya'ni bu paytda hali yozilmagan bo'lishi mumkin.
        links: list[tuple[str, list[str]]] = []

        for t in items:
            # Mavzu SHAXSIYATI — `target_structure`. Ilgari kalit `order` edi:
            # ro'yxat orasiga yangi mavzu qo'shilganda raqamlar suriladi va
            # eski mavzuning ustiga butunlay boshqa mavzu yozilib ketardi
            # (o'quvchi progressi esa eski ID'ga bog'langan holda qolardi).
            topic, created = Topic.objects.update_or_create(
                target_structure=t["target_structure"],
                defaults={
                    "track": t["track"],
                    "order": t["order"],
                    "focus_phrase": t.get("focus_phrase", ""),
                    # Rol suhbat muhiti va shadowing videosi — ikkalasi ham
                    # ixtiyoriy: bo'lmasa yo'nalish oddiy holatda ishlaydi.
                    "persona_en": t.get("persona_en", ""),
                    "setting_en": t.get("setting_en", ""),
                    "ambience": t.get("ambience", ""),
                    "voice": t.get("voice", ""),
                    "media_url": t.get("media_url", ""),
                    "title_uz": t["title_uz"],
                    "title_ru": t.get("title_ru", ""),
                    "title_en": t.get("title_en", ""),
                    "session_mode": t.get("session_mode", ""),
                    "status": t.get("status", "draft"),
                    "max_questions": t.get("max_questions", 10),
                },
            )
            topics_created += int(created)
            wanted = t.get("related_structures") or (
                [t["related_structure"]] if t.get("related_structure") else []
            )
            if wanted:
                links.append((t["target_structure"], wanted))

            mat = t.get("material")
            if mat:
                Material.objects.update_or_create(
                    topic=topic,
                    defaults={
                        "rule_uz": mat["rule_uz"],
                        "rule_ru": mat.get("rule_ru", ""),
                        "usage_uz": mat.get("usage_uz", ""),
                        "usage_ru": mat.get("usage_ru", ""),
                        "examples": mat["examples"],
                    },
                )

            if t.get("chunks"):
                Chunk.objects.filter(topic=topic).delete()
                Chunk.objects.bulk_create(
                    [
                        Chunk(
                            topic=topic,
                            text=c["text"],
                            translation_uz=c["translation_uz"],
                            translation_ru=c.get("translation_ru", ""),
                        )
                        for c in t["chunks"]
                    ]
                )

            if options["reset_questions"]:
                Question.objects.filter(topic=topic).delete()

            for i, q in enumerate(t.get("questions", []), start=1):
                problems = check_question(q)
                if problems:
                    warnings += 1
                    self.stdout.write(
                        self.style.WARNING(f"  [!] {topic}: savol #{i} - {'; '.join(problems)}")
                    )
                _, q_created = Question.objects.update_or_create(
                    topic=topic,
                    order=i,
                    defaults={
                        "question_text": q["question_text"],
                        "canonical_answer": q["canonical_answer"],
                        "answer_variants": q.get("answer_variants", []),
                        "elicitation_note": q.get("elicitation_note", ""),
                        # Shadowing: gap videoning qaysi oralig'ida.
                        "clip_start_ms": q.get("clip_start_ms"),
                        "clip_end_ms": q.get("clip_end_ms"),
                        "status": q.get("status", QuestionStatus.APPROVED),
                        "source": q.get("source", QuestionSource.MANUAL),
                    },
                )
                questions_created += int(q_created)

        warnings += self._apply_links(links)
        self._settle_untouched(items)

        self.stdout.write(
            self.style.SUCCESS(
                f"Tayyor: {topics_created} yangi mavzu, {questions_created} yangi savol, "
                f"{warnings} ogohlantirish."
            )
        )

    def _tracks(self, items: list[dict]) -> set[str]:
        """Fayl qaysi yo'nalishlarga tegadi. Boshqa yo'nalish qo'l tegmay qoladi."""
        return {t["track"] for t in items}

    def _make_room(self, items: list[dict]) -> None:
        """Fayldagi raqamlar bo'sh maydonga tushishi uchun barchasini yuqoriga suradi."""
        if not items:
            return
        Topic.objects.filter(track__in=self._tracks(items), order__lt=ORDER_OFFSET).update(
            order=F("order") + ORDER_OFFSET
        )

    def _apply_links(self, links: list[tuple[str, list[str]]]) -> int:
        """`related_structures` → `related_topics`. Topilmagani ogohlantirish."""
        missing = 0
        for source, targets in links:
            topic = Topic.objects.filter(target_structure=source).first()
            if not topic:
                continue
            found = []
            for target in targets:
                related = Topic.objects.filter(target_structure=target).first()
                if not related:
                    missing += 1
                    self.stdout.write(
                        self.style.WARNING(f"  [!] {source}: bog'lanadigan '{target}' topilmadi")
                    )
                    continue
                found.append(related)
            # `set` — fayl yagona haqiqat: fayldan olib tashlangan bog'lam
            # bazada ham qolmaydi.
            topic.related_topics.set(found)
        return missing

    def _settle_untouched(self, items: list[dict]) -> None:
        """Faylda yo'q mavzular ro'yxat oxiriga, nisbiy tartibini saqlab qo'yiladi."""
        for track in self._tracks(items):
            leftovers = list(
                Topic.objects.filter(track=track, order__gte=ORDER_OFFSET).order_by("order")
            )
            if not leftovers:
                continue
            next_order = max((t["order"] for t in items if t["track"] == track), default=0) + 1
            for topic in leftovers:
                topic.order = next_order
                topic.save(update_fields=["order"])
                next_order += 1
            self.stdout.write(
                self.style.WARNING(
                    f"  [!] '{track}': faylda yo'q {len(leftovers)} mavzu oxiriga ko'chirildi"
                )
            )
