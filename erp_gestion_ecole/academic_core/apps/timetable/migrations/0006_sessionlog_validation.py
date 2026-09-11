import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("timetable", "0005_alter_timetableentry_day_of_week"),
    ]

    operations = [
        migrations.AddField(
            model_name="sessionlog",
            name="is_validated",
            field=models.BooleanField(default=False, verbose_name="Validé"),
        ),
        migrations.AddField(
            model_name="sessionlog",
            name="validated_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Validé le"),
        ),
        migrations.AddField(
            model_name="sessionlog",
            name="validated_by",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="validated_session_logs",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Validé par",
            ),
        ),
    ]
