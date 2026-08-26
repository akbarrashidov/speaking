import logging

from django.conf import settings
from django.contrib.auth import authenticate
from django.db import IntegrityError
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
    throttle_classes,
)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from . import quota
from .jwt_utils import issue_token
from .serializers import (
    LoginSerializer,
    OnboardingSerializer,
    QuotaSerializer,
    RegisterSerializer,
    UserSerializer,
)

logger = logging.getLogger(__name__)


class AuthThrottle(AnonRateThrottle):
    """Kirish/ro'yxatdan o'tishga IP bo'yicha qattiqroq chegara (brute-force'ga qarshi).

    `ScopedRateThrottle` emas: u scope'ni `view.throttle_scope` dan oladi va
    funksiya-view'larda ishlamaydi.
    """

    scope = "auth"


def _auth_response(user, created=False):
    token, expires_in = issue_token(user)
    return Response(
        {
            "jwt": token,
            "expires_in": expires_in,
            "user": UserSerializer(user).data,
            "created": created,
        },
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([AuthThrottle])
def register(request):
    """POST /api/auth/register — email + parol bilan yangi akkaunt."""
    serializer = RegisterSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(
            {"error": "validation_error", "fields": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        user = serializer.save()
    except IntegrityError:
        # Bir vaqtda ikkita so'rov kelgan holat.
        return Response(
            {
                "error": "validation_error",
                "fields": {"email": ["Bu email allaqachon ro'yxatdan o'tgan"]},
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
    user.last_active_at = timezone.now()
    user.save(update_fields=["last_active_at"])
    return _auth_response(user, created=True)


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([AuthThrottle])
def login(request):
    """POST /api/auth/login — email + parol → JWT."""
    serializer = LoginSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(
            {"error": "validation_error", "fields": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # `authenticate` foydalanuvchi topilmasa ham parolni hisoblaydi — shu bois
    # javob vaqti email mavjudligini oshkor qilmaydi.
    user = authenticate(
        request,
        username=serializer.validated_data["email"],
        password=serializer.validated_data["password"],
    )
    if user is None:
        return Response(
            {"error": "invalid_credentials", "detail": "Email yoki parol noto'g'ri"},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    user.last_active_at = timezone.now()
    user.save(update_fields=["last_active_at"])
    return _auth_response(user)


@api_view(["POST"])
def refresh(request):
    """POST /api/auth/refresh — amaldagi JWT'ni yangisiga almashtiradi."""
    request.user.last_active_at = timezone.now()
    request.user.save(update_fields=["last_active_at"])
    return _auth_response(request.user)


@api_view(["GET"])
def me(request):
    """GET /api/me — profil + plan + qolgan kvota."""
    st = quota.get_status(request.user)
    return Response(
        {
            "user": UserSerializer(request.user).data,
            "quota": QuotaSerializer(st).data,
        }
    )


@api_view(["POST"])
def onboarding(request):
    """POST /api/me/onboarding — ro'yxatdan o'tishning IKKINCHI qadami.

    Alohida so'rov, chunki bu alohida qadam: birinchisida akkaunt yaratiladi
    (email, parol, ism), bu yerda esa o'quvchi o'zi haqida gapiradi. Ikkalasi
    bitta formaga qo'yilsa, ro'yxatdan o'tish tashlab ketiladigan darajada
    uzun bo'lardi.

    Qayta yuborish mumkin: o'quvchi javobini o'zgartirsa, registr ham
    qaytadan hisoblanadi — lekin faqat daraja aniqlash suhbatidan OLDIN
    ma'noli, keyin o'lchangan qiymat ustun turadi.
    """
    serializer = OnboardingSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(
            {"error": "validation_error", "fields": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )
    serializer.save_to(request.user)
    logger.info(
        "onboarding_saved user=%s level=%s register=%s",
        request.user.id,
        request.user.declared_level,
        request.user.speaking_register,
    )
    return Response({"user": UserSerializer(request.user).data})


SUPPORTED_LANGUAGES = ("uz", "ru")


@api_view(["POST"])
def set_language(request):
    """POST /api/me/language — interfeys VA tahlil tili (§translate.py).

    Bu tanlov faqat tugmalar matni emas: AI gapining tarjimasi, sessiya
    yakunidagi xulosa va tavsiyalar ham shu tilda yoziladi.
    """
    language = str(request.data.get("language") or "").strip().lower()
    if language not in SUPPORTED_LANGUAGES:
        return Response(
            {"error": "unsupported_language", "supported": list(SUPPORTED_LANGUAGES)},
            status=status.HTTP_400_BAD_REQUEST,
        )
    request.user.language_code = language
    request.user.save(update_fields=["language_code"])
    return Response({"user": UserSerializer(request.user).data})


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def config(request):
    """Veb ilova uchun ochiq konfiguratsiya."""
    return Response(
        {
            "input_sample_rate": settings.GEMINI_INPUT_SAMPLE_RATE,
            "output_sample_rate": settings.GEMINI_OUTPUT_SAMPLE_RATE,
            "resume_grace_seconds": settings.SESSION_RESUME_GRACE_SECONDS,
        }
    )
