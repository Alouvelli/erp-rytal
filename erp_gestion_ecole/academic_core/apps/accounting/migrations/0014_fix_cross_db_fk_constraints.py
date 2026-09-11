# Custom migration: disable SQLite FK checks during table recreation
# Needed because institute DBs have cross-DB FK references to accounts.User
# which don't resolve within db_inst_* (User lives in default DB only).

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def disable_fk_checks(apps, schema_editor):
    if schema_editor.connection.vendor == 'sqlite':
        schema_editor.connection.cursor().execute('PRAGMA foreign_keys = OFF')


def enable_fk_checks(apps, schema_editor):
    if schema_editor.connection.vendor == 'sqlite':
        schema_editor.connection.cursor().execute('PRAGMA foreign_keys = ON')


class Migration(migrations.Migration):

    atomic = False  # Required to allow PRAGMA outside of a transaction

    dependencies = [
        ("accounting", "0013_frais_mensuel_classe"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(disable_fk_checks, reverse_code=enable_fk_checks),
        migrations.AlterField(
            model_name="academicyeardistribution",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="created_distributions",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="accountingclosure",
            name="closed_by",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="closures",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Clôturé par",
            ),
        ),
        migrations.AlterField(
            model_name="caissepayment",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="caisse_payments_created",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Enregistré par",
            ),
        ),
        migrations.AlterField(
            model_name="comptabiliteconfig",
            name="updated_by",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="comptabilite_configs",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="fraisgenerauxniveau",
            name="updated_by",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="frais_generaux_updates",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Mis à jour par",
            ),
        ),
        migrations.AlterField(
            model_name="fraismensuelclasse",
            name="updated_by",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="frais_mensuel_classe_updates",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Mis à jour par",
            ),
        ),
        migrations.AlterField(
            model_name="hourlyrate",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="created_hourly_rates",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="teacherhonoraire",
            name="validated_by",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="validated_honoraires",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(enable_fk_checks, reverse_code=disable_fk_checks),
    ]
