from django.core.exceptions import ValidationError
from django.db import models

from . import media as media_utils


class SessionMode(models.TextChoices):
    """Sessiya rejimlari (§4.3). Ishlaydiganlari — `IMPLEMENTED_MODES`."""

    REPEAT_DRILL = "repeat_drill", "Repeat drill (A0)"
    ANTICIPATION_DRILL = "anticipation_drill", "Anticipation drill (A1)"
    SPEED_DRILL = "speed_drill", "Speed drill (A2)"
    GUIDED_CONVERSATION = "guided_conversation", "Guided conversation (B1)"
    FREE_CONVERSATION = "free_conversation", "Free conversation (B2)"
    ADAPTIVE_CONVERSATION = "adaptive_conversation", "Adaptive conversation (erkin suhbat)"
    SHADOWING = "shadowing", "Shadowing (ketidan takrorlash)"
    ROLEPLAY = "roleplay", "Rol suhbat (vaziyat)"
    PLACEMENT = "placement", "Daraja aniqlash (birinchi suhbat)"


IMPLEMENTED_MODES = {
    SessionMode.ANTICIPATION_DRILL,
    SessionMode.GUIDED_CONVERSATION,
    SessionMode.ADAPTIVE_CONVERSATION,
    SessionMode.SHADOWING,
    SessionMode.ROLEPLAY,
    SessionMode.PLACEMENT,
}

# Oqimni Live o'zi boshqaradigan rejimlar: backend savol yozib bermaydi, savol
# banki esa GOALS ro'yxati bo'lib promptga tushadi. Drill rejimlarida aksincha —
# har savol DIRECTOR orqali bittalab beriladi.
FREE_FLOW_MODES = frozenset(
    {
        SessionMode.ADAPTIVE_CONVERSATION,
        SessionMode.SHADOWING,
        SessionMode.ROLEPLAY,
        # Daraja aniqlash ham erkin oqim, va ayniqsa: bu yerda savol banki
        # SKRIPT bo'lsa o'lchov buziladi — model o'quvchi javobiga qarab
        # qiyinlashtirib borishi kerak, aks holda "u nimani biladi" degan
        # savolga javob olinmaydi.
        SessionMode.PLACEMENT,
    }
)


class ContentStatus(models.TextChoices):
    DRAFT = "draft", "Qoralama"
    PUBLISHED = "published", "Nashr qilingan"


class TopicTrack(models.TextChoices):
    """Yo'nalish: mavzu nimani mashq qildiradi.

    To'rttasi ham BIR XIL mashinani ishlatadi (material → sessiya → tahlil).
    Farq fokusda: grammatikada shakl, iborada aynan o'sha ibora, shadowingda
    ohang va sur'at, rol suhbatda esa vaziyatni oxirigacha olib borish.
    """

    GRAMMAR = "grammar", "Grammatika"
    PHRASES = "phrases", "Iboralar"
    SHADOWING = "shadowing", "Shadowing"
    ROLEPLAY = "roleplay", "Rol suhbat"
    # Alohida yo'nalish, va bu ataylab: daraja aniqlash mavzusi grammatika
    # ro'yxatining boshiga tushib qolsa, u birinchi DARS bo'lib ko'rinardi va
    # `unlock_next_topic` uni ketma-ketlikning bir bo'g'ini deb hisoblardi.
    # O'z trekida esa u o'quvchiga ko'rinmaydi ham (§LEARNER_TRACKS).
    PLACEMENT = "placement", "Daraja aniqlash"


# O'quvchiga ko'rinadigan yo'nalishlar. `placement` bu yerda YO'Q: u dars emas,
# bir martalik o'lchov — ro'yxatlarda, progressda va navigatsiyada ko'rinmaydi.
LEARNER_TRACKS = (
    TopicTrack.GRAMMAR,
    TopicTrack.PHRASES,
    TopicTrack.SHADOWING,
    TopicTrack.ROLEPLAY,
)


class Ambience(models.TextChoices):
    """Rol suhbat uchun fon muhiti — klientda protsedural tarzda yasaladi.

    Fayl yuklanmaydi: shovqin brauzerda Web Audio bilan quriladi (shitirlash +
    tasodifiy tovushlar). Shu bois yo'nalish "muhitga tushish" hissini
    beradi-yu, ilova og'irlashmaydi.
    """

    NONE = "none", "Yo'q"
    CAFE = "cafe", "Kafe"
    STREET = "street", "Ko'cha / mashina"
    OFFICE = "office", "Ofis"
    CLINIC = "clinic", "Poliklinika"
    HOTEL = "hotel", "Mehmonxona qabulxonasi"
    SHOP = "shop", "Do'kon"


class QuestionStatus(models.TextChoices):
    DRAFT = "draft", "Qoralama"
    APPROVED = "approved", "Tasdiqlangan"
    REJECTED = "rejected", "Rad etilgan"


