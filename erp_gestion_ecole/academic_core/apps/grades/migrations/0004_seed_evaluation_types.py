from django.db import migrations


EVAL_TYPES = [
    ('CC',         'Contrôle continu',  0.40),
    ('EXAM',       'Examen final',       0.60),
    ('RATTRAPAGE', 'Rattrapage',         0.60),
    ('TP',         'Travaux pratiques',  1.00),
    ('PROJECT',    'Projet',             1.00),
]


def seed_evaluation_types(apps, schema_editor):
    EvaluationType = apps.get_model('grades', 'EvaluationType')
    for code, label, weight in EVAL_TYPES:
        EvaluationType.objects.get_or_create(
            code=code,
            defaults={'label': label, 'weight': weight},
        )


def reverse_seed(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('grades', '0003_lmd_bulletin'),
    ]

    operations = [
        migrations.RunPython(seed_evaluation_types, reverse_seed),
    ]
