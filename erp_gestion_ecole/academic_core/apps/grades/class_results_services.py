"""
Rapport Annuel de la Direction — section "Résultats par classe" : une ligne
par classe du département, ventilée Homme/Femme, pour une année académique
et un semestre donnés, scindée en 4 tableaux (reproduit le format de
"TABLEAU DES RESULTATS PAR CLASSE" utilisé par la Direction des Études, avec
en plus l'effet des réclamations de notes isolé dans des tableaux dédiés) :

  - Session Normale
  - Session Normale — après réclamation
  - Session de Rattrapage (avant réclamation)
  - Session de Rattrapage — après réclamation

Réutilise `compute_bulletin_data()` (services.py) — un seul passage par
étudiant, aucune nouvelle logique de calcul de moyenne. Les réclamations
traitées viennent de `GradeComplaint` (voir reclamation_views.py) : leur
seule présence (traitée favorablement) vaut validation pour l'étudiant
concerné, sans recalcul de sa moyenne stockée (même sémantique que le
tableur Excel historique).

Classification (population de base, avant tout effet de réclamation)
----------------------------------------------------------------------
Chaque étudiant ayant composé est classé, dans l'ordre :
  - **Session Normale, Admis** : moyenne du semestre >= 10 ET aucune UE
    n'a été sauvée par une note de rattrapage — par construction, leur
    `semester_average` n'est jamais gonflé par un rattrapage (aucune UE
    `validated_by_rattrapage`), donc la "meilleure moyenne" Session Normale
    reste fiable sans recalcul séparé d'une moyenne "pré-rattrapage".
  - Sinon, l'étudiant n'a **pas** validé en session normale et bascule
    dans la population "Session de Rattrapage", classé en 3 groupes
    mutuellement exclusifs :
      - **Repêchage**   : moyenne >= 10 grâce à au moins une UE validée
        par une note de rattrapage déjà saisie.
      - **Réclamation** : pas repêché, mais une réclamation de note a été
        enregistrée et traitée favorablement (GradeComplaint) pour ce
        semestre.
      - **Résiduel**    : ni l'un ni l'autre, en attente.

Effet des réclamations sur chacun des 4 tableaux
----------------------------------------------------------------------
  - **Session Normale** : n'inclut jamais l'effet d'une réclamation —
    Admis = uniquement les validés "propres" ci-dessus.
  - **Session Normale — après réclamation** : mêmes colonnes que
    ci-dessus, mais un étudiant Non Admis en session normale ayant une
    réclamation traitée sur ce semestre y est promu Admis (compté aussi
    dans la colonne "Réclamation"). La "meilleure moyenne" de ce tableau
    reste identique à celle de la Session Normale : la moyenne stockée
    d'un étudiant promu par réclamation reste, par construction, < 10 et
    ne peut donc pas représenter la meilleure performance de la session.
  - **Session de Rattrapage (avant réclamation)** : Admis = Repêchage
    uniquement ; Non Admis = Réclamation + Résiduel (la réclamation n'a
    pas encore été prise en compte dans ce tableau).
  - **Session de Rattrapage — après réclamation** : Admis = Repêchage +
    Réclamation ; Non Admis = Résiduel uniquement. Mêmes population et
    "meilleure moyenne" que le tableau "avant réclamation" (même effectif
    de classe) — seule la répartition Admis/Non Admis change.

Limites documentées (comme la note historique sur "Effectif ayant
composé") :
  - "Effectif ayant composé" reste une approximation : le système ne
    stocke aucun indicateur "absent" distinct de "pas encore noté" — un
    étudiant est considéré "ayant composé" dès qu'au moins un EC de son
    semestre porte une note d'examen saisie.
  - Côté Session de Rattrapage (les deux variantes), aucune donnée de
    présence propre à l'épreuve de rattrapage n'existe dans l'application :
    "Effectif composé" y est toujours égal à l'effectif total de cette
    session (tous supposés présents), et "Absent examen" y reste à 0.
  - Les abandons (`Enrollment.STATUS_ABANDONED`) ne sont comptés que côté
    Session Normale (les deux variantes, toujours à 0 côté Rattrapage) :
    aucune date fiable ne permet de déterminer si un abandon a eu lieu
    avant ou après la période de rattrapage.
"""
from decimal import Decimal

