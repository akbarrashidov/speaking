from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models


class Plan(models.TextChoices):
    FREE = "free", "Free"
    PREMIUM = "premium", "Premium"


class DeclaredLevel(models.TextChoices):
    """O'quvchining O'ZI aytgan darajasi — ro'yxatdan o'tishning 2-qadami.

    Bu daraja EMAS va kontentga ta'sir qilmaydi. Darajalar (A0..B2) tizimdan
    ataylab olib tashlangan: yagona o'lchov `speaking_register` va u nutqdan
    o'lchanadi (§apps/practice/adaptive.py).

    U faqat ikki ish qiladi. Birinchisi — `speaking_register` ga BOSHLANG'ICH
    taxmin beradi, ya'ni birinchi suhbat o'quvchini noldan emas, taxminan
    to'g'ri joydan boshlaydi. Ikkinchisi — daraja aniqlash suhbatiga kontekst
    bo'ladi: "o'zini intermediate deydi" degan ma'lumot bilan model qiyinroq
    savoldan boshlaydi va taxmin to'g'rimi yoki yo'qmi tezroq bilinadi.
    Aytgani bilan o'lchangani to'g'ri kelmasa — O'LCHANGAN g'olib.
    """

    BEGINNER = "beginner", "Hech narsa bilmayman"
    ELEMENTARY = "elementary", "Elementary — oddiy gaplar"
    INTERMEDIATE = "intermediate", "Intermediate — suhbat quraman"
    ADVANCED = "advanced", "Advanced — erkin gapiraman"


class UserManager(BaseUserManager):
    use_in_migrations = True

    def normalize_email(self, email):
        """Django'nikidan farqli: butun manzil kichik harfga keltiriladi."""
        return super().normalize_email(email or "").strip().lower()

    def create_user(self, email, password=None, **extra):
        email = self.normalize_email(email)
        if not email:
            raise ValueError("email majburiy")
        user = self.model(email=email, **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("is_active", True)
        if not extra["is_staff"] or not extra["is_superuser"]:
            raise ValueError("Superuser is_staff va is_superuser bo'lishi shart")
        return self.create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    """Email va parol bilan autentifikatsiya qilinadigan o'quvchi (§6 users)."""

    email = models.EmailField(unique=True, db_index=True)
    first_name = models.CharField(max_length=128, blank=True, default="")
    language_code = models.CharField(max_length=8, blank=True, default="")
    plan = models.CharField(max_length=16, choices=Plan.choices, default=Plan.FREE)
    # AI shu o'quvchi bilan qaysi registrda gapiradi (0..4). Daraja tanlanmaydi
    # va e'lon qilinmaydi — u o'quvchining O'Z nutqidan o'lchanadi va sessiya
    # oxirida shu yerga yoziladi, keyingi suhbat esa shu nuqtadan boshlanadi
    # (§apps/practice/adaptive.py).
    speaking_register = models.IntegerField(default=2)
    # --- ro'yxatdan o'tishning 2-qadami (§DeclaredLevel) ----------------
    declared_level = models.CharField(
        max_length=16,
        choices=DeclaredLevel.choices,
        blank=True,
        default="",
        help_text="O'quvchi o'zi aytgan daraja. Kontentga ta'sir qilmaydi",
    )
    learning_background = models.TextField(
        blank=True,
        default="",
        help_text="Nimalarni biladi, qayerda o'rgangan — o'z so'zlari bilan",
    )
    # Ikkinchi qadam to'ldirildimi. Alohida bayroq kerak, chunki `declared_level`
    # ning bo'shligi javob bermaganini emas, "hech narsa bilmayman" ni ham
    # bildirishi mumkin — ikkisi bir xil emas.
    onboarding_completed = models.BooleanField(default=False)
    # Daraja aniqlash suhbati o'tdimi (§apps/practice/placement.py).
    placement_done = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    last_active_at = models.DateTimeField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        db_table = "users"
        verbose_name = "Foydalanuvchi"
        verbose_name_plural = "Foydalanuvchilar"

    def __str__(self):
        return f"{self.first_name} ({self.email})" if self.first_name else self.email

    @property
    def display_name(self) -> str:
        return self.first_name or self.email.split("@")[0]

    @property
    def is_premium(self) -> bool:
        return self.plan == Plan.PREMIUM


class DailyQuota(models.Model):
    """Kunlik sessiya hisoblagichi (§4.9). date — Asia/Tashkent kalendar kuni."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="quotas")
    date = models.DateField()
    sessions_used = models.IntegerField(default=0)

    class Meta:
        db_table = "daily_quota"
        constraints = [
            models.UniqueConstraint(fields=["user", "date"], name="uniq_user_date_quota")
        ]
        verbose_name = "Kunlik kvota"
        verbose_name_plural = "Kunlik kvotalar"

    def __str__(self):
        return f"{self.user_id} / {self.date}: {self.sessions_used}"
