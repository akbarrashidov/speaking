"""Daraja tanlovi o'rniga suhbat registri (§apps/practice/adaptive.py)."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0002_email_auth'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='user',
            name='current_level',
        ),
        migrations.AddField(
            model_name='user',
            name='speaking_register',
            field=models.IntegerField(default=2),
        ),
    ]
