from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("practice", "0003_session_cost"),
    ]

    operations = [
        migrations.AddField(
            model_name="sessionmetrics",
            name="feedback",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="sessionmetrics",
            name="stuck_count",
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name="evaluation",
            name="errors",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
