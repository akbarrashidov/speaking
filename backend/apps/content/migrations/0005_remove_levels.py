"""Darajalar olib tashlanadi — mavzular tekis ro'yxat bo'lib qoladi.

Tartib raqamlari 0004 da global qilib qo'yilgan, shuning uchun `order` ni
unikal qilish xavfsiz.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("content", "0004_flatten_topic_order"),
        ("users", "0003_remove_levels"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="topic",
            name="uniq_level_order",
        ),
        migrations.RemoveField(
            model_name="topic",
            name="level",
        ),
        migrations.AlterModelOptions(
            name="topic",
            options={
                "ordering": ("order",),
                "verbose_name": "Mavzu",
                "verbose_name_plural": "Mavzular",
            },
        ),
        migrations.AlterField(
            model_name="topic",
            name="order",
            field=models.IntegerField(unique=True),
        ),
        migrations.AlterField(
            model_name="topic",
            name="session_mode",
            field=models.CharField(
                blank=True,
                choices=[
                    ("repeat_drill", "Repeat drill (A0)"),
                    ("anticipation_drill", "Anticipation drill (A1)"),
                    ("speed_drill", "Speed drill (A2)"),
                    ("guided_conversation", "Guided conversation (B1)"),
                    ("free_conversation", "Free conversation (B2)"),
                    ("adaptive_conversation", "Adaptive conversation (erkin suhbat)"),
                ],
                default="",
                help_text="Bo'sh bo'lsa adaptive_conversation ishlatiladi",
                max_length=32,
            ),
        ),
        migrations.DeleteModel(
            name="Level",
        ),
    ]
