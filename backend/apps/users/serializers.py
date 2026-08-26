from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import DeclaredLevel, User


class UserSerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "first_name",
            "display_name",
            "language_code",
            "plan",
            # Klient shu ikkitasiga qarab yo'l tanlaydi: 2-qadam to'ldirilmagan
            # bo'lsa tanishuv ekrani, daraja aniqlanmagan bo'lsa birinchi
            # suhbat, ikkalasi ham bo'lgach — asosiy ilova.
            "onboarding_completed",
            "placement_done",
            "declared_level",
            "speaking_register",
        )


class RegisterSerializer(serializers.Serializer):
    """POST /api/auth/register kirish maydonlari."""

    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(write_only=True, max_length=128)
    first_name = serializers.CharField(required=False, allow_blank=True, max_length=128, default="")
    # Ro'yxatdan o'tishda tanlangan til darhol saqlanadi — birinchi sessiya
    # tahlili ham o'sha tilda chiqsin.
    language = serializers.ChoiceField(choices=("uz", "ru"), required=False, default="uz")

    def validate_email(self, value):
        email = User.objects.normalize_email(value)
        if User.objects.filter(email=email).exists():
            raise serializers.ValidationError("Bu email allaqachon ro'yxatdan o'tgan")
        return email

    def validate_password(self, value):
        try:
            validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc
        return value

    def create(self, validated_data):
        return User.objects.create_user(
            email=validated_data["email"],
            password=validated_data["password"],
            first_name=(validated_data.get("first_name") or "").strip(),
            language_code=validated_data.get("language") or "uz",
        )


class OnboardingSerializer(serializers.Serializer):
    """POST /api/me/onboarding — ro'yxatdan o'tishning 2-qadami.

    Daraja MAJBURIY, izoh esa ixtiyoriy: birinchisi registrga urug' beradi,
    ikkinchisi daraja aniqlash suhbatiga kontekst (§DeclaredLevel).
    """

    declared_level = serializers.ChoiceField(choices=DeclaredLevel.values)
    learning_background = serializers.CharField(
        required=False, allow_blank=True, max_length=1000, default=""
    )

    def save_to(self, user):
        from apps.practice import adaptive

        level = self.validated_data["declared_level"]
        user.declared_level = level
        user.learning_background = (self.validated_data.get("learning_background") or "").strip()
        # Aytilgan daraja — TAXMIN, ya'ni faqat boshlang'ich nuqta. Daraja
        # aniqlash suhbati tugagach uni o'lchangan qiymat almashtiradi
        # (§apps/practice/placement.py).
        user.speaking_register = adaptive.register_from_declared_level(level)
        user.onboarding_completed = True
        user.save(
            update_fields=[
                "declared_level",
                "learning_background",
                "speaking_register",
                "onboarding_completed",
            ]
        )
        return user


class LoginSerializer(serializers.Serializer):
    """POST /api/auth/login kirish maydonlari."""

    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(write_only=True, max_length=128)

    def validate_email(self, value):
        return User.objects.normalize_email(value)


class QuotaSerializer(serializers.Serializer):
    plan = serializers.CharField()
    limit = serializers.IntegerField(allow_null=True)
    used = serializers.IntegerField()
    remaining = serializers.IntegerField(allow_null=True)
    duration_seconds = serializers.IntegerField()
    next_available_at = serializers.DateTimeField(allow_null=True)
