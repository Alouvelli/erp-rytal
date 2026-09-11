from django.db import migrations, models


def seed_admin_sc_role(apps, schema_editor):
    Role = apps.get_model('accounts', 'Role')
    db = schema_editor.connection.alias
    Role.objects.using(db).get_or_create(
        name='ADMIN_SC',
        defaults={'description': 'Responsable Service à la Communauté'}
    )


def remove_admin_sc_role(apps, schema_editor):
    Role = apps.get_model('accounts', 'Role')
    db = schema_editor.connection.alias
    Role.objects.using(db).filter(name='ADMIN_SC').delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0040_alter_role_name"),
    ]

    operations = [
        migrations.AlterField(
            model_name="role",
            name="name",
            field=models.CharField(
                choices=[
                    ("ADMIN", "Administrateur"),
                    ("INST_ADMIN", "Administrateur d'institut"),
                    ("SI_ADMIN", "Administrateur du SI"),
                    ("ASSISTANTE_DG", "Assistante du Directeur Général"),
                    ("ADMIN_DIRECTION", "Administrateur de direction"),
                    ("ADMIN_DE", "Directeur des études"),
                    ("ADMIN_DAF", "Directeur Administratif et Financier"),
                    ("ADMIN_COM", "Administrateur Direction (COM)"),
                    ("ADMIN_RH", "Directeur des ressources humaines"),
                    ("ADMIN_SC", "Responsable Service à la Communauté"),
                    ("ASSISTANTE_DE", "Assistante Directeur des études"),
                    ("ASSISTANTE_DIRECTION", "Assistante de Direction"),
                    ("CIAQ", "CIAQ"),
                    ("COIP", "COIP"),
                    ("CONTROLEUR", "Contrôleur Interne"),
                    ("RESPONSABLE", "Chef de Département"),
                    ("RESPONSABLE_CLASSE", "Responsable de classe"),
                    ("ADJOINT_RESPONSABLE_CLASSE", "Adjoint du responsable de classe"),
                    ("ASSISTANTE", "Assistante de département"),
                    ("COMPTABLE", "Comptable"),
                    ("TRESORIER_GENERAL", "Trésorier Général"),
                    ("CAISSIER", "Caissier"),
                    ("CHARGE_EXAMENS_CONCOURS", "Chargé des Examens & Concours"),
                    ("ENSEIGNANT", "Enseignant"),
                    ("ETUDIANT", "Étudiant"),
                    ("CONTROLE_ACCUEIL", "Contrôle Accueil"),
                    ("CANDIDAT", "Candidat"),
                ],
                max_length=50,
                unique=True,
            ),
        ),
        migrations.RunPython(seed_admin_sc_role, remove_admin_sc_role),
    ]
