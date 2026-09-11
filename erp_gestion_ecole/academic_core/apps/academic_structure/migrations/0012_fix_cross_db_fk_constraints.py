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
        ("academic_structure", "0011_add_institutconfig_db_alias"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(disable_fk, reverse_code=enable_fk),
        migrations.AlterField(
            model_name="abonnementinstitut",
            name="created_by",
            field=models.ForeignKey(
                blank=True, db_constraint=False, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="abonnements_crees", to=settings.AUTH_USER_MODEL,
                verbose_name="Cree par",
            ),
        ),
        migrations.AlterField(
            model_name="bulletinconfig",
            name="updated_by",
            field=models.ForeignKey(
                blank=True, db_constraint=False, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="bulletin_config_updates", to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="department",
            name="admin",
            field=models.OneToOneField(
                blank=True, db_constraint=False, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="administered_department", to=settings.AUTH_USER_MODEL,
                verbose_name="Administrateur de département",
            ),
        ),
        migrations.AlterField(
            model_name="institutconfig",
            name="updated_by",
            field=models.ForeignKey(
                blank=True, db_constraint=False, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="institut_config_updates", to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(enable_fk, reverse_code=disable_fk),
    ]
