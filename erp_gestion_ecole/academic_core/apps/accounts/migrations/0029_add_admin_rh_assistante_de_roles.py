from django.db import migrations, models


NEW_CHOICES = [
    ("ADMIN",                  "Administrateur"),
    ("INST_ADMIN",             "Administrateur d'institut"),
    ("SI_ADMIN",               "Administrateur du SI"),
    ("ASSISTANTE_DG",          "Assistante du Directeur Général"),
    ("ADMIN_DIRECTION",        "Administrateur de direction"),
    ("ADMIN_DE",               "Directeur des études"),
    ("ADMIN_DAF",              "Directeur Administratif et Financier"),
    ("ADMIN_COM",              "Administrateur Direction (COM)"),
    ("ADMIN_RH",               "Directeur des ressources humaines"),
    ("ASSISTANTE_DE",          "Assistante Directeur des études"),
    ("ASSISTANTE_DIRECTION",   "Assistante de Direction"),
    ("CIAQ",                   "CIAQ"),
    ("CONTROLEUR",             "Contrôleur Interne"),
    ("RESPONSABLE",            "Chef de Département"),
    ("RESPONSABLE_CLASSE",     "Responsable de classe"),
    ("ADJOINT_RESPONSABLE_CLASSE", "Adjoint du responsable de classe"),
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
    # IMPORTANT : utiliser explicitement .using(alias) ici. Ce projet a un
    # routeur DB personnalisé (InstitutRouter) qui route les écritures selon
    # un alias thread-local (get_current_db()), inexistant hors requête HTTP.
    # Sans .using(), les objects.get_or_create() de cette migration
    # atterriraient tous sur 'default', même quand la commande migrate
    # personnalisée applique cette migration à une base tenant (db_inst_*) —
    # c'est exactement ce qui s'est produit pour la migration 0026.
    alias = schema_editor.connection.alias
    Role = apps.get_model("accounts", "Role")
    for code, label in [
        ("ADMIN_RH",      "Directeur des ressources humaines"),
        ("ASSISTANTE_DE", "Assistante Directeur des études"),
    ]:
        Role.objects.using(alias).get_or_create(name=code, defaults={"description": label})


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0028_add_adjoint_responsable_classe"),
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
        migrations.RunPython(seed_new_roles, migrations.RunPython.noop),
    ]
