from django.conf import settings
from django.db import models


class TopicStatus(models.TextChoices):
    LOCKED = "locked", "Yopiq"
    ACTIVE = "active", "Ochiq"
    MASTERED = "mastered", "O'zlashtirilgan"


class TopicProgress(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="topic_progress"
    )
    topic = models.ForeignKey("content.Topic", on_delete=models.CASCADE, related_name="progress")
    status = models.CharField(
        max_length=16, choices=TopicStatus.choices, default=TopicStatus.LOCKED
    )
    sessions_count = models.IntegerField(default=0)
    last_accuracy = models.FloatField(null=True, blank=True)
    best_accuracy = models.FloatField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "topic_progress"
        constraints = [models.UniqueConstraint(fields=["user", "topic"], name="uniq_user_topic")]
        verbose_name = "Mavzu progressi"
        verbose_name_plural = "Mavzu progresslari"

    def __str__(self):
        return f"{self.user_id} · {self.topic_id} · {self.status}"


class ErrorLog(models.Model):
    """Spaced repetition manbai (§4.8)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="error_logs"
    )
    topic = models.ForeignKey(
        "content.Topic", null=True, on_delete=models.SET_NULL, related_name="error_logs"
    )
    session = models.ForeignKey(
        "practice.Session",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="error_logs",
    )
    target_structure = models.CharField(max_length=64, blank=True, default="")
    error_type = models.CharField(max_length=64, blank=True, default="")
    learner_utterance = models.TextField(blank=True, default="")
    correction = models.TextField(blank=True, default="")
    review_count = models.IntegerField(default=0)
    next_review_at = models.DateTimeField(null=True, blank=True, db_index=True)
    resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "error_logs"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["user", "resolved", "next_review_at"], name="idx_due_errors"),
        ]
        verbose_name = "Xato yozuvi"
        verbose_name_plural = "Xato yozuvlari"

    def __str__(self):
        return f"{self.error_type}: {self.learner_utterance[:40]}"