class QuestionSource(models.TextChoices):
    GENERATED = "generated", "Generatsiya qilingan"
    MANUAL = "manual", "Qo'lda"


# Darajalar (A0..B2) olib tashlandi. Ilova endi faqat GRAMMATIK MAVZULAR
# ro'yxati: har mavzu bitta strukturani mashq qildiradi. "Daraja" tushunchasi
# kontentda emas, suhbatning O'ZIDA yashaydi — AI o'quvchi qanday gapirsa,
# shunday gapiradi (§apps/practice/adaptive.py, `register`).
DEFAULT_SESSION_MODE = SessionMode.ADAPTIVE_CONVERSATION

# Kontent tillari. O'zbekcha — asos: yangi mavzu avval shu tilda yoziladi,
# ruschasi bo'sh bo'lsa o'quvchi o'zbekchasini ko'radi (bo'sh ekran emas).
BASE_LANGUAGE = "uz"
CONTENT_LANGUAGES = ("uz", "ru")


def localized(obj, field: str, language: str) -> str:
    """`field_ru` bo'lsa o'shani, aks holda `field_uz` ni qaytaradi."""
    if language and language != BASE_LANGUAGE:
        value = (getattr(obj, f"{field}_{language}", "") or "").strip()
        if value:
            return value
    return getattr(obj, f"{field}_{BASE_LANGUAGE}", "") or ""


class Topic(models.Model):
    """Bitta grammatik mavzu. Ro'yxat tekis — `order` global ketma-ketlik.

    `order` — POZITSIYA, `target_structure` — SHAXSIYAT. Ro'yxat orasiga yangi
    mavzu qo'shilganda pozitsiyalar suriladi, shuning uchun seed fayli mavzuni
    aynan `target_structure` bo'yicha topadi (§seed_content buyrug'i).
    """

    track = models.CharField(
        max_length=16,
        choices=TopicTrack.choices,
        default=TopicTrack.GRAMMAR,
        db_index=True,
        help_text="Yo'nalish: grammatika, iboralar, shadowing yoki rol suhbat",
    )
    order = models.IntegerField()
    title_uz = models.CharField(max_length=200)
    title_ru = models.CharField(max_length=200, blank=True, default="")
    title_en = models.CharField(max_length=200, blank=True, default="")
    target_structure = models.CharField(
        max_length=64,
        unique=True,
        help_text="Mashina o'qiy oladigan label, masalan past_simple_affirmative",
    )
    focus_phrase = models.CharField(
        max_length=120,
        blank=True,
        default="",
        help_text=(
            "Faqat iboralar yo'nalishi uchun: o'quvchi aytishi kerak bo'lgan "
            'aynan o\'sha ibora, masalan "look forward to + -ing"'
        ),
    )
    # Bir mavzu bir nechtasiga tayanishi mumkin: shadowing matni ham
    # grammatikadan, ham iboradan foydalanadi — o'quvchi ikkalasiga ham o'tib
    # ketishi kerak, shuning uchun bu ro'yxat, bitta havola emas.
    related_topics = models.ManyToManyField(
        "self",
        symmetrical=False,
        blank=True,
        related_name="linked_from",
        help_text="Bu mavzu qaysi mavzularga tayanadi (grammatika, ibora)",
    )
    session_mode = models.CharField(
        max_length=32,
        choices=SessionMode.choices,
        blank=True,
        default="",
        help_text=f"Bo'sh bo'lsa {DEFAULT_SESSION_MODE} ishlatiladi",
    )
    # --- shadowing: video ---------------------------------------------
    # Video ikki yo'l bilan keladi: admin orqali yuklanadi yoki tashqi manzil
    # beriladi. Video bo'lmasa yo'nalish ishlashdan to'xtamaydi — gapni AI
    # ovozi aytadi, o'lchov esa gapning tabiiy uzunligiga qarab bo'ladi.
    media_file = models.FileField(
        upload_to="shadowing/",
        blank=True,
        null=True,
        help_text="Shadowing videosi (yuklangan fayl)",
    )
    media_url = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="Shadowing videosi (tashqi manzil). Yuklangan fayl ustun turadi",
    )
    # --- rol suhbat: muhit --------------------------------------------
    persona_en = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text='AI kim bo\'ladi, masalan "Rustam, a busy waiter"',
    )
    setting_en = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text='Vaziyat, masalan "lunch rush, every table full"',
    )
    ambience = models.CharField(
        max_length=16,
        choices=Ambience.choices,
        blank=True,
        default="",
        help_text="Klientdagi fon shovqini",
    )
    voice = models.CharField(
        max_length=32,
        blank=True,
        default="",
        help_text="Gemini ovozi (bo'sh bo'lsa umumiy sozlama)",
    )
    status = models.CharField(
        max_length=16, choices=ContentStatus.choices, default=ContentStatus.DRAFT
    )
    max_questions = models.IntegerField(default=10)

    class Meta:
        db_table = "topics"
        ordering = ("track", "order")
        verbose_name = "Mavzu"
        verbose_name_plural = "Mavzular"
        constraints = [
            # Tartib yo'nalish ICHIDA unikal: grammatikaning 1-mavzusi ham,
            # iboralarning 1-mavzusi ham bo'lishi kerak.
            models.UniqueConstraint(fields=("track", "order"), name="uniq_track_order"),
        ]

    def __str__(self):
        return f"{self.order}. {self.title_uz}"

    @property
    def effective_mode(self) -> str:
        return self.session_mode or DEFAULT_SESSION_MODE

    @property
    def media_src(self) -> str:
        """Videoning manzili. Yuklangan fayl tashqi manzildan ustun."""
        if self.media_file:
            return self.media_file.url
        return self.media_url or ""

    @property
    def media_kind(self) -> str:
        """`youtube`, `file` yoki bo'sh — klient shunga qarab pleyer tanlaydi."""
        if self.media_file:
            return media_utils.FILE
        return media_utils.media_kind(self.media_url)

    @property
    def media_ref(self) -> str:
        """YouTube uchun video ID, qolgan holatda manzilning o'zi."""
        if self.media_file:
            return self.media_file.url
        return media_utils.media_ref(self.media_url)

    def approved_questions(self):
        return self.questions.filter(status=QuestionStatus.APPROVED).order_by("order", "id")


