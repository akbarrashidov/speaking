"""Test sozlamalari — tashqi servislarsiz (sqlite, locmem, eager Celery).

CI ham, lokal ishga tushirish ham shu modulni ishlatadi, shuning uchun testlar
env o'zgaruvchilariga bog'liq emas.
"""

# ruff: noqa: F403, F405
from .settings import *  # noqa

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

JWT_SECRET = "test-jwt-secret"
GEMINI_API_KEY = "test-gemini-key"
# `listen.py` haqiqiy HTTP chaqiruv qiladi (kalit yuqorida to'ldirilgan), ya'ni
# testda u har navbatda tarmoqqa chiqib, hold timeout'iga urilardi. Testlar
# zaxira yo'lni — `asr.transcribe` + `coach.evaluate` — mock qiladi.
LISTEN_ENABLED = False
# Bo'sh kalit → LLM tahlili chaqirilmaydi, fallback ishlatiladi.
ANALYSIS_API_KEY = ""
CONTENT_API_KEY = ""

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Testlar ishlab chiqarish qiymatlariga tayanadi — `.env` dagi vaqtinchalik
# sozlamalar (masalan sinov rejimidagi cheksiz kvota) ularga ta'sir qilmasin.
DEV_UNLOCK_ALL = False
SESSION_LIMITS = {
    "free": {"daily_sessions": 1, "duration_seconds": 300},
    "premium": {"daily_sessions": None, "duration_seconds": 900},
}

REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_THROTTLE_RATES": {"user": "10000/min", "anon": "10000/min"},
}

LOGGING["root"]["level"] = "WARNING"
LOGGING["loggers"]["apps"]["level"] = "WARNING"
