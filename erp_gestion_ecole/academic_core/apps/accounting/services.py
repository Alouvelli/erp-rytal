from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import List

from django.utils import timezone

from .models import HourlyRate, TeacherHonoraire

MOIS_FR = ['', 'Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin',
           'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre']

# Bande de couleur distincte par mois calendaire (1=Janvier … 12=Décembre),
# pour distinguer visuellement les colonnes-mois des tableaux « Budget
# honoraires » (mensuels/annuels) — le même mois porte toujours la même
# teinte d'une année/table à l'autre. `bg` = fond clair (cellules), `header`
# = teinte plus soutenue (en-tête de colonne, texte sombre lisible dessus).
# Palette pastel cohérente avec les couleurs "maison" déjà utilisées ailleurs
# (vert/bleu/ambre des exports honoraires annuels).
MONTH_COLORS = {
    1:  {'bg': '#DBEAFE', 'header': '#93C5FD'},  # Janvier — bleu
    2:  {'bg': '#E0E7FF', 'header': '#A5B4FC'},  # Février — indigo
    3:  {'bg': '#EDE9FE', 'header': '#C4B5FD'},  # Mars — violet
    4:  {'bg': '#FCE7F3', 'header': '#F9A8D4'},  # Avril — rose
    5:  {'bg': '#FFE4E6', 'header': '#FDA4AF'},  # Mai — rouge rosé
    6:  {'bg': '#FFEDD5', 'header': '#FDBA74'},  # Juin — orange
    7:  {'bg': '#FEF3C7', 'header': '#FCD34D'},  # Juillet — ambre
    8:  {'bg': '#FEF9C3', 'header': '#FDE047'},  # Août — jaune
    9:  {'bg': '#ECFCCB', 'header': '#BEF264'},  # Septembre — citron vert
    10: {'bg': '#D1FAE5', 'header': '#6EE7B7'},  # Octobre — émeraude
    11: {'bg': '#CCFBF1', 'header': '#5EEAD4'},  # Novembre — sarcelle
    12: {'bg': '#CFFAFE', 'header': '#67E8F9'},  # Décembre — cyan
}


def month_color(month_number, key='bg'):
    return MONTH_COLORS.get(month_number, {}).get(key, '#F8FAFC')


