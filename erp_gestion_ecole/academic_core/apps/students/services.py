"""
Logique de création d'un compte étudiant (User + Student + Enrollment),
partagée entre la création manuelle par un admin/gestionnaire
(students/views.py::StudentCreateView) et le parcours candidat du portail
public d'admission (academic_core/apps/admissions).
"""
import base64
import random
import string

from django.contrib.auth.hashers import make_password
from django.core.files.base import ContentFile
from django.utils import timezone

from .models import Student, Enrollment

MOIS_LONG = ['', 'Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin',
             'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre']


def build_student_card_status(student):
    """
    Statut de paiement + informations d'affichage d'un étudiant, pour la carte
    affichée au Contrôle Accueil (photo, filière, classe, bande verte/rouge).

    Règle de validation : mois précédents (arriérés) invalidés immédiatement
    si impayés, sans délai de grâce ; mois en cours avec délai de grâce
    jusqu'au 4 inclus (invalidé à partir du 5 s'il reste impayé) ; dernier
    mois de l'année académique exclu du contrôle (déjà inclus dans le montant
    global de la formation, pas un vrai cycle mensuel).

    Extrait de students/views.py::controle_scan_lookup pour être réutilisable
    par le nouveau flux self-scan (hr/checkin_views.py::accueil_self_checkin).
    Retourne un dict {student: {...}, paiement: {...}} — même forme que le
    JSON déjà consommé par controle_scan.html.
    """
    from academic_core.apps.accounting.services import month_schedule_for

    today = timezone.now().date()
    enrollment = student.current_enrollment()

    is_valid = False
    statut_label = 'INVALIDÉ'
    statut_detail = 'Aucune inscription active'
    reference_month_label = None
    installments_data = []
    photo_url = None

    if student.photo:
        try:
            photo_url = student.photo.url
        except Exception:
            photo_url = None

    if enrollment:
        schedule = month_schedule_for(enrollment.academic_year, enrollment.class_group)
        checkable_months = schedule[:-1] if len(schedule) > 1 else []
        today_key = (today.year, today.month)

        unpaid_months = []
        for (y, m) in checkable_months:
            if (y, m) > today_key:
                continue
            if (y, m) == today_key and today.day < 5:
                continue  # mois en cours, encore dans le délai de grâce
            inst = enrollment.installments.filter(due_date__year=y, due_date__month=m).first()
            if not (inst and inst.is_paid):
                unpaid_months.append((y, m))

        if unpaid_months:
            unpaid_months.sort()
            ref_y, ref_m = unpaid_months[0]
            reference_month_label = f"{MOIS_LONG[ref_m]} {ref_y}"
            is_valid = False
            statut_label = 'INVALIDÉ'
            if len(unpaid_months) == 1:
                statut_detail = f"Mois de {reference_month_label} non réglé"
            else:
                statut_detail = f"{len(unpaid_months)} mois impayés, dont {reference_month_label}"
        else:
            is_valid = True
            statut_label = 'VALIDÉ'
            if today_key in checkable_months and today.day < 5:
                reference_month_label = f"{MOIS_LONG[today.month]} {today.year}"
                statut_detail = f"À jour — délai de règlement de {reference_month_label} jusqu'au 4"
            else:
                reference_month_label = None
                statut_detail = "À jour des paiements"

        for inst in enrollment.installments.order_by('-due_date')[:6]:
            installments_data.append({
                'mois': f"{MOIS_LONG[inst.due_date.month]} {inst.due_date.year}",
                'montant': float(inst.amount_expected),
                'paye': inst.is_paid,
                'date_paiement': inst.paid_date.strftime('%d/%m/%Y') if inst.paid_date else None,
            })

    dernier_mois_paye = None
    if enrollment:
        derniere_echeance_payee = enrollment.installments.filter(is_paid=True).order_by('-due_date').first()
        if derniere_echeance_payee:
            dernier_mois_paye = (
                f"{MOIS_LONG[derniere_echeance_payee.due_date.month]} "
                f"{derniere_echeance_payee.due_date.year}"
            )

    return {
        'student': {
            'id': student.pk,
            'nom': student.user.get_full_name(),
            'matricule': student.matricule,
            'filiere': enrollment.class_group.program.name if enrollment else '',
            'classe': enrollment.class_group.name if enrollment else '',
            'annee': str(enrollment.academic_year) if enrollment else '',
            'photo': photo_url,
            'suspendu': student.payment_suspended,
        },
        'paiement': {
            'is_valid': is_valid,
            'statut_label': statut_label,
            'statut_detail': statut_detail,
            'mois_reference': reference_month_label,
            'dernier_mois_paye': dernier_mois_paye,
            'echeances': installments_data,
        },
    }


