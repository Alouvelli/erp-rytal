import secrets
from django.db import migrations, models


def generate_qr_tokens(apps, schema_editor):
    db = schema_editor.connection.alias
    AttendanceSheet = apps.get_model("attendance", "AttendanceSheet")
    for sheet in AttendanceSheet.objects.using(db).all():
        sheet.session_qr_token = secrets.token_urlsafe(32)
        AttendanceSheet.objects.using(db).filter(pk=sheet.pk).update(
            session_qr_token=sheet.session_qr_token
        )


class Migration(migrations.Migration):

    dependencies = [
        ("attendance", "0004_add_subject_progress_and_extra_requests"),
    ]

    operations = [
        # Add field without unique constraint first, populate, then add constraint
        migrations.AddField(
            model_name="attendancesheet",
            name="session_qr_token",
            field=models.CharField(
                blank=True,
                max_length=64,
                default="",
                verbose_name="Token QR séance",
            ),
        ),
        migrations.RunPython(generate_qr_tokens, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="attendancesheet",
            name="session_qr_token",
            field=models.CharField(
                blank=True,
                help_text="Token unique pour le QR code de pointage des présences en séance.",
                max_length=64,
                unique=True,
                verbose_name="Token QR séance",
            ),
        ),
        migrations.AddField(
            model_name="studentattendance",
            name="self_checkin",
            field=models.BooleanField(
                default=False,
                help_text="Vrai si l'étudiant a scanné le QR code de la séance.",
                verbose_name="Auto-pointage",
            ),
        ),
    ]