from academic_core.apps.academic_structure.models import Class
from academic_core.apps.students.models import Enrollment

from .services import compute_bulletin_data
from .models import GradeComplaint

PASS_THRESHOLD = Decimal('10')
GENDER_KEYS = ('M', 'F')

SESSION_COUNTER_KEYS = ('composes', 'abandons', 'admis', 'non_admis', 'absent_examen', 'reclamation')
SESSION_KEYS = ('normale', 'normale_reclamation', 'rattrapage', 'rattrapage_reclamation')


def _empty_counts():
    return {g: 0 for g in GENDER_KEYS}


def _new_session():
    session = {key: _empty_counts() for key in SESSION_COUNTER_KEYS}
    session['effectif_total'] = 0
    session['meilleure_moyenne'] = None
    session['meilleure_moyenne_etudiant'] = None
    return session


def _new_class_row(class_group):
    return {'class_group': class_group, **{key: _new_session() for key in SESSION_KEYS}}


def _session_total(session, key):
    return sum(session[key].values())


def taux(numerator, denominator):
    if not denominator:
        return None
    return _round1(Decimal(numerator) / Decimal(denominator) * Decimal('100'))


def _round1(val):
    return val.quantize(Decimal('0.1'))


def _compute_session_rates(session):
    composes = _session_total(session, 'composes')
    admis = _session_total(session, 'admis')
    session['taux_reussite'] = taux(admis, composes)
    session['taux_h'] = taux(session['admis']['M'], session['composes']['M'])
    session['taux_f'] = taux(session['admis']['F'], session['composes']['F'])


def _accumulate_abandons(row, class_group, academic_year):
    abandons = Enrollment.objects.filter(
        class_group=class_group, academic_year=academic_year,
        status=Enrollment.STATUS_ABANDONED,
    ).select_related('student')
    for enr in abandons:
        g = enr.student.gender if enr.student.gender in GENDER_KEYS else None
        if g:
            row['normale']['abandons'][g] += 1
            row['normale_reclamation']['abandons'][g] += 1


def _aggregate_total(rows):
    total = _new_class_row(None)
    for session_key in SESSION_KEYS:
        total_session = total[session_key]
        for counter_key in SESSION_COUNTER_KEYS:
            for g in GENDER_KEYS:
                total_session[counter_key][g] = sum(r[session_key][counter_key][g] for r in rows)
        total_session['effectif_total'] = sum(r[session_key]['effectif_total'] for r in rows)

        best_row = None
        for r in rows:
            m = r[session_key]['meilleure_moyenne']
            if m is not None and (best_row is None or m > best_row[session_key]['meilleure_moyenne']):
                best_row = r
        if best_row:
            total_session['meilleure_moyenne'] = best_row[session_key]['meilleure_moyenne']
            total_session['meilleure_moyenne_etudiant'] = best_row[session_key]['meilleure_moyenne_etudiant']

        _compute_session_rates(total_session)

    return total