def _get_institut_config(class_group):
    """Retourne l'InstitutConfig de l'institut lié à la classe, ou None."""
    try:
        faculty = (class_group.program.department.faculty
                   if class_group and class_group.program and class_group.program.department
                   else None)
        if not faculty:
            return None
        from academic_core.apps.academic_structure.models import InstitutConfig
        return InstitutConfig.objects.using('default').filter(faculty=faculty).first()
    except Exception:
        return None


def _get_sigle_institut(class_group):
    """Retourne le sigle de l'institut lié à la classe, ou chaîne vide."""
    cfg = _get_institut_config(class_group)
    return (cfg.sigle or '').strip() if cfg else ''


def generate_matricule(class_group, academic_year, max_tries=20):
    """
    Génère un matricule unique au format :
      {matricule_prefix}-{YY}-{4_chiffres_aléatoires}/{sigle_institut}
    Le préfixe est lu depuis InstitutConfig.matricule_prefix (défaut : '411').
    """
    cfg = _get_institut_config(class_group)
    prefix = (cfg.matricule_prefix or '411').strip() if cfg else '411'
    sigle  = (cfg.sigle or '').strip() if cfg else ''
    suffix = f'/{sigle}' if sigle else ''

    # Deux derniers chiffres de l'année de fin de l'année académique
    year_digits = '00'
    if academic_year:
        end = getattr(academic_year, 'end_date', None) or getattr(academic_year, 'start_date', None)
        if end:
            year_digits = str(end.year)[-2:]

    for _ in range(max_tries):
        rand4 = ''.join(random.choices(string.digits, k=4))
        candidate = f'{prefix}-{year_digits}-{rand4}{suffix}'
        if not Student.objects.filter(matricule=candidate).exists():
            return candidate
    # Fallback avec 6 chiffres si collision très improbable
    rand6 = ''.join(random.choices(string.digits, k=6))
    return f'{prefix}-{year_digits}-{rand6}{suffix}'


def get_direction_etudes(faculty=None):
    """Retourne la Direction des Études pour la faculté donnée, ou la première trouvée."""
    from academic_core.apps.accounts.models import Direction
    qs = Direction.objects.filter(name__icontains='études')
    if faculty:
        by_faculty = qs.filter(faculty=faculty).first()
        if by_faculty:
            return by_faculty
    return qs.first()


def webcam_b64_to_file(b64_data: str, matricule: str):
    """Convert a base64 data-URL from webcam capture to a Django ContentFile."""
    if not b64_data:
        return None
    try:
        if ',' in b64_data:
            b64_data = b64_data.split(',', 1)[1]
        raw = base64.b64decode(b64_data)
        return ContentFile(raw, name=f"webcam_{matricule}.jpg")
    except Exception:
        return None


