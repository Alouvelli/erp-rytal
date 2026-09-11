from django.db import migrations, models


NEW_CHOICES = [
    ("ADMIN",                       "Administrateur"),
    ("INST_ADMIN",                  "Administrateur d'institut"),
    ("SI_ADMIN",                    "Administrateur du SI"),
    ("ASSISTANTE_DG",               "Assistante du Directeur Général"),
    ("ADMIN_DIRECTION",             "Administrateur de direction"),
    ("ADMIN_DE",                    "Administrateur Direction (DE)"),
    ("ADMIN_DAF",                   "Administrateur Direction (DAF)"),
    ("ADMIN_COM",                   "Administrateur Direction (COM)"),
    ("ASSISTANTE_DIRECTION",        "Assistante de Direction"),
    ("CIAQ",                        "CIAQ"),
    ("CONTROLEUR",                  "Contrôleur Interne"),
    ("RESPONSABLE",                 "Chef de Département"),
    ("RESPONSABLE_CLASSE",          "Responsable de classe"),
    ("ADJOINT_RESPONSABLE_CLASSE",  "Adjoint du responsable de classe"),
    ("ASSISTANTE",                  "Assistante de département"),
    ("COMPTABLE",                   "Comptable"),
    ("TRESORIER_GENERAL",           "Trésorier Général"),
    ("CAISSIER",                    "Caissier"),
    ("CHARGE_EXAMENS_CONCOURS",     "Chargé des Examens & Concours"),
    ("ENSEIGNANT",                  "Enseignant"),
    ("ETUDIANT",                    "Étudiant"),
    ("CONTROLE_ACCUEIL",            "Contrôle Accueil"),
]


def seed_new_role(apps, schema_editor):
    # Role n'est pas un modèle "master" (voir db_router.MASTER_MODEL_NAMES) : il
    # vit dans chaque base d'institut. Le manager par défaut route selon le
    # thread-local get_current_db() (absent hors requête HTTP), donc on cible
    # explicitement la base sur laquelle CETTE migration s'applique.
    Role = apps.get_model("accounts", "Role")
    Role.objects.using(schema_editor.connection.alias).get_or_create(
        name="ADJOINT_RESPONSABLE_CLASSE",
        defaults={"description": "Adjoint du responsable de classe"},
    )


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0027_add_responsable_classe"),
    ]

    operations = [
        migrations.AlterField(
            model_name="role",
            name="name",
            field=models.CharField(
                choices=NEW_CHOICES,
                max_length=50,
                unique=True,
            ),
        ),
        migrations.RunPython(seed_new_role, migrations.RunPython.noop),
    ]
