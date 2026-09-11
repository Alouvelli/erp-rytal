from django.db import migrations, models


def seed_assistante_coip_role(apps, schema_editor):
    Role = apps.get_model('accounts', 'Role')
    db = schema_editor.connection.alias
    Role.objects.using(db).get_or_create(
        name='ASSISTANTE_COIP',
        defaults={'description': "Personnel de la Cellule d'Orientation et d'Insertion Professionnelle"}
    )
    # La ligne COIP existe déjà (migration 0040) — on aligne juste sa description
    # avec le nouveau libellé "Responsable COIP" (choices ci-dessous).
    Role.objects.using(db).filter(name='COIP').update(
        description="Responsable de la Cellule d'Orientation et d'Insertion Professionnelle"
    )


def remove_assistante_coip_role(apps, schema_editor):
    Role = apps.get_model('accounts', 'Role')
    db = schema_editor.connection.alias
    Role.objects.using(db).filter(name='ASSISTANTE_COIP').delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0041_add_admin_sc_role"),
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
                    ("COIP", "Responsable COIP"),
                    ("ASSISTANTE_COIP", "Personnel COIP"),
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
        migrations.RunPython(seed_assistante_coip_role, remove_assistante_coip_role),
    ]
