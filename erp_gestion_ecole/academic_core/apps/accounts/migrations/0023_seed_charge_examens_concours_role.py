from django.db import migrations


def create_role(apps, schema_editor):
    Role = apps.get_model('accounts', 'Role')
    Role.objects.using(schema_editor.connection.alias).get_or_create(
        name='CHARGE_EXAMENS_CONCOURS',
        defaults={'description': "Gestion des Examens & Concours, Notes & Évaluations, "
                                  "Référentiel des Maquettes, Bulletins, Tableau de Conseil, "
                                  "Rattrapages et import des notes — à l'échelle de l'institut."},
    )


def remove_role(apps, schema_editor):
    Role = apps.get_model('accounts', 'Role')
    Role.objects.using(schema_editor.connection.alias).filter(name='CHARGE_EXAMENS_CONCOURS').delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0022_alter_role_name"),
    ]

    operations = [
        migrations.RunPython(create_role, remove_role),
    ]
