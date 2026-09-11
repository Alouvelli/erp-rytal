import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def disable_fk(apps, schema_editor):
    if schema_editor.connection.vendor == 'sqlite':
        schema_editor.connection.cursor().execute('PRAGMA foreign_keys = OFF')


def enable_fk(apps, schema_editor):
    if schema_editor.connection.vendor == 'sqlite':
        schema_editor.connection.cursor().execute('PRAGMA foreign_keys = ON')


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ('students', '0006_add_frais_generaux'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(disable_fk, reverse_code=enable_fk),
        migrations.AlterField(
            model_name='enrollment',
            name='validated_by',
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='validated_enrollments',
                to=settings.AUTH_USER_MODEL,
                verbose_name='Validé par',
            ),
        ),
        migrations.RunPython(enable_fk, reverse_code=disable_fk),
    ]
