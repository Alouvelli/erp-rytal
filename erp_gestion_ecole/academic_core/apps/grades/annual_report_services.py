"""
Rapport Annuel de la Direction Pédagogique — agrégation des résultats
annuels d'un département (toutes ses classes) pour une année académique
donnée, ventilés par genre et par nationalité.

Réutilise `compute_bulletin_data()` (services.py) pour le calcul annuel
par étudiant — pas de nouvelle logique de calcul de moyenne ici, uniquement
de l'agrégation.
"""

from decimal import Decimal

from academic_core.apps.academic_structure.models import Class, Semester
from academic_core.apps.students.models import Enrollment, Student

from .services import compute_bulletin_data

PASS_THRESHOLD = Decimal('10')

# str() forcé : GENDER_CHOICES utilise gettext_lazy(), et les proxys de
# traduction lazy échouent isinstance(value, str) — openpyxl (et certains
# usages JSON) les rejettent sinon avec "Cannot convert ... to Excel".
GENDER_LABELS = {code: str(label) for code, label in Student.GENDER_CHOICES}
NON_RENSEIGNE = 'Non renseigné(e)'


def _blank_counts():
    return {'total': 0, 'admis': 0, 'non_admis': 0, 'non_disponible': 0}


def _classify(annual_average):
    if annual_average is None:
        return 'non_disponible'
    return 'admis' if annual_average >= PASS_THRESHOLD else 'non_admis'


def _accumulate(bucket, student, annual_average):
    status = _classify(annual_average)
    bucket['total'] += 1
    bucket[status] += 1

    gender_label = GENDER_LABELS.get(student.gender, NON_RENSEIGNE) if student.gender else NON_RENSEIGNE
    gender_bucket = bucket['by_gender'].setdefault(gender_label, _blank_counts())
    gender_bucket['total'] += 1
    gender_bucket[status] += 1

    nat_label = student.nationality or 'Non renseignée'
    nat_bucket = bucket['by_nationality'].setdefault(nat_label, _blank_counts())
    nat_bucket['total'] += 1
    nat_bucket[status] += 1


def _new_bucket():
    return {
        'total': 0, 'admis': 0, 'non_admis': 0, 'non_disponible': 0,
        'by_gender': {}, 'by_nationality': {},
    }


def compute_annual_department_report(department, academic_year):
    """
    Retourne un dict :
      - department, academic_year, semester (dernier semestre résolu)
      - classes: [{'class_group':.., 'total':.., 'admis':.., 'non_admis':..,
                    'non_disponible':.., 'by_gender': {...}, 'by_nationality': {...}}, ...]
      - summary: même structure que chaque entrée de `classes`, agrégée sur
        tout le département.
    Un étudiant sans bulletins S1+S2 exploitables est compté dans
    "non_disponible" plutôt que d'être silencieusement ignoré.
    """
    semester = Semester.objects.filter(academic_year=academic_year).order_by('-number').first()

    classes = list(
        Class.objects.filter(program__department=department, academic_year=academic_year)
        .select_related('program', 'level')
        .order_by('name')
    )

    report = {
        'department': department,
        'academic_year': academic_year,
        'semester': semester,
        'classes': [],
        'summary': _new_bucket(),
    }

    if not semester or not classes:
        return report

    enrollments = (
        Enrollment.objects.filter(
            status=Enrollment.STATUS_VALIDATED,
            class_group__in=classes,
            academic_year=academic_year,
        )
        .select_related('student__user', 'class_group')
    )

    enrollments_by_class = {}
    for enr in enrollments:
        enrollments_by_class.setdefault(enr.class_group_id, []).append(enr)

    for class_group in classes:
        class_bucket = _new_bucket()
        for enr in enrollments_by_class.get(class_group.pk, []):
            student = enr.student
            data = compute_bulletin_data(student, semester, class_group=class_group)
            annual_average = data.get('annual_average') if data else None
            _accumulate(class_bucket, student, annual_average)
            _accumulate(report['summary'], student, annual_average)

        report['classes'].append({'class_group': class_group, **class_bucket})

    return report
