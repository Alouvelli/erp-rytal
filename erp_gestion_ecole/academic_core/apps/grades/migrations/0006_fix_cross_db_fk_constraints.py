import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def disable_fk(apps, schema_editor):
    if schema_editor.connection.vendor == "sqlite":
        schema_editor.connection.cursor().execute("PRAGMA foreign_keys = OFF")


def enable_fk(apps, schema_editor):
    if schema_editor.connection.vendor == "sqlite":
        schema_editor.connection.cursor().execute("PRAGMA foreign_keys = ON")


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ("grades", "0005_add_devoir_types"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(disable_fk, reverse_code=enable_fk),
        migrations.AlterField(
            model_name="bulletin",
            name="generated_by",
            field=models.ForeignKey(
                blank=True, db_constraint=False, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="generated_bulletins", to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="evaluation",
            name="locked_by",
            field=models.ForeignKey(
                blank=True, db_constraint=False, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="locked_evaluations", to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="grade",
            name="entered_by",
            field=models.ForeignKey(
                db_constraint=False, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="entered_grades", to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(enable_fk, reverse_code=disable_fk),
    ]
