import uuid

from django.conf import settings
from django.db import models


class SessionStatus(models.TextChoices):
    ACTIVE = "active", "Aktiv"
    PROCESSING = "processing", "Qayta ishlanmoqda"
    DONE = "done", "Tugallangan"
    FAILED = "failed", "Xato"


class EndReason(models.TextChoices):
    COMPLETED = "completed", "Yakunlangan"
    TIME_LIMIT = "time_limit", "Vaqt limiti"
    DISCONNECT = "disconnect", "Uzilish"
    ERROR = "error", "Xato"


class Speaker(models.TextChoices):
    AI = "ai", "AI"
    LEARNER = "learner", "O'quvchi"


class Verdict(models.TextChoices):
    CORRECT = "correct", "To'g'ri"
    INCORRECT = "incorrect", "Noto'g'ri"
    OFF_TOPIC = "off_topic", "Mavzudan tashqari"
    UNINTELLIGIBLE = "unintelligible", "Tushunarsiz"


class Session(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sessions"
    )
    topic = models.ForeignKey("content.Topic", on_delete=models.PROTECT, related_name="sessions")
    mode = models.CharField(max_length=32)
    prompt_version = models.CharField(max_length=32, blank=True, default="")
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    end_reason = models.CharField(max_length=16, choices=EndReason.choices, blank=True, default="")
    duration_seconds = models.IntegerField(default=0)
    time_limit_seconds = models.IntegerField(default=300)
    status = models.CharField(
        max_length=16, choices=SessionStatus.choices, default=SessionStatus.ACTIVE
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # Gemini sarfi (§11 observability)
    usage = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "sessions"
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["user", "-created_at"], name="idx_user_sessions")]
        verbose_name = "Sessiya"
        verbose_name_plural = "Sessiyalar"

    def __str__(self):
        return f"{self.id} · {self.user_id} · {self.topic_id}"


class SessionTurn(models.Model):
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="turns")
    idx = models.IntegerField()
    speaker = models.CharField(max_length=8, choices=Speaker.choices)
    text = models.TextField(blank=True, default="")
    started_at_ms = models.BigIntegerField(default=0)
    ended_at_ms = models.BigIntegerField(default=0)
    question = models.ForeignKey(
        "content.Question", null=True, blank=True, on_delete=models.SET_NULL
    )

    class Meta:
        db_table = "session_turns"
        ordering = ("session", "idx")
        constraints = [
            models.UniqueConstraint(fields=["session", "idx"], name="uniq_session_turn_idx")
        ]
        verbose_name = "Sessiya navbati"
        verbose_name_plural = "Sessiya navbatlari"

    def __str__(self):
        return f"{self.idx} {self.speaker}: {self.text[:40]}"


class Evaluation(models.Model):
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="evaluations")
    question = models.ForeignKey(
        "content.Question", null=True, on_delete=models.SET_NULL, related_name="evaluations"
    )
    attempt = models.IntegerField(default=1)
    verdict = models.CharField(max_length=20, choices=Verdict.choices)
    target_structure_used = models.BooleanField(default=False)
    error_type = models.CharField(max_length=64, blank=True, default="")
    # Coach topgan to'liq xatolar ro'yxati (span/fix/type/severity) — §Faza 3.
    errors = models.JSONField(default=list, blank=True)
    learner_utterance = models.TextField(blank=True, default="")
    recovered_after_model = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "evaluations"
        ordering = ("session", "id")
        verbose_name = "Baholash"
        verbose_name_plural = "Baholashlar"

    def __str__(self):
        return f"{self.question_id} #{self.attempt} → {self.verdict}"


class SessionMetrics(models.Model):
    session = models.OneToOneField(
        Session, on_delete=models.CASCADE, primary_key=True, related_name="metrics"
    )
    talk_time_seconds = models.IntegerField(default=0)
    talk_time_pct = models.FloatField(default=0.0)
    wpm = models.FloatField(default=0.0)
    avg_response_latency_ms = models.IntegerField(default=0)
    questions_total = models.IntegerField(default=0)
    correct_total = models.IntegerField(default=0)
    first_attempt_correct = models.IntegerField(default=0)
    filler_count = models.IntegerField(default=0)
    feedback_summary_uz = models.TextField(blank=True, default="")
    errors = models.JSONField(default=list, blank=True)
    # §Faza 7 — takrorlanuvchi naqshlar, o'sish nuqtasi, keyingi mashqlar,
    # kuchli tomonlar. Naqshlar Python'da sanaladi, izohlar LLM'dan.
    feedback = models.JSONField(default=dict, blank=True)
    stuck_count = models.IntegerField(default=0)
    analysis_ok = models.BooleanField(default=True)
    # Sessiyaning to'liq narxi (Live + coach + tahlil). Optimizatsiyani
    # o'lchash uchun — `apps/practice/cost.py` hisoblaydi.
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    usage_breakdown = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "session_metrics"
        verbose_name = "Sessiya metrikasi"
        verbose_name_plural = "Sessiya metrikalari"

    def __str__(self):
        return f"Metrics {self.session_id}"

    @property
    def first_attempt_accuracy(self) -> float:
        if not self.questions_total:
            return 0.0
        return self.first_attempt_correct / self.questions_total