def create_student_enrollment(*, db_alias, cd, class_group, academic_year, user=None):
    """
    Crée le triplet User + Student + Enrollment pour une nouvelle inscription
    — logique extraite de StudentCreateView.post() pour être réutilisable par
    le parcours candidat du portail public (academic_core/apps/admissions),
    qui fournit `user` (compte CANDIDAT déjà créé et vérifié par email) au
    lieu d'en créer un nouveau.

    `cd` : dict avec les mêmes clés que StudentUserForm.cleaned_data
    (first_name, last_name, email, password, matricule, username,
    date_of_birth, place_of_birth, country_of_birth, nationality, gender,
    phone, address, guardian_*, is_boursier, partenaire_bourse, photo,
    photo_webcam).

    Retourne (user, student, enrollment, matricule, plain_password).
    """
    from academic_core.apps.accounts.models import User, Role

    matricule = (cd.get('matricule') or '').strip() or generate_matricule(class_group, academic_year)
    username  = (cd.get('username') or '').strip() or matricule
    plain_password = cd.get('password') or ''

    student_dept = None
    if class_group and getattr(class_group, 'program', None):
        student_dept = getattr(class_group.program, 'department', None)
    student_faculty  = getattr(student_dept, 'faculty', None) if student_dept else None
    direction_etudes = get_direction_etudes(student_faculty)

    if user is None:
        try:
            role = Role.objects.using(db_alias).get(name=Role.ETUDIANT)
        except Role.DoesNotExist:
            role = Role.objects.get(name=Role.ETUDIANT)

        user = User.objects.using(db_alias).create(
            first_name=cd['first_name'],
            last_name=cd['last_name'],
            email=cd['email'],
            username=username,
            password=make_password(plain_password),
            role=role,
            department=student_dept,
            direction=direction_etudes,
            must_change_password=True,
            is_active=False,
        )
    else:
        # Candidat déjà créé (compte vérifié par email) : reste en rôle
        # CANDIDAT jusqu'à la validation finale du paiement (voir
        # accounting/services.py::finalize_enrollment_payment, appelée par la
        # validation caissier des preuves de paiement — c'est à ce moment,
        # et seulement là, que le rôle bascule vers ETUDIANT) — on complète
        # simplement son profil avec le département dérivé de la filière
        # choisie, pour que le routage/reporting basé sur le département
        # fonctionne dès cette étape.
        user.department = student_dept
        user.direction = direction_etudes
        user.save(using=db_alias)

    raw_photo = cd.get('photo')
    photo_file = (raw_photo if raw_photo and raw_photo is not False else None) \
        or webcam_b64_to_file(cd.get('photo_webcam', ''), matricule)

    student = Student.objects.using(db_alias).create(
        user=user,
        matricule=matricule,
        date_of_birth=cd.get('date_of_birth'),
        place_of_birth=cd.get('place_of_birth', ''),
        country_of_birth=cd.get('country_of_birth', ''),
        nationality=cd.get('nationality', ''),
        gender=cd.get('gender', ''),
        phone=cd.get('phone', ''),
        address=cd.get('address', ''),
        guardian_first_name=cd.get('guardian_first_name', ''),
        guardian_last_name=cd.get('guardian_last_name', ''),
        guardian_phone=cd.get('guardian_phone', ''),
        guardian_address=cd.get('guardian_address', ''),
        guardian_email=cd.get('guardian_email', ''),
        is_boursier=cd.get('is_boursier', False),
        partenaire_bourse=cd.get('partenaire_bourse') if cd.get('is_boursier') else None,
    )
    if photo_file:
        student.photo.save(photo_file.name, photo_file, save=True)

    enrollment = Enrollment.objects.using(db_alias).create(
        student=student,
        class_group=class_group,
        academic_year=academic_year,
        enrollment_type=Enrollment.TYPE_NEW,
        status=Enrollment.STATUS_PENDING,
        is_active=False,
    )


# ---------------------------------------------------------------------------
# Supplément de diplôme — éligibilité par cycle (Licence L1-L2-L3 / Master M1-M2)
# ---------------------------------------------------------------------------

DIPLOMA_SUPPLEMENT_CYCLES = {
    'licence': ['Licence 1', 'Licence 2', 'Licence 3'],
    'master':  ['Master 1', 'Master 2'],
}


def resolve_diploma_supplement_program(student, cycle):
    """
    Détermine la filière (Program) à considérer pour le supplément de
    diplôme d'un cycle donné ('licence' ou 'master') : celle de
    l'inscription validée la plus récente de l'étudiant dans ce cycle, à cet
    institut. None si l'étudiant n'a jamais été inscrit dans ce cycle ici.
    """
    levels = DIPLOMA_SUPPLEMENT_CYCLES.get(cycle)
    if not levels:
        return None

    enrollment = (
        Enrollment.objects
        .filter(
            student=student,
            status=Enrollment.STATUS_VALIDATED,
            class_group__level__name__in=levels,
        )
        .select_related('class_group__program', 'class_group__level', 'academic_year')
        .order_by('-academic_year__start_date')
        .first()
    )
    return enrollment.class_group.program if enrollment else None


def check_diploma_supplement_eligibility(student, program, cycle):
    """
    Vérifie que l'étudiant a validé, dans cette filière précise et à cet
    institut, une inscription à CHACUN des niveaux du cycle demandé (Licence
    1/2/3 ou Master 1/2). Retourne (eligible: bool, missing_levels: list[str],
    enrollments_by_level: dict[str, Enrollment]) — enrollments_by_level ne
    contient que les niveaux effectivement trouvés, utile pour construire le
    document (dernière classe suivie, année académique, etc.) même en cas
    d'inéligibilité (diagnostic).
    """
    levels = DIPLOMA_SUPPLEMENT_CYCLES.get(cycle, [])
    if not program or not levels:
        return False, levels, {}

    enrollments = (
        Enrollment.objects
        .filter(
            student=student,
            status=Enrollment.STATUS_VALIDATED,
            class_group__program=program,
            class_group__level__name__in=levels,
        )
        .select_related('class_group__level', 'class_group__program', 'academic_year')
        .order_by('class_group__level__order')
    )
    enrollments_by_level = {}
    for enr in enrollments:
        level_name = enr.class_group.level.name
        # Garder l'inscription la plus récente si plusieurs existent pour ce niveau
        existing = enrollments_by_level.get(level_name)
        if not existing or enr.academic_year.start_date > existing.academic_year.start_date:
            enrollments_by_level[level_name] = enr

    missing_levels = [lvl for lvl in levels if lvl not in enrollments_by_level]
    eligible = not missing_levels
    return eligible, missing_levels, enrollments_by_level

    return user, student, enrollment, matricule, plain_password


