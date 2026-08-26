"""Mavzular bitta tekis ro'yxatga keltiriladi: A0.1 … B2.5 → 1..N.

Sxemaga tegilmaydi — bu ataylab alohida migratsiya. Postgres ayni tranzaksiyada
qatorlar yangilanib, keyin o'sha jadval ALTER qilinsa "pending trigger events"
xatosi beradi; alohida migratsiya esa o'z tranzaksiyasida commit bo'ladi.
"""

from django.db import migrations


def flatten_topic_order(apps, schema_editor):
    Topic = apps.get_model("content", "Topic")
    topics = list(Topic.objects.order_by("level__order", "order", "id"))
    if not topics:
        return
    # Ikki bosqich: avval hammasi chetga suriladi, keyin yakuniy raqam
    # qo'yiladi. Bir bosqichda (level, order) unikal cheklovi buziladi.
    for i, topic in enumerate(topics, start=1):
        topic.order = 10_000 + i
    Topic.objects.bulk_update(topics, ["order"])
    for i, topic in enumerate(topics, start=1):
        topic.order = i
    Topic.objects.bulk_update(topics, ["order"])


def noop(apps, schema_editor):
    """Orqaga qaytish: raqamlar saqlanadi, daraja tiklanmaydi."""


class Migration(migrations.Migration):
    dependencies = [
        ("content", "0003_adaptive_conversation_default"),
    ]

    operations = [
        migrations.RunPython(flatten_topic_order, noop),
    ]
