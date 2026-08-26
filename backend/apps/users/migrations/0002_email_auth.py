"""Telegram autentifikatsiyasidan email + parolga o'tish.

`telegram_id` va `username` olib tashlanadi, o'rniga unique `email` keladi.
Telegram akkauntlarida email yo'q, shuning uchun ularni avtomatik ko'chirib
bo'lmaydi — jadval bo'sh bo'lmasa migratsiya ataylab to'xtaydi.
"""

import django.db.models.deletion
from django.db import migrations, models

import apps.users.models


def check_table_is_empty(apps_registry, schema_editor):
    User = apps_registry.get_model("users", "User")
    count = User.objects.count()
    if count:
        raise RuntimeError(
            f"users jadvalida {count} ta yozuv bor. Telegram akkauntlarini emailga "
            "avtomatik ko'chirib bo'lmaydi (emaili yo'q). Ularni qo'lda ko'chiring "
            "yoki tozalang, so'ng migratsiyani qayta ishga tushiring."
        )


def noop(apps_registry, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(check_table_is_empty, noop),
        migrations.AlterModelManagers(
            name="user",
            managers=[("objects", apps.users.models.UserManager())],
        ),
        migrations.AddField(
            model_name="user",
            name="email",
            field=models.EmailField(db_index=True, default="", max_length=254, unique=True),
            preserve_default=False,
        ),
        migrations.RemoveField(model_name="user", name="telegram_id"),
        migrations.RemoveField(model_name="user", name="username"),
        migrations.AlterField(
            model_name="user",
            name="current_level",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="users",
                to="content.level",
            ),
        ),
    ]