# ─── Attestation de non soutenance (Licence 3 / Master 2) ─────────────────────
# Document délivré à un étudiant de fin de cycle (Licence 3 ou Master 2) qui a
# validé la totalité des UE de son parcours (toutes les classes précédentes +
# la classe actuelle), mais n'a pas encore soutenu son mémoire/PFE — utile
# pour justifier d'un niveau d'études complet auprès d'un employeur en
# attendant la soutenance et la délivrance du diplôme définitif.

def is_non_soutenance_target_level(level_name):
    """
    True si level_name correspond à une classe de Licence 3 ou Master 2 —
    tolérant aux variations de nommage (« L3 », « Licence3 », « LICENCE 3 »…),
    même logique que accounting/views.py::_detect_fin_cycle, dupliquée ici
    (plutôt qu'importée) pour ne pas faire dépendre l'app students de
    l'app accounting.
    """
    import re
    n = (level_name or '').lower()
    return bool(re.search(r'licen[cs]?e?\s*3|l\s*3\b', n) or re.search(r'master\s*2|m\s*2\b', n))


def non_soutenance_cycle_label(level_name):
    """« Licence » ou « Master » selon le niveau détecté — pour le libellé du document."""
    import re
    n = (level_name or '').lower()
    return 'Licence' if re.search(r'licen[cs]?e?\s*3|l\s*3\b', n) else 'Master'


def resolve_non_soutenance_context(student):
    """
    Retourne (enrollment, required_levels) :
      - enrollment : l'inscription validée la plus récente de l'étudiant dans
        une classe de Licence 3 ou Master 2 (peu importe le nommage exact du
        niveau) ; None si l'étudiant n'est actuellement dans aucune classe de
        ce type — cette attestation n'a de sens que pour elles.
      - required_levels : la liste ORDONNÉE (objets Level, pas des noms) de
        tous les niveaux à valider : tous ceux dont l'ordre est ≤ celui de la
        classe actuelle — couvre donc Licence 1→3, ou Licence 1→Master 2,
        sans lister de noms en dur (ils varient d'un institut à l'autre).
    """
    from academic_core.apps.academic_structure.models import Level

    candidates = (
        Enrollment.objects
        .filter(student=student, status=Enrollment.STATUS_VALIDATED)
        .select_related('class_group__program', 'class_group__level', 'academic_year')
        .order_by('-academic_year__start_date')
    )
    enrollment = None
    for enr in candidates:
        level = enr.class_group.level
        if level and is_non_soutenance_target_level(level.name):
            enrollment = enr
            break
    if not enrollment:
        return None, []

    target_order = enrollment.class_group.level.order
    required_levels = list(Level.objects.filter(order__lte=target_order).order_by('order'))
    return enrollment, required_levels


def _find_stage_soutenance_ue(program, target_level, academic_year):
    """
    UE « Stage & soutenance » du dernier semestre du niveau cible (Licence 3
    ou Master 2) — celle qu'on exempte de la condition de validation totale
    pour l'Attestation de non soutenance : par construction, elle ne peut pas
    être validée avant la soutenance elle-même (l'attestation existe
    précisément pour couvrir cette période d'attente). Identifiée par
    position — le dernier semestre du niveau, puis la dernière UE par ordre
    d'affichage — plutôt que par un intitulé précis, qui varie d'une filière
    à l'autre.
    """
    from academic_core.apps.academic_structure.models import Semester
    from academic_core.apps.grades.models import UniteEnseignement

    last_semester = (
        Semester.objects.filter(level=target_level, academic_year=academic_year)
        .order_by('-number').first()
    )
    if not last_semester:
        return None
    return (
        UniteEnseignement.objects
        .filter(program=program, semester=last_semester)
        .order_by('-order').first()
    )


