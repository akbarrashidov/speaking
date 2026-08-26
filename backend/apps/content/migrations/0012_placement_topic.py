"""Daraja aniqlash mavzusi — kontent emas, INFRASTRUKTURA.

Shu bois u seed faylida emas, migratsiyada: har o'rnatishda mavjud bo'lishi
kerak, aks holda yangi foydalanuvchi ro'yxatdan o'tib, hech qayerga bora
olmaydi.

Savollar — SKRIPT EMAS, zinapoya. Model ularni ketma-ket o'qib bermaydi
(§prompts/modes/placement.md): oson savoldan boshlab, o'quvchi qay yerda
sinishiga qarab yuqoriga chiqadi yoki pastga tushadi. Ro'yxatning vazifasi —
model zinapoyaning har pog'onasini ko'rib turishi.
"""

from django.db import migrations

TARGET_STRUCTURE = "placement_probe"

# (order, savol, kutilgan javob shakli) — zinapoya: hozirgi zamon → o'tgan →
# kelasi → izohli → shartli. Har pog'ona oldingisidan bir qadam qiyin.
QUESTIONS = [
    (1, "What is your name?", "My name is ..."),
    (2, "Where do you live?", "I live in ..."),
    (3, "What do you do every day?", "I work / I study ..."),
    (4, "What did you do yesterday?", "Yesterday I ..."),
    (5, "What are you going to do tomorrow?", "Tomorrow I am going to ..."),
    (6, "Tell me about your family.", "I have ..."),
    (7, "Why do you want to learn English?", "I want to learn English because ..."),
    (
        8,
        "If you could live in any country, where would you live and why?",
        "I would live in ... because ...",
    ),
]


def create_placement_topic(apps, schema_editor):
    Topic = apps.get_model("content", "Topic")
    Question = apps.get_model("content", "Question")

    topic, _ = Topic.objects.update_or_create(
        target_structure=TARGET_STRUCTURE,
        defaults={
            "track": "placement",
            "order": 1,
            "title_uz": "Darajani aniqlash",
            "title_ru": "Определение уровня",
            "title_en": "Placement conversation",
            "session_mode": "placement",
            "status": "published",
            "max_questions": len(QUESTIONS),
        },
    )
    for order, text, answer in QUESTIONS:
        Question.objects.update_or_create(
            topic=topic,
            question_text=text,
            defaults={
                "canonical_answer": answer,
                "elicitation_note": "Daraja aniqlash zinapoyasi — skript emas.",
                "status": "approved",
                "source": "manual",
                "order": order,
            },
        )


def delete_placement_topic(apps, schema_editor):
    Topic = apps.get_model("content", "Topic")
    Topic.objects.filter(target_structure=TARGET_STRUCTURE).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("content", "0011_alter_topic_session_mode_alter_topic_track"),
    ]

    operations = [
        migrations.RunPython(create_placement_topic, delete_placement_topic),
    ]
