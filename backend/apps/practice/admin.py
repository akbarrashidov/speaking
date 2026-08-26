from django.contrib import admin
from django.utils.html import format_html

from .models import Evaluation, Session, SessionMetrics, SessionTurn


class SessionTurnInline(admin.TabularInline):
    model = SessionTurn
    extra = 0
    can_delete = False
    fields = ("idx", "speaker", "text", "started_at_ms", "ended_at_ms", "question")
    readonly_fields = fields
    ordering = ("idx",)

    def has_add_permission(self, request, obj=None):
        return False


class EvaluationInline(admin.TabularInline):
    model = Evaluation
    extra = 0
    can_delete = False
    fields = (
        "question",
        "attempt",
        "verdict",
        "target_structure_used",
        "error_type",
        "learner_utterance",
        "recovered_after_model",
    )
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


class SessionMetricsInline(admin.StackedInline):
    model = SessionMetrics
    extra = 0
    can_delete = False
    readonly_fields = tuple(f.name for f in SessionMetrics._meta.fields if f.name != "session")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    """Sessiya brauzeri (§9): transkript, metrikalar, baholashlar."""

    list_display = (
        "id",
        "user",
        "topic",
        "mode",
        "status",
        "end_reason",
        "duration_seconds",
        "accuracy",
        "cost",
        "started_at",
    )
    list_filter = ("status", "mode", "end_reason", "topic")
    search_fields = ("id", "user__email", "user__first_name", "topic__title_uz")
    date_hierarchy = "created_at"
    readonly_fields = tuple(f.name for f in Session._meta.fields)
    inlines = (SessionMetricsInline, EvaluationInline, SessionTurnInline)

    @admin.display(description="Aniqlik (1-urinish)")
    def accuracy(self, obj):
        m = getattr(obj, "metrics", None)
        if not m or not m.questions_total:
            return "—"
        pct = round(m.first_attempt_accuracy * 100)
        color = "green" if pct >= 80 else ("orange" if pct >= 50 else "crimson")
        return format_html(
            '<b style="color:{}">{}%</b> ({}/{})',
            color,
            pct,
            m.first_attempt_correct,
            m.questions_total,
        )

    @admin.display(description="Narx")
    def cost(self, obj):
        m = getattr(obj, "metrics", None)
        if not m or not m.cost_usd:
            return "—"
        bd = m.usage_breakdown or {}
        return format_html(
            '<span title="Live ${} · LLM ${}">${}</span>',
            bd.get("live_usd", 0),
            bd.get("llm_usd", 0),
            f"{m.cost_usd:.4f}",
        )

    def has_add_permission(self, request):
        return False


@admin.register(Evaluation)
class EvaluationAdmin(admin.ModelAdmin):
    list_display = (
        "session",
        "question",
        "attempt",
        "verdict",
        "error_type",
        "recovered_after_model",
        "created_at",
    )
    list_filter = ("verdict", "error_type", "recovered_after_model")
    search_fields = ("session__id", "learner_utterance")


@admin.register(SessionMetrics)
class SessionMetricsAdmin(admin.ModelAdmin):
    list_display = (
        "session",
        "talk_time_pct",
        "wpm",
        "avg_response_latency_ms",
        "first_attempt_correct",
        "questions_total",
        "filler_count",
        "cost_usd",
        "analysis_ok",
    )
    list_filter = ("analysis_ok",)
    search_fields = ("session__id",)
