"""Testlar `config.settings_test` bilan ishlaydi (pyproject.toml'da belgilangan).

Bu yerda faqat Django yuklanishidan oldin kerak bo'ladigan minimal narsa turadi.
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings_test")
