"""
LMD Bulletin computation service.

MCC rules:
  - Moy EC  = (2 * EXAM + CC) / 3
  - Moy×Coef = Moy EC * Coef EC
  - Moy UE  = sum(Moy×Coef) / sum(Coef EC)
  - Appréciation EC :
      exam == 0 ou absent  → "A faire"
      Moy EC < 10          → "Non Validé"
      Moy EC >= 10         → "Validé"
  - Appréciation UE :
      ≥1 EC "A faire"      → "EC à composer"
      ≥1 EC "Non Validé"   → "Non Validée"
      tous ECs "Validé"    → "Validée"
  - If RATTRAPAGE exists and > Moy EC : Moy EC = Rattrapage (validated_by_rattrapage)
  - Semester average = sum(Moy UE * UE_credits) / sum(UE_credits)
"""

from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction

from .models import (
    EvaluationType, Grade, Bulletin, BulletinUEResult, BulletinECResult,
    UniteEnseignement,
)
from academic_core.apps.students.models import Enrollment
from academic_core.apps.subjects.models import Subject, natural_sort_key


def _round2(val):
    if val is None:
        return None
    return Decimal(str(val)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _get_mcc_types():
    """Return dict {code: EvaluationType} for CC, EXAM, RATTRAPAGE, DEVOIR1, DEVOIR2."""
    result = {}
    for et in EvaluationType.objects.filter(
        code__in=['CC', 'EXAM', 'RATTRAPAGE', 'DEVOIR1', 'DEVOIR2']
    ):
        result[et.code] = et
    return result


def compute_ec_grade(student, subject, semester):
    """
    Returns dict with EC grade components and appreciation.

    CC = moyenne des notes présentes parmi {Devoir1, Devoir2, TP}, arrondie à
         2 décimales (si une seule des trois est saisie, CC = cette note seule).
    Moy EC = (2*EXAM + CC) / 3
    """
    grades_qs = Grade.objects.filter(
        student=student,
        evaluation__subject=subject,
        evaluation__semester=semester,
    ).select_related('evaluation__evaluation_type')

    d1_score   = None
    d2_score   = None
    tp_score   = None
    exam_score = None
    ratt_score = None

    for g in grades_qs:
        code = g.evaluation.evaluation_type.code
        max_score = g.evaluation.max_score or Decimal('20')
        normalized = (g.score / max_score) * Decimal('20')
        if code == EvaluationType.DEVOIR1:
            d1_score = normalized
        elif code == EvaluationType.DEVOIR2:
            d2_score = normalized
        elif code == EvaluationType.TP:
            tp_score = normalized
        elif code in (EvaluationType.CC, EvaluationType.PROJECT):
            # Compatibilité ascendante : ancien type CC/Projet stocké directement
            if d1_score is None:
                d1_score = normalized
        elif code == EvaluationType.EXAM:
            exam_score = normalized
        elif code == EvaluationType.RATTRAPAGE:
            ratt_score = normalized

    # CC = moyenne des notes présentes parmi {Devoir1, Devoir2, TP}, arrondie à 2 décimales
    cc_components = [s for s in (d1_score, d2_score, tp_score) if s is not None]
    if cc_components:
        cc_average = _round2(sum(cc_components) / Decimal(len(cc_components)))
    else:
        cc_average = None

    # Moy EC = (2*EXAM + CC) / 3  — dégradé si une composante manque
    if cc_average is not None and exam_score is not None:
        final_base = _round2((Decimal('2') * exam_score + cc_average) / Decimal('3'))
    elif exam_score is not None:
        final_base = _round2(exam_score)
    elif cc_average is not None:
        final_base = _round2(cc_average)
    else:
        final_base = None

    # Rattrapage remplace si supérieur
    final = final_base
    if ratt_score is not None:
        if final is None or ratt_score > final:
            final = _round2(ratt_score)

    validated_by_rattrapage = (
        ratt_score is not None
        and ratt_score >= Decimal('10')
        and (final_base is None or ratt_score > final_base)
    )

    # Appréciation EC
    exam_absent = exam_score is None or exam_score == Decimal('0')
    ratt_valid  = ratt_score is not None and ratt_score > Decimal('0')
    if exam_absent and not ratt_valid:
        appreciation = 'A faire'
    elif final is not None and final >= Decimal('10'):
        appreciation = 'Validé'
    else:
        appreciation = 'Non Validé'

    is_validated = appreciation == 'Validé'

    return {
        'd1_score':            _round2(d1_score),
        'd2_score':            _round2(d2_score),
        'tp_score':            _round2(tp_score),
        'cc_average':          cc_average,
        'exam_score':          _round2(exam_score),
        'rattrapage_score':    _round2(ratt_score),
        'final_average':       final,
        'appreciation':        appreciation,
        'is_validated':        is_validated,
        'validated_by_rattrapage': validated_by_rattrapage,
    }


def _appreciation(avg):
    if avg is None:
        return 'A faire'
    if avg >= Decimal('16'):
        return 'Tres Bien'
    if avg >= Decimal('14'):
        return 'Bien'
    if avg >= Decimal('12'):
        return 'Assez Bien'
    if avg >= Decimal('10'):
        return 'Passable'
    return 'Insuffisant'


def _mention(avg):
    if avg is None:
        return ''
    if avg >= Decimal('16'):
        return 'Tres Bien'
    if avg >= Decimal('14'):
        return 'Bien'
    if avg >= Decimal('12'):
        return 'Assez Bien'
    if avg >= Decimal('10'):
        return 'Passable'
    return 'Ajourné'


def _get_saved_sem_data(student, semester):
    """Return saved bulletin summary for another semester, or None."""
    try:
        b = Bulletin.objects.get(student=student, semester=semester)
        return {
            'credits_obtained': b.total_credits_obtained,
            'credits_possible': b.total_credits_possible,
            'average': b.semester_average,
        }
    except Bulletin.DoesNotExist:
        return None


def compute_bulletin_data(student, semester, class_group=None):
    """
    Compute all bulletin data on-the-fly without saving to DB.
    Returns a structured dict suitable for template rendering and PDF generation.
    """
    program = None
    if class_group:
        program = class_group.program
    else:
        enrollment = Enrollment.objects.filter(
            student=student, academic_year=semester.academic_year,
            status=Enrollment.STATUS_VALIDATED,
        ).select_related('class_group__program').first()
        if enrollment:
            class_group = enrollment.class_group
            program = class_group.program if class_group else None

    if not program:
        return None

    # Get UEs for this program/semester
    ues = UniteEnseignement.objects.filter(
        program=program, semester=semester
    ).prefetch_related('subjects').order_by('order', 'code')

    ue_data_list = []
    total_credits_possible = 0
    total_credits_obtained = 0
    semester_weighted = Decimal('0')
    semester_credits_weight = Decimal('0')

    for ue in ues:
        subjects = sorted(ue.subjects.all(), key=lambda s: natural_sort_key(s.code))
        if not subjects:
            continue

        ec_data_list = []
        ue_weighted = Decimal('0')
        ue_coeff_sum = Decimal('0')
        # Crédits UE : somme des crédits des ECs (identique à computed_credits dans maquette_list)
        ue_credits_int = 0

        for subj in subjects:
            ec = compute_ec_grade(student, subj, semester)
            final = ec['final_average']
            coeff = subj.coefficient or Decimal('1')
            credits = subj.credits or 0
            ue_credits_int += int(credits)

            ue_coeff_sum += coeff
            if final is not None:
                ue_weighted += final * coeff

            moy_x_coef = _round2(final * coeff) if final is not None else None
            ec_data_list.append({
                'subject':             subj,
                'd1_score':            ec['d1_score'],
                'd2_score':            ec['d2_score'],
                'tp_score':            ec['tp_score'],
                'cc_average':          ec['cc_average'],
                'exam_score':          ec['exam_score'],
                'rattrapage_score':    ec['rattrapage_score'],
                'final_average':       final,
                'moy_x_coef':          moy_x_coef,
                'appreciation':        ec['appreciation'],
                'is_validated':        ec['is_validated'],
                'validated_by_rattrapage': ec['validated_by_rattrapage'],
                'coeff':               coeff,
                'credits':             credits,
            })

        ue_avg = _round2(ue_weighted / ue_coeff_sum) if ue_coeff_sum > 0 else None

        # Appréciation UE : dès que la moyenne de l'UE est >= 10, l'UE est
        # validée automatiquement, quelles que soient les moyennes des EC qui
        # la composent (règle métier explicite — un EC faible ne doit pas
        # invalider une UE dont la moyenne pondérée est suffisante). Seul un
        # EC encore "A faire" (examen non encore passé) laisse l'UE en
        # attente plutôt que jugée.
        ec_apprs = [ec['appreciation'] for ec in ec_data_list]
        if 'A faire' in ec_apprs:
            ue_appreciation = 'EC à composer'
        elif ue_avg is not None and ue_avg >= Decimal('10'):
            ue_appreciation = 'Validée'
        else:
            ue_appreciation = 'Non Validée'

        ue_validated = ue_appreciation == 'Validée'
        ue_validated_by_rattrapage = ue_validated and any(
            ec['validated_by_rattrapage'] for ec in ec_data_list
        )
        credits_obtained = ue_credits_int if ue_validated else 0

        total_credits_possible += ue_credits_int
        total_credits_obtained += credits_obtained

        if ue_avg is not None:
            semester_weighted += ue_avg * ue_credits_int
            semester_credits_weight += ue_credits_int

        ue_data_list.append({
            'ue':                  ue,
            'ec_list':             ec_data_list,
            'average':             ue_avg,
            'appreciation':        ue_appreciation,
            'is_validated':        ue_validated,
            'validated_by_rattrapage': ue_validated_by_rattrapage,
            'credits_possible':    ue_credits_int,
            'credits_obtained':    credits_obtained,
            'coeff_sum':           ue_coeff_sum,
        })

    semester_avg = None
    if semester_credits_weight > 0:
        semester_avg = _round2(semester_weighted / semester_credits_weight)

    # ── Données cross-semestre pour le récap annuel ───────────────────────────
    from academic_core.apps.academic_structure.models import Semester as Sem
    other_sem = Sem.objects.filter(
        academic_year=semester.academic_year
    ).exclude(pk=semester.pk).order_by('number').first()

    s1_credits_obtained = None
    s1_credits_possible = None
    s1_average = None
    s2_credits_obtained = None
    s2_credits_possible = None
    s2_average = None

    current_number = semester.number

    if current_number == 1:
        # Current = S1, other = S2
        s1_credits_obtained = total_credits_obtained
        s1_credits_possible = total_credits_possible
        s1_average = semester_avg
        # S2 not yet available
        if other_sem:
            saved_s2 = _get_saved_sem_data(student, other_sem)
            if saved_s2:
                s2_credits_obtained = saved_s2['credits_obtained']
                s2_credits_possible = saved_s2['credits_possible']
                s2_average = saved_s2['average']
    else:
        # Current = S2, other = S1
        s2_credits_obtained = total_credits_obtained
        s2_credits_possible = total_credits_possible
        s2_average = semester_avg
        if other_sem:
            saved_s1 = _get_saved_sem_data(student, other_sem)
            if saved_s1:
                s1_credits_obtained = saved_s1['credits_obtained']
                s1_credits_possible = saved_s1['credits_possible']
                s1_average = saved_s1['average']

    # Annual totals
    annual_credits_obtained = None
    annual_credits_possible = None
    annual_average = None

    if s1_credits_obtained is not None and s2_credits_obtained is not None:
        annual_credits_obtained = s1_credits_obtained + s2_credits_obtained
        annual_credits_possible = (s1_credits_possible or 0) + (s2_credits_possible or 0)
        if s1_average is not None and s2_average is not None and (
            (s1_credits_possible or 0) + (s2_credits_possible or 0) > 0
        ):
            s1_w = Decimal(str(s1_average)) * Decimal(str(s1_credits_possible or 0))
            s2_w = Decimal(str(s2_average)) * Decimal(str(s2_credits_possible or 0))
            annual_average = _round2(
                (s1_w + s2_w) / Decimal(str(annual_credits_possible))
            )

    return {
        'student': student,
        'semester': semester,
        'class_group': class_group,
        'program': program,
        'ue_list': ue_data_list,
        'semester_average': semester_avg,
        'mention': _mention(semester_avg),
        'total_credits_obtained': total_credits_obtained,
        'total_credits_possible': total_credits_possible,
        # Annual recap
        'other_semester': other_sem,
        's1_credits_obtained': s1_credits_obtained,
        's1_credits_possible': s1_credits_possible,
        's1_average': s1_average,
        's2_credits_obtained': s2_credits_obtained,
        's2_credits_possible': s2_credits_possible,
        's2_average': s2_average,
        'annual_credits_obtained': annual_credits_obtained,
        'annual_credits_possible': annual_credits_possible,
        'annual_average': annual_average,
        'annual_mention': _mention(annual_average) if annual_average is not None else '',
    }


@transaction.atomic
def save_bulletin(student, semester, class_group, generated_by):
    """Compute and persist a bulletin snapshot."""
    data = compute_bulletin_data(student, semester, class_group)
    if data is None:
        return None

    bulletin, _ = Bulletin.objects.update_or_create(
        student=student, semester=semester,
        defaults={
            'class_group': class_group,
            'status': Bulletin.STATUS_DRAFT,
            'semester_average': data['semester_average'],
            'total_credits_obtained': data['total_credits_obtained'],
            'total_credits_possible': data['total_credits_possible'],
            'mention': data['mention'],
            'generated_by': generated_by,
        }
    )

    # Clear old results
    bulletin.ue_results.all().delete()

    for ue_entry in data['ue_list']:
        ue_result = BulletinUEResult.objects.create(
            bulletin=bulletin,
            ue=ue_entry['ue'],
            average=ue_entry['average'],
            credits_obtained=ue_entry['credits_obtained'],
            is_validated=ue_entry['is_validated'],
            order=ue_entry['ue'].order,
        )
        for ec in ue_entry['ec_list']:
            BulletinECResult.objects.create(
                bulletin=bulletin,
                ue_result=ue_result,
                subject=ec['subject'],
                cc_average=ec['cc_average'],
                exam_score=ec['exam_score'],
                rattrapage_score=ec['rattrapage_score'],
                final_average=ec['final_average'],
                appreciation=ec['appreciation'],
                is_validated=ec['is_validated'],
            )

    return bulletin
