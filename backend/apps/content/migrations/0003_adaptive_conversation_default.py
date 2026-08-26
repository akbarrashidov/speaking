"""Barcha darajalar erkin suhbatga o'tadi.

Skript rejimlari (`anticipation_drill`, `guided_conversation`) bankdagi savolni
so'zma-so'z berardi: o'quvchi allaqachon aytib bo'lgan narsani qaytadan
so'rardi va bank tugashi bilan sessiya yopilardi. `adaptive_conversation` da
savollar boshlanish nuqtasi, oqimni esa model o'quvchining javobiga qarab
quradi.

Ayrim mavzuni skript rejimida qoldirish kerak bo'lsa — `Topic.session_mode`
maydoni saqlanib qoldi, u darajaning qiymatini bekor qiladi.
"""

from django.db import migrations, models

SCRIPTED = ("anticipation_drill", "guided_conversation", "repeat_drill", "speed_drill")


def to_adaptive(apps, schema_editor):
    Level = apps.get_model("content", "Level")
    Level.objects.filter(default_mode__in=SCRIPTED).update(default_mode="adaptive_conversation")


def back_to_scripted(apps, schema_editor):
    """Orqaga qaytish: A* darajalar drill'ga, B* suhbatga (seed'dagi holat)."""
    Level = apps.get_model("content", "Level")
    Level.objects.filter(code__startswith="A").update(default_mode="anticipation_drill")
    Level.objects.filter(code__startswith="B").update(default_mode="guided_conversation")


class Migration(migrations.Migration):
    dependencies = [
        ("content", "0002_alter_level_default_mode_alter_topic_session_mode"),
    ]

    operations = [
        migrations.AlterField(
            model_name="level",
            name="default_mode",
            field=models.CharField(
                choices=[
                    ("repeat_drill", "Repeat drill (A0)"),
                    ("anticipation_drill", "Anticipation drill (A1)"),
                    ("speed_drill", "Speed drill (A2)"),
                    ("guided_conversation", "Guided conversation (B1)"),
                    ("free_conversation", "Free conversation (B2)"),
                    ("adaptive_conversation", "Adaptive conversation (erkin suhbat)"),
                ],
                default="adaptive_conversation",
                max_length=32,
            ),
        ),
        migrations.RunPython(to_adaptive, back_to_scripted),
    ]
