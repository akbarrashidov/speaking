from django.contrib import admin, messages
from django.utils.html import format_html

from .models import (
    Chunk,
    ContentStatus,
    Material,
    Question,
    QuestionStatus,
    Topic,
)
from .validators import check_question


class MaterialInline(admin.StackedInline):
    model = Material
    extra = 0
    max_num = 1


class ChunkInline(admin.TabularInline):
    model = Chunk
    extra = 1


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = (
        "__str__",
        "track",
        "order",
        "target_structure",
        "focus_phrase",
        "related_summary",
        "effective_mode",
        "status",
        "questions_summary",
    )
    list_filter = ("track", "status", "session_mode")
    search_fields = ("title_uz", "title_ru", "title_en", "target_structure", "focus_phrase")
    filter_horizontal = ("related_topics",)
    ordering = ("track", "order")
    inlines = (MaterialInline, ChunkInline)
    actions = ("publish", "unpublish")

    @admin.display(description="Rejim")
    def effective_mode(self, obj):
        return obj.effective_mode

    @admin.display(description="Tayanadi")
    def related_summary(self, obj):
        return ", ".join(t.target_structure for t in obj.related_topics.all()) or "—"

    @admin.display(description="Savollar (tasdiq/jami)")
    def questions_summary(self, obj):
        total = obj.questions.count()
        approved = obj.questions.filter(status=QuestionStatus.APPROVED).count()
        color = "green" if approved else "crimson"
        return format_html('<b style="color:{}">{}</b> / {}', color, approved, total)

    @admin.action(description="Nashr qilish")
    def publish(self, request, queryset):
        blocked = []
        for topic in queryset:
            if not topic.questions.filter(status=QuestionStatus.APPROVED).exists():
                blocked.append(str(topic))
                continue
            if not Material.objects.filter(topic=topic).exists():
                blocked.append(f"{topic} (material yo'q)")
                continue
            topic.status = ContentStatus.PUBLISHED
            topic.save(update_fields=["status"])
        if blocked:
            self.message_user(
                request,
                "Nashr qilinmadi (tasdiqlangan savol yoki material yo'q): " + ", ".join(blocked),
                level=messages.WARNING,
            )

    @admin.action(description="Nashrdan olish")
    def unpublish(self, request, queryset):
        queryset.update(status=ContentStatus.DRAFT)


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    """Review workflow (§9): draft bo'yicha filtr, inline approve/reject."""

    list_display = (
        "question_text_short",
        "topic",
        "order",
        "status",
        "source",
        "quality",
        "canonical_answer",
    )
    list_filter = ("status", "source", "topic")
    search_fields = ("question_text", "canonical_answer")
    list_editable = ("status", "order")
    ordering = ("topic", "order", "id")
    autocomplete_fields = ("topic",)
    actions = ("approve", "reject")
    list_per_page = 50

    @admin.display(description="Savol")
    def question_text_short(self, obj):
        return obj.question_text[:80]

    @admin.display(description="Sifat tekshiruvi")
    def quality(self, obj):
        problems = check_question(
            {
                "question_text": obj.question_text,
                "canonical_answer": obj.canonical_answer,
                "answer_variants": obj.answer_variants,
            }
        )
        if not problems:
            return format_html('<span style="color:green">✓ OK</span>')
        return format_html(
            '<span style="color:crimson" title="{}">⚠ {} ta muammo</span>',
            " | ".join(problems),
            len(problems),
        )

    @admin.action(description="Tasdiqlash")
    def approve(self, request, queryset):
        approved, skipped = 0, []
        for q in queryset:
            problems = check_question(
                {
                    "question_text": q.question_text,
                    "canonical_answer": q.canonical_answer,
                    "answer_variants": q.answer_variants,
                }
            )
            q.status = QuestionStatus.APPROVED
            q.save(update_fields=["status"])
            approved += 1
            if problems:
                skipped.append(f"#{q.id}: {'; '.join(problems)}")
        self.message_user(request, f"{approved} ta savol tasdiqlandi.")
        if skipped:
            self.message_user(
                request,
                "Diqqat — sifat tekshiruvi ogohlantirishlari: " + " || ".join(skipped),
                level=messages.WARNING,
            )

    @admin.action(description="Rad etish")
    def reject(self, request, queryset):
        count = queryset.update(status=QuestionStatus.REJECTED)
        self.message_user(request, f"{count} ta savol rad etildi.")


@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    list_display = ("topic", "rule_uz", "translated")
    search_fields = ("topic__title_uz", "rule_uz", "rule_ru")

    @admin.display(description="Ruschasi bor", boolean=True)
    def translated(self, obj):
        return bool((obj.rule_ru or "").strip())

    autocomplete_fields = ("topic",)


@admin.register(Chunk)
class ChunkAdmin(admin.ModelAdmin):
    list_display = ("text", "translation_uz", "translation_ru", "topic")
    list_filter = ("topic",)
    search_fields = ("text", "translation_uz", "translation_ru")
    autocomplete_fields = ("topic",)
