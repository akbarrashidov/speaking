from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("practice", "0002_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="sessionmetrics",
            name="cost_usd",
            field=models.DecimalField(decimal_places=6, default=0, max_digits=10),
        ),
        migrations.AddField(
            model_name="sessionmetrics",
            name="usage_breakdown",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