class Material(models.Model):
    """Sessiyadan oldingi qisqa material (§4.2). O'qish ≤ 60 soniya."""

    topic = models.OneToOneField(Topic, on_delete=models.CASCADE, related_name="material")
    rule_uz = models.TextField(help_text="Maksimum 2 gap, o'zbekcha")
    rule_ru = models.TextField(blank=True, default="", help_text="Ruscha variant")
    # Ibora uchun shakldan MUHIMROQ savol: qayerda va kimga aytiladi. Bir xil
    # ibora do'st bilan tabiiy, ish xatida esa g'alati eshitilishi mumkin.
    usage_uz = models.TextField(
        blank=True,
        default="",
        help_text="Qayerda va qanday vaziyatda ishlatiladi (asosan iboralar uchun)",
    )
    usage_ru = models.TextField(blank=True, default="", help_text="Ruscha variant")
    examples = models.JSONField(
        default=list,
        help_text='[{"en": "...", "uz": "...", "ru": "..."}] — 3–4 ta misol',
    )

    class Meta:
        db_table = "materials"
        verbose_name = "Material"
        verbose_name_plural = "Materiallar"

    def __str__(self):
        return f"Material: {self.topic}"

    def clean(self):
        if not isinstance(self.examples, list):
            raise ValidationError({"examples": "JSON massiv bo'lishi shart"})
        if not 1 <= len(self.examples) <= 6:
            raise ValidationError({"examples": "3–4 ta misol tavsiya etiladi (1–6 chegara)"})
        for item in self.examples:
            if not isinstance(item, dict) or "en" not in item or "uz" not in item:
                raise ValidationError(
                    {"examples": "Har element {'en': ..., 'uz': ...} bo'lishi shart"}
                )


class Question(models.Model):
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name="questions")
    order = models.IntegerField(default=0)
    question_text = models.TextField()
    canonical_answer = models.TextField()
    answer_variants = models.JSONField(default=list, blank=True)
    elicitation_note = models.TextField(
        blank=True,
        default="",
        help_text="AI'ga ko'rsatma: target strukturani qanday majburlash kerak",
    )
    # Shadowing: shu gap videoning qaysi oralig'ida aytiladi. Klip uzunligi —
    # sur'atni o'lchashdagi ETALON, ya'ni "videodagidek tezlikda" degani aynan
    # shu oraliqqa nisbatan hisoblanadi.
    clip_start_ms = models.IntegerField(null=True, blank=True, help_text="Videoda boshlanish (ms)")
    clip_end_ms = models.IntegerField(null=True, blank=True, help_text="Videoda tugash (ms)")
    status = models.CharField(
        max_length=16, choices=QuestionStatus.choices, default=QuestionStatus.DRAFT
    )
    source = models.CharField(
        max_length=16, choices=QuestionSource.choices, default=QuestionSource.MANUAL
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "questions"
        ordering = ("topic", "order", "id")
        verbose_name = "Savol"
        verbose_name_plural = "Savollar"

    def __str__(self):
        return f"[{self.status}] {self.question_text[:60]}"


class Chunk(models.Model):
    """Yodlanadigan tayyor ibora (§4.2)."""

    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name="chunks")
    text = models.CharField(max_length=200)
    translation_uz = models.CharField(max_length=200)
    translation_ru = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        db_table = "chunks"
        verbose_name = "Chunk"
        verbose_name_plural = "Chunklar"

    def __str__(self):
        return self.text
