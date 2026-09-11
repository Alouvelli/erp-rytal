from django.db import migrations, models


NEW_CHOICES = [
    ("ADMIN",                  "Administrateur"),
    ("INST_ADMIN",             "Administrateur d'institut"),
    ("SI_ADMIN",               "Administrateur du SI"),
    ("ASSISTANTE_DG",          "Assistante du Directeur Général"),
    ("ADMIN_DIRECTION",        "Administrateur de direction"),
    ("ADMIN_DE",               "Administrateur Direction (DE)"),
    ("ADMIN_DAF",              "Administrateur Direction (DAF)"),
    ("ADMIN_COM",              "Administrateur Direction (COM)"),
    ("ASSISTANTE_DIRECTION",   "Assistante de Direction"),
    ("CIAQ",                   "CIAQ"),
    ("CONTROLEUR",             "Contrôleur Interne"),
    ("RESPONSABLE",            "Chef de Département"),
    ("ASSISTANTE",             "Assistante de département"),
    ("COMPTABLE",              "Comptable"),
    ("TRESORIER_GENERAL",      "Trésorier Général"),
    ("CAISSIER",               "Caissier"),
    ("CHARGE_EXAMENS_CONCOURS","Chargé des Examens & Concours"),
    ("ENSEIGNANT",             "Enseignant"),
    ("ETUDIANT",               "Étudiant"),
    ("CONTROLE_ACCUEIL",       "Contrôle Accueil"),
]


def seed_new_roles(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    for code, label in [
        ("ADMIN_DE",  "Administrateur Direction (DE)"),
        ("ADMIN_DAF", "Administrateur Direction (DAF)"),
        ("ADMIN_COM", "Administrateur Direction (COM)"),
    ]:
        Role.objects.get_or_create(name=code, defaults={"description": label})


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0025_security_event"),
    ]

    operations = [
        # 1. Mettre à jour les choices (inclut le renommage du label RESPONSABLE)
        migrations.AlterField(
            model_name="role",
            name="name",
            field=models.CharField(
                choices=NEW_CHOICES,
                max_length=50,
                unique=True,
            ),
        ),
        # 2. Insérer les 3 nouveaux rôles en base
        migrations.RunPython(seed_new_roles, migrations.RunPython.noop),
    ]
