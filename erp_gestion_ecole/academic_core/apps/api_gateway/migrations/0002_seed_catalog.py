from django.db import migrations


CATALOG = [
    ('Liste des étudiants', 'ETUDIANTS', '/api/v1/students/',
     "Étudiants de l'institut (identité, matricule, classe) et leurs inscriptions "
     "(sous-ressource /students/<id>/enrollments/). Filtres : recherche par matricule, nom, prénom."),
    ('Fiches d\'émargement', 'EMARGEMENTS', '/api/v1/attendance/sheets/',
     "Fiches d'émargement des séances (statut, contenu de cours, enseignant, classe, module)."),
    ('Présences des étudiants', 'EMARGEMENTS', '/api/v1/attendance/records/',
     "Présence/absence de chaque étudiant par séance."),
    ('Évaluations', 'NOTES', '/api/v1/grades/evaluations/',
     "Évaluations programmées (devoirs, examens) par module et classe."),
    ('Notes', 'NOTES', '/api/v1/grades/grades/',
     "Notes obtenues par les étudiants aux évaluations."),
    ('Moyennes semestrielles', 'NOTES', '/api/v1/grades/averages/',
     "Moyennes semestrielles calculées par étudiant."),
    ('Enseignants', 'ENSEIGNANTS', '/api/v1/teachers/',
     "Enseignants de l'institut (identité, département, modules assignés)."),
    ('Emploi du temps', 'PLANNING', '/api/v1/timetable/entries/',
     "Créneaux de l'emploi du temps (classe, module, enseignant, salle, horaire)."),
]


def seed_catalog(apps, schema_editor):
    APIResource = apps.get_model('api_gateway', 'APIResource')
    db_alias = schema_editor.connection.alias
    for name, functionality, path, description in CATALOG:
        APIResource.objects.using(db_alias).get_or_create(
            endpoint_path=path,
            defaults={'name': name, 'functionality': functionality, 'description': description},
        )


def remove_catalog(apps, schema_editor):
    APIResource = apps.get_model('api_gateway', 'APIResource')
    db_alias = schema_editor.connection.alias
    APIResource.objects.using(db_alias).filter(
        endpoint_path__in=[c[2] for c in CATALOG]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('api_gateway', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_catalog, remove_catalog),
    ]