def month_schedule_for(academic_year, class_group):
    """[(year, month), ...] chronologique pour une classe sur une année
    académique, à partir d'AcademicYearDistribution (start_month + nb_months),
    avec repli sept.→juin (10 mois) si aucune distribution n'est définie.

    Logique partagée entre le contrôle de paiement étudiant
    (students/views.py::_month_schedule) et le budget honoraires mensuels.
    """
    from .models import AcademicYearDistribution

    if not academic_year:
        return []
    try:
        distrib = AcademicYearDistribution.objects.get(
            academic_year=academic_year, class_group=class_group)
        start_m, nb = distrib.start_month, distrib.nb_months
    except AcademicYearDistribution.DoesNotExist:
        start_m, nb = 9, 10  # Défaut : sept → juin (10 mois)
    start_year = (academic_year.start_date.year
                  if academic_year.start_date else timezone.now().year)
    result = []
    for i in range(nb):
        m = ((start_m - 1 + i) % 12) + 1
        y = start_year + ((start_m - 1 + i) // 12)
        result.append((y, m))
    return result


@dataclass
class PaymentStatus:
    is_cleared: bool          # True = peut imprimer son bulletin
    unpaid_months: List[int]  # Numéros des mois non payés
    paid_months: List[int]    # Numéros des mois payés
    total_due: Decimal        # Montant total dû pour les mois impayés
    frais_mensuel: Decimal    # Mensualité configurée

    @property
    def unpaid_month_labels(self) -> List[str]:
        return [MOIS_FR[m] for m in self.unpaid_months if 1 <= m <= 12]

    @property
    def paid_month_labels(self) -> List[str]:
        return [MOIS_FR[m] for m in self.paid_months if 1 <= m <= 12]


def check_bulletin_payment_clearance(student, academic_year, up_to_date: date | None = None) -> PaymentStatus:
    """
    Vérifie si un étudiant a payé toutes ses mensualités de scolarité dues
    jusqu'à aujourd'hui (ou up_to_date).

    Les mois dus sont EXACTEMENT ceux de la répartition d'année académique de
    la classe de l'étudiant (AcademicYearDistribution — mêmes mois que sur la
    page « Paiement des Mensualités »), et un mois n'est considéré payé que
    s'il existe une échéance (PaymentInstallment) marquée réglée pour ce mois
    précis — la même source de vérité que « Paiement des Mensualités ».

    Retourne un PaymentStatus avec :
      - is_cleared : False si au moins un mois dû n'est pas couvert
      - unpaid_months : liste des mois non payés (numéros 1-12)
      - paid_months : liste des mois payés
      - total_due : montant estimé des impayés
      - frais_mensuel : mensualité configurée (0 si non configurée)
    """
    from academic_core.apps.students.models import Enrollment

    today = up_to_date or date.today()

    # status=VALIDATED (pas is_active=True) : une réinscription ultérieure
    # désactive globalement les inscriptions antérieures de l'étudiant (voir
    # ReinscriptionView.post), y compris celle de `academic_year` — déjà
    # validée et donc censée rester pleinement consultable. `academic_year`
    # étant explicitement fourni par l'appelant, l'inscription pertinente
    # est celle validée POUR CETTE ANNÉE précise, active ou non aujourd'hui.
    enrollment = student.enrollments.filter(
        academic_year=academic_year, status=Enrollment.STATUS_VALIDATED
    ).select_related('class_group__level', 'class_group__frais_mensuel_config').first()

    if not enrollment or not enrollment.class_group:
        return PaymentStatus(
            is_cleared=True, unpaid_months=[], paid_months=[],
            total_due=Decimal('0'), frais_mensuel=Decimal('0'),
        )

    class_group = enrollment.class_group

    # Mensualité configurée (par classe, sinon par niveau) — pour l'estimation du montant dû
    frais_mensuel = Decimal('0')
    fm_classe = None
    try:
        fm_classe = class_group.frais_mensuel_config.frais_mensuel
    except Exception:
        pass
    if fm_classe is not None:
        frais_mensuel = fm_classe
    else:
        try:
            cfg = class_group.level.frais_generaux_config
            if cfg.frais_mensuel:
                frais_mensuel = cfg.frais_mensuel
        except Exception:
            pass

    # Si aucune mensualité configurée → pas de blocage
    if not frais_mensuel or frais_mensuel <= 0:
        return PaymentStatus(
            is_cleared=True, unpaid_months=[], paid_months=[],
            total_due=Decimal('0'), frais_mensuel=Decimal('0'),
        )

    # Mois de la classe selon sa répartition d'année académique (mêmes mois
    # que sur « Paiement des Mensualités »)
    from academic_core.apps.accounting.models import AcademicYearDistribution
    try:
        distrib = AcademicYearDistribution.objects.get(
            academic_year=academic_year, class_group=class_group)
        start_m, nb = distrib.start_month, distrib.nb_months
    except AcademicYearDistribution.DoesNotExist:
        start_m, nb = 9, 10  # Défaut : sept → juin (10 mois)

    start_year = academic_year.start_date.year if academic_year.start_date else today.year
    schedule = []
    for i in range(nb):
        m = ((start_m - 1 + i) % 12) + 1
        y = start_year + ((start_m - 1 + i) // 12)
        schedule.append((y, m))

    # Un mois n'est "dû" que s'il est déjà entamé (échéance <= today ou up_to_date)
    due_months_full = [(y, m) for (y, m) in schedule if date(y, m, 1) <= today]

    if not due_months_full:
        return PaymentStatus(
            is_cleared=True, unpaid_months=[], paid_months=[],
            total_due=Decimal('0'), frais_mensuel=frais_mensuel,
        )

    paid_status = {
        (inst.due_date.year, inst.due_date.month): inst.is_paid
        for inst in enrollment.installments.all()
    }

    unpaid_full = [(y, m) for (y, m) in due_months_full if not paid_status.get((y, m), False)]
    paid_full   = [(y, m) for (y, m) in due_months_full if paid_status.get((y, m), False)]

    return PaymentStatus(
        is_cleared=len(unpaid_full) == 0,
        unpaid_months=[m for (_y, m) in unpaid_full],
        paid_months=[m for (_y, m) in paid_full],
        total_due=frais_mensuel * len(unpaid_full),
        frais_mensuel=frais_mensuel,
    )


def set_hourly_rate(department, level, academic_year, rate_value, user=None):
    """
    Crée ou met à jour le taux horaire (département × niveau × année
    académique) — source de vérité unique déjà utilisée par record_honoraire()
    ci-dessous et par la page dédiée « Taux horaire ». Permet de modifier ce
    même taux depuis d'autres points d'entrée (création d'un EC pour un
    niveau donné, affectation d'un enseignant à cet EC) sans dupliquer la
    logique de résolution department/level/academic_year.

    Ne fait rien si l'un des trois axes de la clé est manquant (ex : EC pas
    encore rattaché à un semestre) ou si `rate_value` est vide.
    """
    if not (department and level and academic_year) or rate_value in (None, ''):
        return None
    rate_obj, created = HourlyRate.objects.update_or_create(
        department=department, level=level, academic_year=academic_year,
        defaults={'rate_per_hour': rate_value},
    )
    if created and user:
        rate_obj.created_by = user
        rate_obj.save(update_fields=['created_by'])
    return rate_obj


def record_honoraire(sheet, validated_by=None):
    """
    Enregistre l'honoraire d'une séance validée.
    Retourne (honoraire, created) ou (None, False) si pas de taux configuré.
    """
    entry   = sheet.timetable_entry
    teacher = entry.teacher
    dept    = entry.class_group.program.department
    level   = entry.class_group.level
    acad_year = entry.semester.academic_year

    if not level:
        return None, False

    try:
        rate_obj = HourlyRate.objects.get(
            department=dept,
            level=level,
            academic_year=acad_year,
        )
    except HourlyRate.DoesNotExist:
        return None, False

    duration = Decimal(str(entry.duration_hours))
    amount   = rate_obj.amount_for_session(duration)

    honoraire, created = TeacherHonoraire.objects.get_or_create(
        attendance_sheet=sheet,
        defaults={
            'teacher':       teacher,
            'department':    dept,
            'academic_year': acad_year,
            'session_date':  sheet.session_date,
            'duration_hours': duration,
            'rate_per_hour': rate_obj.rate_per_hour,
            'amount':        amount,
            'validated_by':  validated_by,
        }
    )
    if created:
        try:
            from .views import sync_honoraires_budget_lines
            sync_honoraires_budget_lines(acad_year)
        except Exception:
            pass  # l'honoraire reste enregistré même si la synchro budget échoue
    return honoraire, created


# ── Finalisation d'une inscription après confirmation de paiement ──────────
# Extraite de accounting/views.py::validation_inscription_detail (action
# 'validate') pour être réutilisable par la vue de validation des preuves de
# paiement du portail public d'admission (academic_core/apps/admissions).
# Comportement strictement identique à l'action 'validate' d'origine : seule
# la source des valeurs change (paramètres explicites au lieu de request.POST).

def _resolve_required_month(enrollment):
    from .models import AcademicYearDistribution
    from academic_core.db_router import get_current_db
    if not enrollment.class_group or not enrollment.academic_year:
        return None
    distrib = AcademicYearDistribution.objects.using(get_current_db()).filter(
        class_group=enrollment.class_group,
        academic_year=enrollment.academic_year,
    ).first()
    if distrib:
        return ((distrib.start_month - 1 + distrib.nb_months - 1) % 12) + 1
    return 6


def regenerate_installments(enrollment):
    """
    (Re)génère l'échéancier de paiement (PaymentInstallment) d'une inscription
    à partir de son état courant (frais/mensualité/mois payés d'avance) —
    supprime les échéances existantes et les recrée. Utilisé à la validation
    initiale, et pour resynchroniser un échéancier devenu incohérent après
    correction du calcul du restant dû (voir Enrollment.net_fees).

    N'appeler que sur des inscriptions sans mensualité réellement déjà
    encaissée au-delà des mois payés d'avance (voir advance_months_list) —
    sinon cela efface un historique de paiement réel.
    """
    from academic_core.apps.students.models import PaymentInstallment
    from datetime import datetime as _dt, date as dt
    import math

    enrollment.installments.all().delete()

    base = enrollment.payment_date
    if isinstance(base, str):
        try:
            base = _dt.strptime(base, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            base = timezone.now().date()
    if not base:
        base = timezone.now().date()

    mensuel_val = enrollment.monthly_installment or Decimal('0')
    months_paid = enrollment.advance_months_list()

    is_boursier    = enrollment.student.is_boursier
    required_month = _resolve_required_month(enrollment) if is_boursier else None

    acad_year   = enrollment.academic_year
    start_year  = (acad_year.start_date.year  if acad_year and acad_year.start_date else base.year)
    start_month = (acad_year.start_date.month if acad_year and acad_year.start_date else 9)

    inst_num = 1

    for month_num, month_amount in months_paid:
        if is_boursier and month_num == required_month:
            amount_for_month = Decimal('0')
        else:
            amount_for_month = month_amount if month_amount is not None else mensuel_val
        if amount_for_month <= 0:
            continue
        month_year = start_year if month_num >= start_month else start_year + 1
        try:
            due = dt(month_year, month_num, 1)
        except ValueError:
            due = base
        PaymentInstallment.objects.create(
            enrollment=enrollment,
            installment_number=inst_num,
            due_date=due,
            amount_expected=amount_for_month,
            amount_paid=amount_for_month,
            paid_date=None,
            is_paid=True,
            notes="Payé à l'inscription",
        )
        inst_num += 1

    remaining = enrollment.bourse_remaining_amount if is_boursier else enrollment.remaining_amount
    monthly   = enrollment.monthly_installment
    if remaining and monthly and monthly > 0 and not is_boursier:
        nb = math.ceil(float(remaining) / float(monthly))
        year, month = base.year, base.month
        for _ in range(nb):
            month += 1
            if month > 12:
                month = 1
                year += 1
            amount = min(monthly, remaining)
            remaining -= amount
            PaymentInstallment.objects.create(
                enrollment=enrollment,
                installment_number=inst_num,
                due_date=dt(year, month, 1),
                amount_expected=amount,
            )
            inst_num += 1


def finalize_enrollment_payment(enrollment, *, payment_date, validated_by,
                                 total_fees=None, frais_generaux=None,
                                 monthly_installment=None, notes='', request=None):
    """
    Confirme le paiement et valide l'inscription : crée le CaissePayment,
    génère l'échéancier complet, active Student.current_class/User.is_active,
    notifie l'étudiant. Retourne le CaissePayment créé.

    `payment_date` : date ou chaîne 'YYYY-MM-DD'. `total_fees`/`frais_generaux`/
    `monthly_installment` : Decimal ou None (repli sur la config classe/niveau,
    comme l'action 'validate' d'origine).
    """
    from academic_core.apps.students.models import Enrollment
    from .models import CaissePayment, FraisGenerauxNiveau, FraisMensuelClasse
    from academic_core.db_router import get_current_db

    if total_fees is not None:
        enrollment.total_fees = total_fees
    if frais_generaux is not None:
        enrollment.frais_generaux = frais_generaux
    if monthly_installment is not None and not enrollment.student.is_boursier:
        enrollment.monthly_installment = monthly_installment
    enrollment.payment_date = payment_date
    if notes:
        enrollment.notes = notes
    enrollment.status       = Enrollment.STATUS_VALIDATED
    enrollment.is_active    = True
    enrollment.validated_by = validated_by
    enrollment.validated_at = timezone.now()
    enrollment.save()

    if not enrollment.payment_reference:
        enrollment.payment_reference = Enrollment.generate_payment_reference()
        enrollment.save(update_fields=['payment_reference'])

    _db      = get_current_db()
    _level   = enrollment.class_group.level if enrollment.class_group else None
    _niv_cfg = None
    if _level:
        try:
            _niv_cfg = FraisGenerauxNiveau.objects.using(_db).get(level=_level)
        except FraisGenerauxNiveau.DoesNotExist:
            pass

    _classe_cfg = None
    if enrollment.class_group:
        try:
            _classe_cfg = FraisMensuelClasse.objects.using(_db).get(class_group=enrollment.class_group)
        except FraisMensuelClasse.DoesNotExist:
            pass

    if not enrollment.total_fees:
        _ft = _classe_cfg.montant_global if (_classe_cfg and _classe_cfg.montant_global) else None
        if _ft is None and _niv_cfg and _niv_cfg.frais_totaux:
            _ft = _niv_cfg.frais_totaux
        if _ft:
            enrollment.total_fees = _ft
            enrollment.save(update_fields=['total_fees'])

    if not enrollment.monthly_installment and not enrollment.student.is_boursier:
        _fm = _classe_cfg.frais_mensuel if (_classe_cfg and _classe_cfg.frais_mensuel) else None
        if _fm is None and _niv_cfg and _niv_cfg.frais_mensuel:
            _fm = _niv_cfg.frais_mensuel
        if _fm:
            enrollment.monthly_installment = _fm
            enrollment.save(update_fields=['monthly_installment'])

    frais_inscription_val = enrollment.frais_generaux or Decimal('0')
    mensuel     = enrollment.monthly_installment or Decimal('0')
    months_list = [m for m, _amt in enrollment.advance_months_list()]

    total_encaisse = enrollment.payment_amount if enrollment.payment_amount is not None else (
        frais_inscription_val + max(len(months_list) - 1, 0) * mensuel
    )
    notes_parts = [f"Frais d'inscription — {enrollment.class_group.name}"]
    if months_list:
        MOIS_FR_LOCAL = ['', 'Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin',
                          'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre']
        mois_labels = ', '.join(MOIS_FR_LOCAL[m] for m in months_list if 1 <= m <= 12)
        notes_parts.append(f"Mois payés : {mois_labels}")
    cp = CaissePayment.objects.create(
        student=enrollment.student,
        enrollment=enrollment,
        payment_type=CaissePayment.TYPE_INSCRIPTION,
        amount=total_encaisse,
        payment_date=enrollment.payment_date,
        payment_months=','.join(str(m) for m in months_list),
        academic_year=enrollment.academic_year,
        notes=' | '.join(notes_parts),
        created_by=validated_by,
    )
    enrollment.payment_reference = cp.reference
    enrollment.payment_amount    = total_encaisse
    enrollment.save(update_fields=['payment_reference', 'payment_amount'])

    if enrollment.credit_report:
        enrollment.payment_amount = (enrollment.payment_amount or Decimal('0')) + enrollment.credit_report
        enrollment.save(update_fields=['payment_amount'])

    regenerate_installments(enrollment)

    student = enrollment.student
    student.current_class = enrollment.class_group
    student.save(update_fields=['current_class'])
    student.user.is_active = True

    # Candidat du portail public (voir academic_core/apps/admissions) : la
    # validation finale du paiement est le moment où il devient réellement
    # un étudiant — bascule du rôle CANDIDAT vers ETUDIANT ici, jamais avant
    # (voir students/services.py::create_student_enrollment), synchronisée
    # dans 'default' où vit la copie authentifiable du compte.
    from academic_core.apps.accounts.models import Role
    if student.user.role and student.user.role.name == Role.CANDIDAT:
        etudiant_role = Role.objects.using(get_current_db()).filter(name=Role.ETUDIANT).first()
        if etudiant_role:
            student.user.role = etudiant_role
            try:
                default_role = Role.objects.using('default').get(name=Role.ETUDIANT)
                from django.contrib.auth import get_user_model
                get_user_model().objects.using('default').filter(pk=student.user.pk).update(role=default_role)
            except Exception:
                pass

    student.user.save(update_fields=['is_active', 'role'])
    try:
        from academic_core.apps.notifications.utils import notify_inscription_validated
        notify_inscription_validated(enrollment, request=request)
    except Exception:
        pass

    return cp


def build_diploma_supplement_ue_table(program, num_semesters):
    """
    Construit la table « Contenus des enseignements » du supplément de
    diplôme (voir accounting/views.py::diploma_supplement_pdf) à partir des
    modules (EC) réellement définis pour cette filière — pas de ressaisie
    manuelle : Unité d'Enseignement, module, semestre(s) concerné(s) (marqué
    'x'), quota horaire (Subject.volume_total_ue) et crédits ECTS
    (Subject.credits), exactement les colonnes du modèle Word de référence.
    """
    from academic_core.apps.subjects.models import Subject

    subjects = (
        Subject.objects
        .filter(program=program, semester__number__lte=num_semesters)
        .select_related('ue', 'semester')
        .order_by('ue__order', 'semester__number', 'code')
    )

    rows = []
    total_qt = Decimal('0')
    total_credits = 0
    for subj in subjects:
        ue_label = f"{subj.ue.code} : {subj.ue.title}" if subj.ue else 'Hors UE'
        sem_num = subj.semester.number if subj.semester else None
        rows.append({
            'ue_label':  ue_label,
            'module':    subj.title,
            'sem_marks': {n: (n == sem_num) for n in range(1, num_semesters + 1)},
            'qt':        subj.volume_total_ue,
            'credits':   subj.credits,
        })
        total_qt += subj.volume_total_ue or Decimal('0')
        total_credits += subj.credits or 0

    return {'rows': rows, 'total_qt': total_qt, 'total_credits': total_credits}


def generate_inscription_recu_pdf(enrollment, config=None):
    """
    Génère le reçu PDF consolidé d'une inscription (tous paiements) — extrait
    de accounting/views.py::inscription_recu_pdf pour être réutilisable sans
    objet `request` (pièce jointe de l'email de validation, voir
    notifications/utils.py::notify_inscription_validated). Retourne un buffer
    BytesIO positionné au début.
    """
    import io as _io
    from .models import CaissePayment
    from reportlab.lib.pagesizes import A5
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, KeepTogether
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
    from academic_core.pdf_utils import logo_image as _logo_img_fn

    def _logo_img(**kw):
        return _logo_img_fn(config=config, **kw)

    payments = list(CaissePayment.objects.filter(enrollment=enrollment).order_by('payment_type', 'payment_month'))
    student  = enrollment.student

    if enrollment.payment_amount:
        total_paid = enrollment.payment_amount
    else:
        _pdf_months  = enrollment.advance_months_list()
        _pdf_fees    = enrollment.total_fees or 0
        _pdf_mensuel = enrollment.monthly_installment or 0
        if _pdf_months and _pdf_mensuel:
            total_paid = _pdf_fees + max(len(_pdf_months) - 1, 0) * _pdf_mensuel
        else:
            total_paid = _pdf_fees or sum(p.amount for p in payments)
    nom_inst   = config.nom if config else 'Institut'
    sigle_inst = config.sigle if config else ''

    navy  = colors.HexColor('#00173B')
    gold  = colors.HexColor('#D4AF37')
    green = colors.HexColor('#166534')
    light = colors.HexColor('#EFF6FF')

    buffer = _io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A5,
        rightMargin=1.0*cm, leftMargin=1.0*cm,
        topMargin=0.7*cm, bottomMargin=0.7*cm,
    )
    styles = getSampleStyleSheet()
    story  = []

    def _style(name='Normal', **kw):
        return ParagraphStyle(name, parent=styles[name], **kw)

    PAD2 = [('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5),
            ('TOPPADDING',(0,0),(-1,-1),2),('BOTTOMPADDING',(0,0),(-1,-1),2)]

    # ── En-tête compact ───────────────────────────────────────────────────────
    logo = _logo_img(width=1.7*cm, height=1.7*cm)
    header_data = [[logo, Paragraph(
        f'<font color="#00173B"><b>{nom_inst}</b></font>'
        f'  <font color="#D4AF37" size="8">{sigle_inst}</font><br/>'
        f'<font size="6.5" color="#555">{getattr(config,"ville","") or ""}'
        f'{" — " if getattr(config,"telephone","") else ""}'
        f'{getattr(config,"telephone","") or ""}</font>',
        _style('Normal', fontSize=10, leading=13, alignment=TA_LEFT),
    )]]
    header_tbl = Table(header_data, colWidths=[2.1*cm, None])
    header_tbl.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(header_tbl)
    story.append(HRFlowable(width='100%', thickness=2, color=gold, spaceAfter=3))

    # ── Titre + référence sur une ligne ──────────────────────────────────────
    story.append(Paragraph(
        f'<b>REÇU D\'INSCRIPTION</b>'
        f'  <font color="#166534" size="10"><b>{enrollment.payment_reference or "—"}</b></font>',
        _style('Normal', fontSize=11, textColor=navy, alignment=TA_CENTER, spaceAfter=4),
    ))

    # ── Informations étudiant sur 2 colonnes ─────────────────────────────────
    def _mini_tbl(data):
        t = Table(data, colWidths=[2.2*cm, None])
        t.setStyle(TableStyle([
            ('FONTSIZE',  (0,0),(-1,-1), 7.5),
            ('FONTNAME',  (0,0),(0,-1), 'Helvetica-Bold'),
            ('TEXTCOLOR', (0,0),(0,-1), navy),
            ('ROWBACKGROUNDS',(0,0),(-1,-1),[colors.white, colors.HexColor('#F8FAFC')]),
            ('GRID',(0,0),(-1,-1),0.3,colors.HexColor('#E2E8F0')),
        ] + PAD2))
        return t

    left_data  = [['Matricule',  student.matricule],
                  ['Étudiant',   student.full_name],
                  ['Classe',     enrollment.class_group.name if enrollment.class_group else '—']]
    right_data = [['Année acad.', str(enrollment.academic_year) if enrollment.academic_year else '—'],
                  ['Type',        enrollment.get_enrollment_type_display()],
                  ['Date paiement', str(enrollment.payment_date) if enrollment.payment_date else '—']]
    stu_tbl = Table([[_mini_tbl(left_data), _mini_tbl(right_data)]], colWidths=['50%','50%'])
    stu_tbl.setStyle(TableStyle([('LEFTPADDING',(0,0),(-1,-1),0),
                                  ('RIGHTPADDING',(0,0),(-1,-1),0),
                                  ('VALIGN',(0,0),(-1,-1),'TOP')]))
    story += [stu_tbl, Spacer(1, 5)]

    # ── Détail du paiement ────────────────────────────────────────────────────
    story.append(Paragraph('<b>Détail du paiement</b>',
        _style('Normal', fontSize=8, textColor=navy, spaceAfter=3)))

    for p in payments:
        # Résumé du paiement sur une ligne
        pay_tbl = Table([[
            Paragraph(f'<b>Réf :</b> <font color="#1d4ed8">{p.reference}</font>',
                      _style('Normal', fontSize=7.5)),
            Paragraph(f'<b>Type :</b> {p.get_type_label()}',
                      _style('Normal', fontSize=7.5)),
            Paragraph(f'<b>Date :</b> {p.payment_date.strftime("%d/%m/%Y") if p.payment_date else "—"}',
                      _style('Normal', fontSize=7.5)),
            Paragraph(f'<b><font color="#166534">{int(p.amount):,} FCFA</font></b>'.replace(',', ' '),
                      _style('Normal', fontSize=8, alignment=TA_RIGHT)),
        ]], colWidths=[3.5*cm, 2.8*cm, 2.5*cm, None])
        pay_tbl.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#F8FAFC')),
            ('GRID',(0,0),(-1,-1),0.3,colors.HexColor('#E2E8F0')),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ] + PAD2))
        story.append(pay_tbl)

        # Ventilation frais d'inscription + mois
        # Le 1er mois est inclus dans total_fees (formule : total_fees + (n-1)*mensuel)
        ventil_rows = []
        months_labels = p.get_months_labels()
        if enrollment.total_fees:
            first_month_label = months_labels[0] if months_labels else None
            frais_label = (
                f"Frais d'inscription (dont {first_month_label})"
                if first_month_label else "Frais d'inscription"
            )
            ventil_rows.append([frais_label,
                                 f'{int(enrollment.total_fees):,} FCFA'.replace(',', ' ')])
        for mois_lbl in months_labels[1:]:   # sauter le 1er mois déjà dans total_fees
            fm = enrollment.monthly_installment or 0
            ventil_rows.append([f'Mensualité — {mois_lbl}',
                                 f'{int(fm):,} FCFA'.replace(',', ' ')])

        if ventil_rows:
            v_tbl = Table([['Ventilation', 'Montant']] + ventil_rows, colWidths=[None, 2.8*cm])
            v_tbl.setStyle(TableStyle([
                ('FONTSIZE',    (0,0),(-1,-1), 7.5),
                ('BACKGROUND',  (0,0),(-1,0),  colors.HexColor('#E2E8F0')),
                ('FONTNAME',    (0,0),(-1,0),  'Helvetica-Bold'),
                ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white, colors.HexColor('#F0FDF4')]),
                ('GRID',        (0,0),(-1,-1), 0.3, colors.HexColor('#D1FAE5')),
                ('ALIGN',       (1,0),(1,-1),  'RIGHT'),
            ] + PAD2))
            story.append(v_tbl)

    story.append(Spacer(1, 5))

    # ── Total ─────────────────────────────────────────────────────────────────
    total_tbl = Table(
        [['MONTANT TOTAL PAYÉ', f'{int(total_paid):,} FCFA'.replace(',', ' ')]],
        colWidths=[None, 3.2*cm],
    )
    total_tbl.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1), navy),
        ('TEXTCOLOR', (0,0),(-1,-1), colors.white),
        ('FONTNAME',  (0,0),(-1,-1), 'Helvetica-Bold'),
        ('FONTSIZE',  (0,0),(-1,-1), 9),
        ('ALIGN',     (1,0),(1,0),   'RIGHT'),
        ('TOPPADDING',(0,0),(-1,-1), 5),
        ('BOTTOMPADDING',(0,0),(-1,-1), 5),
        ('LEFTPADDING',(0,0),(-1,-1), 7),
        ('RIGHTPADDING',(0,0),(-1,-1), 7),
    ]))
    story.append(total_tbl)
    story.append(Spacer(1, 6))

    # ── Signature ─────────────────────────────────────────────────────────────
    caissier_nom = enrollment.validated_by.get_full_name() if enrollment.validated_by else '—'
    sig_tbl = Table([[
        Paragraph(f'<font size="7.5">Validé par : <b>{caissier_nom}</b></font>',
                  _style('Normal', textColor=navy)),
        Paragraph('<font size="7.5">Signature &amp; Cachet :<br/><br/>___________________</font>',
                  _style('Normal', textColor=colors.grey, alignment=TA_CENTER)),
    ]], colWidths=[None, 5*cm])
    sig_tbl.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),
                                  ('LEFTPADDING',(0,0),(-1,-1),0)]))
    from academic_core.apps.students.qr_utils import student_qr_receipt_block
    tail = [
        sig_tbl,
        HRFlowable(width='100%', thickness=0.5, color=colors.lightgrey, spaceBefore=5),
        Paragraph(
            f'<font size="6.5" color="grey">Document généré le '
            f'{timezone.now().strftime("%d/%m/%Y à %H:%M")} — {nom_inst}</font>',
            _style('Normal', alignment=TA_CENTER),
        ),
    ] + student_qr_receipt_block(student, enrollment)
    story.append(KeepTogether(tail))

    from academic_core.pdf_utils import watermark_canvas
    doc.build(story, onFirstPage=watermark_canvas, onLaterPages=watermark_canvas)
    buffer.seek(0)
    return buffer