def check_non_soutenance_eligibility(student, enrollment, required_levels):
    """
    Vérifie que l'étudiant a validé, dans la filière de `enrollment` et à cet
    institut, TOUTES les UE de TOUS les semestres de CHAQUE niveau de
    required_levels — SAUF la dernière UE du niveau cible (Licence 3 ou
    Master 2), qui correspond au stage/mémoire de fin d'études : elle est
    justement celle qui reste à valider une fois la soutenance passée, donc
    exclue de la condition (voir _find_stage_soutenance_ue) — condition de
    délivrance de l'Attestation de non soutenance.

    Contrairement à check_diploma_supplement_eligibility (qui ne vérifie que
    l'inscription administrative validée à chaque niveau), ceci descend
    jusqu'au détail des UE (grades.BulletinUEResult.is_validated) — la
    demande explicite était "valider TOUTES les UE" (hormis celle du
    stage/soutenance), pas seulement être passé en classe supérieure.

    Retourne un dict :
      eligible                   bool
      missing_enrollment_levels  noms des niveaux jamais validés administrativement
      missing_semesters          semestres LMD du parcours sans aucun bulletin
      missing_ue                 BulletinUEResult non validés (is_validated=False),
                                  hors UE de stage/soutenance exemptée
      enrollments_by_level       {Level.pk: Enrollment retenue} (diagnostic)
      exempted_ue                UniteEnseignement de stage/soutenance exclue (ou None)
    """
    from academic_core.apps.academic_structure.models import Semester
    from academic_core.apps.grades.models import Bulletin, BulletinUEResult

    if not enrollment or not required_levels:
        return {
            'eligible': False,
            'missing_enrollment_levels': [lvl.name for lvl in required_levels],
            'missing_semesters': [], 'missing_ue': [], 'enrollments_by_level': {},
            'exempted_ue': None,
        }

    program = enrollment.class_group.program
    target_level = required_levels[-1]
    exempted_ue = _find_stage_soutenance_ue(program, target_level, enrollment.academic_year)

    # 1. Une inscription validée à chaque niveau requis, dans cette filière —
    #    condition de base : sans ça on ne sait même pas dans quelle année
    #    académique regarder les bulletins de ce niveau (étape 2).
    enrollments = (
        Enrollment.objects.filter(
            student=student, status=Enrollment.STATUS_VALIDATED,
            class_group__program=program, class_group__level__in=required_levels,
        ).select_related('class_group__level', 'academic_year')
    )
    enrollments_by_level = {}
    for enr in enrollments:
        level = enr.class_group.level
        existing = enrollments_by_level.get(level.pk)
        if not existing or enr.academic_year.start_date > existing.academic_year.start_date:
            enrollments_by_level[level.pk] = enr
    missing_enrollment_levels = [lvl.name for lvl in required_levels if lvl.pk not in enrollments_by_level]

    # 2. Semestres LMD réels de ces niveaux, restreints à l'année académique
    #    où l'étudiant a effectivement suivi chaque niveau (un même niveau
    #    correspond à des Semester différents selon l'année académique — ne
    #    jamais filtrer par niveau seul, sinon on récupère des semestres
    #    d'années où cet étudiant n'était pas encore inscrit).
    relevant_semesters = []
    for level in required_levels:
        enr = enrollments_by_level.get(level.pk)
        if not enr:
            continue
        relevant_semesters += list(
            Semester.objects.filter(level=level, academic_year=enr.academic_year)
        )

    bulletins_by_semester = {
        b.semester_id: b for b in
        Bulletin.objects.filter(student=student, semester__in=relevant_semesters)
    }
    missing_semesters = [s for s in relevant_semesters if s.pk not in bulletins_by_semester]

    ue_results = (
        BulletinUEResult.objects
        .filter(bulletin__student=student, bulletin__semester__in=relevant_semesters)
        .select_related('ue', 'bulletin__semester')
    )
    if exempted_ue:
        ue_results = ue_results.exclude(ue=exempted_ue)
    missing_ue = [r for r in ue_results if not r.is_validated]

    eligible = not missing_enrollment_levels and not missing_semesters and not missing_ue
    return {
        'eligible': eligible,
        'missing_enrollment_levels': missing_enrollment_levels,
        'missing_semesters': missing_semesters,
        'missing_ue': missing_ue,
        'enrollments_by_level': enrollments_by_level,
        'exempted_ue': exempted_ue,
    }
