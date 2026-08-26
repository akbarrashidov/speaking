from django.contrib import admin

from .models import ErrorLog, TopicProgress


@admin.register(TopicProgress)
class TopicProgressAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "topic",
        "status",
        "sessions_count",
        "last_accuracy",
        "best_accuracy",
        "updated_at",
    )
    list_filter = ("status", "topic")
    search_fields = ("user__email", "user__first_name", "topic__title_uz")
    autocomplete_fields = ("topic",)


@admin.register(ErrorLog)
class ErrorLogAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "topic",
        "error_type",
        "learner_utterance",
        "correction",
        "review_count",
        "next_review_at",
        "resolved",
    )
    list_filter = ("resolved", "error_type", "topic")
    search_fields = ("user__email", "learner_utterance", "correction")
    autocomplete_fields = ("topic",)
    readonly_fields = ("created_at",)
