"""Django sozlamalari — AI Speaking Practice platformasi."""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR.parent / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in ("1", "true", "yes", "on")


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def env_int_or_none(name: str, default: int | None) -> int | None:
    """`env_int` kabi, lekin cheksizlikni ham ifodalaydi.

    Bo'sh qiymat yoki `none`/`unlimited` → `None`, ya'ni limit yo'q. Kod ichida
    cheksizlik allaqachon `None` bilan belgilanadi (`SESSION_LIMITS`), shuning
    uchun uni env orqali ham yoqib bo'ladi.
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    if raw.strip().lower() in ("", "none", "unlimited"):
        return None
    try:
        return int(raw)
    except ValueError:
        return default


SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "insecure-dev-key-change-me")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "*").split(",")
CSRF_TRUSTED_ORIGINS = [o for o in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",") if o]

INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "channels",
    "django_celery_results",
    "apps.users",
    "apps.content",
    "apps.practice",
    "apps.progress",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --- Ma'lumotlar bazasi ---------------------------------------------------
# Ishlab chiqarish: PostgreSQL 16. USE_SQLITE=1 faqat lokal test yugurtish uchun.
if env_bool("USE_SQLITE", False):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("POSTGRES_DB", "speaking"),
            "USER": os.getenv("POSTGRES_USER", "speaking"),
            "PASSWORD": os.getenv("POSTGRES_PASSWORD", "speaking"),
            "HOST": os.getenv("POSTGRES_HOST", "postgres"),
            "PORT": env_int("POSTGRES_PORT", 5432),
            "CONN_MAX_AGE": 60,
        }
    }

AUTH_USER_MODEL = "users.User"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

LANGUAGE_CODE = "uz"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
# Kvota kalendar kuni shu zona bo'yicha hisoblanadi (§4.9).
QUOTA_TIMEZONE = os.getenv("QUOTA_TIMEZONE", "Asia/Tashkent")

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Shadowing videolari admin orqali yuklanadi va nginx tomonidan beriladi.
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# --- Redis / Channels / Celery -------------------------------------------
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [REDIS_URL]},
    }
}
if env_bool("USE_INMEMORY_CHANNEL_LAYER", False):
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}
if env_bool("USE_LOCMEM_CACHE", False):
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = "django-db"
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", False)
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = "UTC"

# --- DRF / auth -----------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.users.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.UserRateThrottle",
        "rest_framework.throttling.AnonRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "user": os.getenv("THROTTLE_USER", "120/min"),
        "anon": os.getenv("THROTTLE_ANON", "20/min"),
        # Kirish/ro'yxatdan o'tish — parol tanlashga qarshi qattiqroq chegara.
        "auth": os.getenv("THROTTLE_AUTH", "10/min"),
    },
    "UNAUTHENTICATED_USER": None,
}
JWT_SECRET = os.getenv("JWT_SECRET", SECRET_KEY)
JWT_ALGORITHM = "HS256"
JWT_TTL_SECONDS = env_int("JWT_TTL_SECONDS", 3600)

CORS_ALLOW_ALL_ORIGINS = env_bool("CORS_ALLOW_ALL_ORIGINS", DEBUG)
CORS_ALLOWED_ORIGINS = [o for o in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",") if o]

# --- Gemini Live ----------------------------------------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_LIVE_MODEL = os.getenv("GEMINI_LIVE_MODEL", "gemini-3.1-flash-live-preview")
GEMINI_LIVE_HOST = os.getenv("GEMINI_LIVE_HOST", "generativelanguage.googleapis.com")
GEMINI_VOICE = os.getenv("GEMINI_VOICE", "Aoede")
GEMINI_INPUT_SAMPLE_RATE = env_int("GEMINI_INPUT_SAMPLE_RATE", 16000)
GEMINI_OUTPUT_SAMPLE_RATE = env_int("GEMINI_OUTPUT_SAMPLE_RATE", 24000)
# Kontekst shu chegaradan oshsa sirg'aluvchi oyna siqishni boshlaydi —
# uzun sessiyada har navbat qimmatlashib bormasligi uchun.
GEMINI_COMPRESSION_TRIGGER_TOKENS = env_int("GEMINI_COMPRESSION_TRIGGER_TOKENS", 8000)
# Faqat `*-native-audio` oilasida qo'llanadi; 3.1 Flash Live buni bilmaydi.
GEMINI_AFFECTIVE_DIALOG = env_bool("GEMINI_AFFECTIVE_DIALOG", True)

# --- Narx jadvallari (1M token uchun USD) --------------------------------
# Kalit — model nomining prefiksi; eng uzun mos keluvchi prefiks yutadi.
# Google narxni o'zgartirsa LIVE_PRICING_JSON env orqali kodga tegmasdan yangilanadi.
LIVE_PRICING = {
    "gemini-2.5-flash-native-audio": {
        "text_in": 0.50,
        "audio_in": 3.00,
        "text_out": 2.00,
        "audio_out": 12.00,
    },
    "gemini-3.1-flash-live": {
        "text_in": 0.75,
        "audio_in": 3.00,
        "text_out": 4.50,
        "audio_out": 12.00,
    },
    "default": {"text_in": 0.75, "audio_in": 3.00, "text_out": 4.50, "audio_out": 12.00},
}

# Coach / tahlil / kontent LLM'lari. Kalit — model nomining bir bo'lagi.
TEXT_LLM_PRICING = {
    "gpt-oss-20b": {"text_in": 0.05, "text_out": 0.20},
    "gpt-oss-120b": {"text_in": 0.15, "text_out": 0.60},
    # So'zma-so'z transkript (§asr.py). Audio kirish tokenlari shu qatorda
    # hisoblanadi — Gemini ularni `promptTokenCount` ichida qaytaradi.
    "gemini-2.5-flash": {"text_in": 0.30, "text_out": 2.50},
    "gemini-2.5-flash-lite": {"text_in": 0.10, "text_out": 0.40},
    # Standart tarif (2026-08). Audio kirish qimmatroq ($0.50/1M), lekin bitta
    # chaqiruvda ~2600 token matndan atigi ~40 tasi audio — farq sezilmaydi.
    "gemini-3.1-flash-lite": {"text_in": 0.25, "text_out": 1.50},
    "default": {"text_in": 0.20, "text_out": 0.80},
}


def _merge_pricing_env(table: dict, var: str) -> dict:
    raw = os.getenv(var, "").strip()
    if not raw:
        return table
    try:
        table.update(json.loads(raw))
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return table


_merge_pricing_env(LIVE_PRICING, "LIVE_PRICING_JSON")
_merge_pricing_env(TEXT_LLM_PRICING, "TEXT_LLM_PRICING_JSON")

# --- Sessiyadan keyingi tahlil LLM'i (§2) --------------------------------
ANALYSIS_API_BASE = os.getenv("ANALYSIS_API_BASE", "https://api.fireworks.ai/inference/v1")
ANALYSIS_API_KEY = os.getenv("ANALYSIS_API_KEY", "")
ANALYSIS_MODEL = os.getenv("ANALYSIS_MODEL", "accounts/fireworks/models/gpt-oss-120b")
ANALYSIS_TIMEOUT_SECONDS = env_int("ANALYSIS_TIMEOUT_SECONDS", 60)
# Faqat reasoning modellar uchun (low|medium|high). Bo'sh — yuborilmaydi.
ANALYSIS_REASONING_EFFORT = os.getenv("ANALYSIS_REASONING_EFFORT", "low").strip().lower()

# --- Real vaqtdagi coach LLM'i (§Faza 2) ---------------------------------
# Har o'quvchi javobidan keyin ishlaydi, shuning uchun TEZ va KICHIK model
# kerak: 120b reasoning modeli bu yerga to'g'ri kelmaydi.
# Bo'sh qoldirilsa ANALYSIS_* qiymatlari meros olinadi.
COACH_API_BASE = os.getenv("COACH_API_BASE") or ANALYSIS_API_BASE
COACH_API_KEY = os.getenv("COACH_API_KEY") or ANALYSIS_API_KEY
COACH_MODEL = os.getenv("COACH_MODEL") or "accounts/fireworks/models/gpt-oss-20b"
# Coach kritik yo'lda emas — kechiksa sessiya deterministik davom etadi.
COACH_TIMEOUT_SECONDS = float(os.getenv("COACH_TIMEOUT_SECONDS", "6"))
COACH_REASONING_EFFORT = os.getenv("COACH_REASONING_EFFORT", "low").strip().lower()
# gpt-oss o'ylash tokenlarini ham `completion` hisobiga yozadi — 700 da javob
# JSON o'rtasida kesilib, har 5-chaqiruvdan biri `bad_json` bilan yiqilardi.
COACH_MAX_TOKENS = env_int("COACH_MAX_TOKENS", 1200)
# Sessiyaga tushadigan chaqiruvlar tomi (narx nazorati).
COACH_MAX_CALLS = env_int("COACH_MAX_CALLS", 40)

# --- So'zma-so'z transkript (§asr.py) ------------------------------------
# Gemini Live'ning o'z transkripti o'quvchi gapini to'g'rilab beradi, ya'ni
# grammatik xato coachga yetib bormaydi. O'quvchi audiosi shu model bilan
# qaytadan, "hech narsani tuzatma" ko'rsatmasi ostida o'qiladi.
ASR_ENABLED = env_bool("ASR_ENABLED", True)
# `gemini-2.5-flash` EMAS: u yangi kalitlar uchun yopilgan va `generateContent`
# ga 404 qaytaradi ("no longer available to new users"). Chaqiruv jimgina
# yiqilgani uchun butun so'zma-so'z quvuri o'lik qolib, baholash Live'ning
# xatolarni tuzatib beradigan transkriptida ishlayverardi.
#
# `gemini-3.5-flash` ham EMAS: u `thinkingBudget: 0` bilan JSON'ni yopmasdan
# to'xtaydi (`finishReason=STOP`, lekin oxirgi qavs yo'q) va 15 s gacha cho'ziladi.
# 3.1-flash-lite o'lchovda ~2.4 s va har safar to'g'ri JSON qaytardi.
ASR_MODEL = os.getenv("ASR_MODEL", "gemini-3.1-flash-lite")
ASR_TIMEOUT_SECONDS = float(os.getenv("ASR_TIMEOUT_SECONDS", "8"))
ASR_MAX_TOKENS = env_int("ASR_MAX_TOKENS", 300)
# Bitta navbatdan shuncha soniyadan ortig'i yuborilmaydi (xotira va narx).
ASR_MAX_SECONDS = env_int("ASR_MAX_SECONDS", 45)

# --- Eshitish + baholash bitta chaqiruvda (§listen.py) --------------------
# O'quvchi gapirib bo'lgach model DARHOL javob bermaydi: avval shu chaqiruv
# nima aytilganini va qaysi xato borligini aniqlaydi, keyin modelga navbat
# ochiladi. Ya'ni bu kritik yo'lda — o'quvchi shu vaqt kutib turadi.
LISTEN_ENABLED = env_bool("LISTEN_ENABLED", True)
# Yuqoridagi `ASR_MODEL` bilan bir xil sabablar — va bu chaqiruv kritik yo'lda,
# ya'ni tezlik ham tanlov mezoni: o'quvchi shu vaqt jim kutib turadi.
LISTEN_MODEL = os.getenv("LISTEN_MODEL", "gemini-3.1-flash-lite")
# `TURN_HOLD_MAX_SECONDS` dan KICHIK bo'lishi shart. Teskari bo'lsa (6 > 5)
# sekin chaqiruv har safar hold timeout'i bilan uzilardi: baholash bekor
# qilinib, o'sha navbat tuzatishsiz qolardi — ya'ni 5-6 s oralig'idagi har
# javob jimgina yo'qolardi.
LISTEN_TIMEOUT_SECONDS = float(os.getenv("LISTEN_TIMEOUT_SECONDS", "4.5"))
# Chaqiruv shuncha soniyada javob bermasa — ikkinchi, bir xil so'rov yuboriladi
# va qaysi biri avval qaytsa o'sha olinadi (§listen._post_hedged). Tarmoq yo'li
# beqaror bo'lgani uchun kechikish "dumi" aynan shu bilan kesiladi. 0 — o'chiq.
#
# Chegara odatiy kechikishdan (o'lchovda mediana ~1.9 s) YUQORI bo'lishi shart.
# 1.8 da u deyarli har chaqiruvda ishlab, listen sarfini ikkilantirardi — foyda
# esa faqat haqiqiy "dum"da bor.
LISTEN_HEDGE_AFTER_SECONDS = float(os.getenv("LISTEN_HEDGE_AFTER_SECONDS", "2.6"))
LISTEN_MAX_TOKENS = env_int("LISTEN_MAX_TOKENS", 900)
LISTEN_THINKING_BUDGET = env_int("LISTEN_THINKING_BUDGET", 0)
# Baholash shuncha kutilib javob bermasa — model javob berishga qo'yib
# yuboriladi. Jim qolgan suhbat noto'g'ri tuzatishdan ham yomonroq.
#
# Faqat SKRIPT rejimlarida ishlaydi: erkin suhbatda navbat baholashni umuman
# kutmaydi (§LIVE_FIRST_ENABLED).
TURN_HOLD_MAX_SECONDS = float(os.getenv("TURN_HOLD_MAX_SECONDS", "5"))

# Erkin suhbatda model baholashni KUTMAYDI (§consumer._close_turn_live_first).
#
# Nega. Baholash kritik yo'lda turganda har navbatdan keyin ~2 s jimlik
# bo'lardi: o'quvchi gapirib bo'ladi, keyin kutadi, keyin javob keladi. Sifat
# yaxshi edi — tuzatish modelning O'SHA javobiga qo'shilardi — lekin bu suhbat
# emas, navbatlashib gapirish edi.
#
# Endi xatoni Live modeli o'z qulog'i bilan topadi va o'sha zahoti aytadi
# (§prompts/self_correction.md), coach esa fonda ishlab EKRANDAGI tuzatish
# diffini beradi. Ya'ni ovoz kutmaydi, o'lchov esa yo'qolmaydi.
#
# False qilinsa eski xatti-harakat qaytadi: model coach javobini kutadi.
LIVE_FIRST_ENABLED = env_bool("LIVE_FIRST_ENABLED", True)

# --- Tarjima LLM'i (AI gapining o'zbekchasi ekranda) ----------------------
# Har AI navbatidan keyin bitta juda qisqa chaqiruv: kirish ~40, chiqish ~30
# token. Coach byudjetidan alohida — tarjima tuzatishlarni siqib chiqarmasin.
TRANSLATE_API_BASE = os.getenv("TRANSLATE_API_BASE") or COACH_API_BASE
TRANSLATE_API_KEY = os.getenv("TRANSLATE_API_KEY") or COACH_API_KEY
TRANSLATE_MODEL = os.getenv("TRANSLATE_MODEL") or COACH_MODEL
TRANSLATE_TIMEOUT_SECONDS = float(os.getenv("TRANSLATE_TIMEOUT_SECONDS", "5"))
TRANSLATE_MAX_TOKENS = env_int("TRANSLATE_MAX_TOKENS", 500)
TRANSLATE_ENABLED = env_bool("TRANSLATE_ENABLED", True)

# --- Kontent generatsiya LLM'i (§10) -------------------------------------
CONTENT_API_BASE = os.getenv("CONTENT_API_BASE", ANALYSIS_API_BASE)
CONTENT_API_KEY = os.getenv("CONTENT_API_KEY", ANALYSIS_API_KEY)
CONTENT_MODEL = os.getenv("CONTENT_MODEL", ANALYSIS_MODEL)

# --- Sessiya biznes qoidalari --------------------------------------------
# SINOV REJIMI: barcha mavzu/daraja ochiq, kvota va sarf tomi hisobga olinmaydi.
# Faqat lokal testlash uchun — productionda HAR DOIM 0 bo'lsin.
DEV_UNLOCK_ALL = env_bool("DEV_UNLOCK_ALL", False)

SESSION_LIMITS = {
    "free": {
        "daily_sessions": env_int_or_none("FREE_DAILY_SESSIONS", 1),
        "duration_seconds": env_int("FREE_DURATION_SECONDS", 300),
    },
    "premium": {
        "daily_sessions": None,  # cheksiz
        "duration_seconds": env_int("PREMIUM_DURATION_SECONDS", 900),
    },
}
SESSION_MAX_ATTEMPTS = 2  # §4.4 — model javobgacha maksimum 2 urinish
# Bitta foydalanuvchiga kuniga ketadigan haqiqiy pul tomi (§Faza 8). Sessiya
# soni cheksiz bo'lgan tarifda ham sarf nazoratsiz o'smasligi uchun.
# 0 → tom yo'q.
DAILY_COST_CAP_USD = float(os.getenv("DAILY_COST_CAP_USD", "0"))
SESSION_RESUME_GRACE_SECONDS = env_int("SESSION_RESUME_GRACE_SECONDS", 60)
SESSION_STATE_TTL_SECONDS = env_int("SESSION_STATE_TTL_SECONDS", 7200)

# Routing thresholdlari (§4.7)
# --- shadowing baholash (§apps/practice/shadow.py) ------------------------
# Sur'at "videodagidek"mi: o'quvchi nutqi etalondan shu oraliqda bo'lsa yaxshi.
SHADOW_TEMPO_MIN = float(os.getenv("SHADOW_TEMPO_MIN", "0.80"))
SHADOW_TEMPO_MAX = float(os.getenv("SHADOW_TEMPO_MAX", "1.30"))
# Video biriktirilmagan gap uchun etalon uzunlik shu tezlikdan hisoblanadi
# (so'z/daqiqa) — tabiiy so'zlashuv sur'ati.
SHADOW_REFERENCE_WPM = float(os.getenv("SHADOW_REFERENCE_WPM", "150"))
# Talaffuz izohi — o'quvchi yozuvini modelga eshittirib olinadi. O'chirilsa
# baholash qoladi, faqat izoh o'lchovlardan yoziladi.
SHADOW_PRONUNCIATION_ENABLED = os.getenv("SHADOW_PRONUNCIATION_ENABLED", "1") == "1"
SHADOW_PRONUNCIATION_TIMEOUT = float(os.getenv("SHADOW_PRONUNCIATION_TIMEOUT", "8"))

MASTERY_ACCURACY = float(os.getenv("MASTERY_ACCURACY", "0.80"))
MASTERY_SESSIONS = env_int("MASTERY_SESSIONS", 2)
STRUGGLING_ACCURACY = float(os.getenv("STRUGGLING_ACCURACY", "0.50"))
STRUGGLING_SESSIONS = env_int("STRUGGLING_SESSIONS", 2)

# Spaced repetition zinapoyasi kunlarda (§4.8)
SPACED_REPETITION_LADDER = [1, 3, 7]
SPACED_REPETITION_MAX_INJECT = 3

PROMPTS_DIR = BASE_DIR / "prompts"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "structured": {
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "structured"},
    },
    "root": {"handlers": ["console"], "level": os.getenv("LOG_LEVEL", "INFO")},
    "loggers": {
        "django.db.backends": {"level": "WARNING", "handlers": ["console"], "propagate": False},
        "apps": {
            "level": os.getenv("APP_LOG_LEVEL", "INFO"),
            "handlers": ["console"],
            "propagate": False,
        },
    },
}