def compute_class_results_table(department, academic_year, semester):
    """
    Retourne {'department', 'academic_year', 'semester', 'rows': [...], 'total': {...}}.
    Une entrée par classe du département dont le niveau LMD correspond à celui
    du semestre choisi, chaque entrée portant 4 sous-dictionnaires (voir
    SESSION_KEYS / docstring du module pour la sémantique).
    """
    classes = list(
        Class.objects.filter(
            program__department=department,
            academic_year=academic_year,
            level=semester.level,
        ).select_related('program', 'level').order_by('name')
    )

    rows = []
    for class_group in classes:
        row = _new_class_row(class_group)
        normale = row['normale']
        normale_recl = row['normale_reclamation']
        rattrapage = row['rattrapage']
        rattrapage_recl = row['rattrapage_reclamation']

        enrollments = list(
            Enrollment.objects.filter(
                class_group=class_group, academic_year=academic_year,
                status=Enrollment.STATUS_VALIDATED,
            ).select_related('student__user')
        )

        complaint_student_ids = set(
            GradeComplaint.objects.filter(
                class_group=class_group, semester=semester,
            ).values_list('student_id', flat=True)
        )

        best_normale_avg = None
        best_normale_student = None
        best_rattrapage_avg = None
        best_rattrapage_student = None

        for enr in enrollments:
            student = enr.student
            g = student.gender if student.gender in GENDER_KEYS else None
            if g is None:
                continue

            normale['effectif_total'] += 1
            normale_recl['effectif_total'] += 1

            data = compute_bulletin_data(student, semester, class_group)
            if data is None:
                normale['absent_examen'][g] += 1
                normale_recl['absent_examen'][g] += 1
                continue

            has_composed = any(
                ec['exam_score'] is not None
                for ue in data['ue_list'] for ec in ue['ec_list']
            )
            if not has_composed:
                normale['absent_examen'][g] += 1
                normale_recl['absent_examen'][g] += 1
                continue

            normale['composes'][g] += 1
            normale_recl['composes'][g] += 1

            semester_avg = data['semester_average']
            is_valide = semester_avg is not None and semester_avg >= PASS_THRESHOLD
            saved_by_rattrapage = any(ue.get('validated_by_rattrapage') for ue in data['ue_list'])
            has_complaint = student.pk in complaint_student_ids

            if is_valide and not saved_by_rattrapage:
                normale['admis'][g] += 1
                normale_recl['admis'][g] += 1
                if best_normale_avg is None or semester_avg > best_normale_avg:
                    best_normale_avg = semester_avg
                    best_normale_student = student
                continue

            # Non validé en session normale -> bascule dans la population Rattrapage.
            normale['non_admis'][g] += 1
            if has_complaint:
                normale_recl['admis'][g] += 1
                normale_recl['reclamation'][g] += 1
            else:
                normale_recl['non_admis'][g] += 1

            rattrapage['effectif_total'] += 1
            rattrapage['composes'][g] += 1
            rattrapage_recl['effectif_total'] += 1
            rattrapage_recl['composes'][g] += 1

            is_repechage = is_valide and saved_by_rattrapage
            if is_repechage:
                rattrapage['admis'][g] += 1
                rattrapage_recl['admis'][g] += 1
            elif has_complaint:
                rattrapage['non_admis'][g] += 1
                rattrapage_recl['admis'][g] += 1
                rattrapage_recl['reclamation'][g] += 1
            else:
                rattrapage['non_admis'][g] += 1
                rattrapage_recl['non_admis'][g] += 1

            if semester_avg is not None and (
                best_rattrapage_avg is None or semester_avg > best_rattrapage_avg
            ):
                best_rattrapage_avg = semester_avg
                best_rattrapage_student = student

        normale['meilleure_moyenne'] = best_normale_avg
        normale['meilleure_moyenne_etudiant'] = best_normale_student
        normale_recl['meilleure_moyenne'] = best_normale_avg
        normale_recl['meilleure_moyenne_etudiant'] = best_normale_student
        rattrapage['meilleure_moyenne'] = best_rattrapage_avg
        rattrapage['meilleure_moyenne_etudiant'] = best_rattrapage_student
        rattrapage_recl['meilleure_moyenne'] = best_rattrapage_avg
        rattrapage_recl['meilleure_moyenne_etudiant'] = best_rattrapage_student

        _accumulate_abandons(row, class_group, academic_year)

        for session_key in SESSION_KEYS:
            _compute_session_rates(row[session_key])

        rows.append(row)

    total = _aggregate_total(rows)

    return {
        'department': department,
        'academic_year': academic_year,
        'semester': semester,
        'rows': rows,
        'total': total,
    }
