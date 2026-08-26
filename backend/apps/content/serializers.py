from django.conf import settings
from rest_framework import serializers

from .models import BASE_LANGUAGE, Chunk, Material, Question, Topic, TopicTrack, localized


def language_of(context) -> str:
    """So'rov qaysi tilda javob kutayotgani — o'quvchi profilidan (§users)."""
    user = getattr(context.get("request"), "user", None)
    return getattr(user, "language_code", "") or BASE_LANGUAGE


class TopicSerializer(serializers.ModelSerializer):
    # Nom o'quvchi tilida keladi. `title_uz` maydoni bazada qoladi (u — asos),
    # lekin API neytral kalit beradi: klient qaysi til ekanini bilishi shart emas.
    title = serializers.SerializerMethodField()
    mode = serializers.CharField(source="effective_mode", read_only=True)
    status = serializers.SerializerMethodField()
    accuracy = serializers.SerializerMethodField()
    sessions_count = serializers.SerializerMethodField()
    questions_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Topic
        fields = (
            "id",
            "track",
            "order",
            "title",
            "title_en",
            "target_structure",
            "focus_phrase",
            "mode",
            "max_questions",
            "status",
            "accuracy",
            "sessions_count",
            "questions_count",
        )

    def get_title(self, obj):
        return localized(obj, "title", language_of(self.context))

    def _progress(self, obj):
        return (self.context.get("progress_map") or {}).get(obj.id)

    def get_status(self, obj):
        p = self._progress(obj)
        if p:
            return "active" if settings.DEV_UNLOCK_ALL and p.status == "locked" else p.status
        return "active" if settings.DEV_UNLOCK_ALL else "locked"

    def get_accuracy(self, obj):
        p = self._progress(obj)
        return p.last_accuracy if p else None

    def get_sessions_count(self, obj):
        p = self._progress(obj)
        return p.sessions_count if p else 0


class ChunkSerializer(serializers.ModelSerializer):
    translation = serializers.SerializerMethodField()

    class Meta:
        model = Chunk
        fields = ("text", "translation")

    def get_translation(self, obj):
        return localized(obj, "translation", language_of(self.context))


class MaterialSerializer(serializers.ModelSerializer):
    topic_id = serializers.IntegerField(source="topic.id", read_only=True)
    title = serializers.SerializerMethodField()
    # Inglizcha nom va dars shakli — ekranda ko'rinadi: ilova NIMANI o'rgatishi
    # birinchi qarashdayoq bilinishi kerak (§frontend: .sentence, .structure).
    title_en = serializers.CharField(source="topic.title_en", read_only=True)
    target_structure = serializers.CharField(source="topic.target_structure", read_only=True)
    track = serializers.CharField(source="topic.track", read_only=True)
    focus_phrase = serializers.CharField(source="topic.focus_phrase", read_only=True)
    media_src = serializers.CharField(source="topic.media_src", read_only=True)
    media_kind = serializers.CharField(source="topic.media_kind", read_only=True)
    media_ref = serializers.CharField(source="topic.media_ref", read_only=True)
    scene = serializers.SerializerMethodField()
    rule = serializers.SerializerMethodField()
    usage = serializers.SerializerMethodField()
    examples = serializers.SerializerMethodField()
    chunks = serializers.SerializerMethodField()
    related = serializers.SerializerMethodField()

    class Meta:
        model = Material
        fields = (
            "topic_id",
            "track",
            "title",
            "title_en",
            "target_structure",
            "focus_phrase",
            "media_src",
            "media_kind",
            "media_ref",
            "scene",
            "rule",
            "usage",
            "examples",
            "chunks",
            "related",
        )

    def get_title(self, obj):
        return localized(obj.topic, "title", language_of(self.context))

    def get_rule(self, obj):
        return localized(obj, "rule", language_of(self.context))

    def get_scene(self, obj):
        """Rol suhbat muhiti — kim bilan va qayerda gaplashiladi."""
        topic = obj.topic
        if not (topic.persona_en or topic.setting_en or topic.ambience):
            return None
        return {
            "persona": topic.persona_en,
            "setting": topic.setting_en,
            "ambience": topic.ambience,
        }

    def get_usage(self, obj):
        """Qayerda ishlatiladi. Grammatik mavzularda bo'sh — blok ko'rinmaydi."""
        return localized(obj, "usage", language_of(self.context))

    def get_related(self, obj):
        """Mavzu nimaga tayanadi — o'quvchi u yerga o'tib ketishi uchun.

        Ro'yxat: shadowing matni ham grammatikadan, ham iboradan foydalanadi.
        Tartib yo'nalish bo'yicha barqaror — ekranda joyi sakramasin.
        """
        language = language_of(self.context)
        order = {
            TopicTrack.GRAMMAR: 0,
            TopicTrack.PHRASES: 1,
            TopicTrack.SHADOWING: 2,
            TopicTrack.ROLEPLAY: 3,
        }
        rows = sorted(
            obj.topic.related_topics.all(),
            key=lambda t: (order.get(t.track, 9), t.order),
        )
        return [
            {
                "topic_id": t.id,
                "track": t.track,
                "title": localized(t, "title", language),
                "focus_phrase": t.focus_phrase,
            }
            for t in rows
        ]

    def get_examples(self, obj):
        """Misol: inglizcha gap + o'quvchi tilidagi tarjimasi (`tr`)."""
        language = language_of(self.context)
        items = []
        for item in obj.examples or []:
            if not isinstance(item, dict):
                continue
            translation = (item.get(language) or "").strip() or (item.get(BASE_LANGUAGE) or "")
            items.append({"en": item.get("en", ""), "tr": translation})
        return items

    def get_chunks(self, obj):
        return ChunkSerializer(obj.topic.chunks.all(), many=True, context=self.context).data


class QuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Question
        fields = (
            "id",
            "order",
            "question_text",
            "canonical_answer",
            "answer_variants",
            "elicitation_note",
            "status",
            "source",
        )
