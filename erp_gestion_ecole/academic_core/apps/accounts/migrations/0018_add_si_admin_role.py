from django.db import migrations, models


def create_si_admin_role(apps, schema_editor):
    Role = apps.get_model('accounts', 'Role')
    db = schema_editor.connection.alias
    Role.objects.using(db).get_or_create(
        name='SI_ADMIN',
        defaults={'description': 'Administrateur du Système d\'Information — mêmes droits que l\'Administrateur d\'institut'}
    )


def remove_si_admin_role(apps, schema_editor):
    Role = apps.get_model('accounts', 'Role')
    db = schema_editor.connection.alias
    Role.objects.using(db).filter(name='SI_ADMIN').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0017_add_tresorier_caissier_roles'),
    ]

    operations = [
        migrations.AlterField(
            model_name='role',
            name='name',
            field=models.CharField(
                choices=[
                    ('ADMIN', "Administrateur"),
                    ('INST_ADMIN', "Administrateur d'institut"),
                    ('SI_ADMIN', "Administrateur du SI"),
                    ('ASSISTANTE_DG', "Assistante du Directeur Général"),
                    ('ADMIN_DIRECTION', "Administrateur de direction"),
                    ('ASSISTANTE_DIRECTION', "Assistante de Direction"),
                    ('CIAQ', "CIAQ"),
                    ('CONTROLEUR', "Contrôleur Interne"),
                    ('RESPONSABLE', "Administrateur de département"),
                    ('ASSISTANTE', "Assistante de département"),
                    ('COMPTABLE', "Comptable"),
                    ('TRESORIER_GENERAL', "Trésorier Général"),
                    ('CAISSIER', "Caissier"),
                    ('ENSEIGNANT', "Enseignant"),
                    ('ETUDIANT', "Étudiant"),
                ],
                max_length=50,
                unique=True,
            ),
        ),
        migrations.RunPython(create_si_admin_role, remove_si_admin_role),
    ]
