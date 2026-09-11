from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.utils import timezone
from django.db.models import Count, Q
from datetime import date


@login_required
def dashboard_index(request):
    user    = request.user
    faculty = getattr(request, 'active_faculty', None)
    ctx     = {'today': date.today()}

    # Super Admin global sans institut sélectionné
    if user.is_super_admin() and not faculty:
        ctx.update(_super_admin_global_context())
        return render(request, 'dashboard/index_super_admin.html', ctx)

    # Candidat du portail public d'admission : tableau de bord dédié (statut
    # candidature/inscription/paiement), jamais le dashboard normal — il n'a
    # pas encore de profil Student tant que son parcours n'est pas terminé.
    if user.is_candidat():
        return redirect('candidat:candidat_dashboard')

    # Routage par rôle (du plus spécifique au plus général)
    if user.is_tresorier():
        ctx.update(_tresorier_context(faculty))
    elif user.is_caissier():
        ctx.update(_caissier_context(faculty, request=request))
    elif user.is_comptable():
        ctx.update(_comptable_context(faculty))
    elif user.is_controleur():
        ctx.update(_controleur_context(faculty))
    elif user.is_ciaq():
        ctx.update(_ciaq_context(user, faculty))
    elif user.is_admin_direction():
        ctx.update(_direction_context(user, faculty))
    elif user.is_inst_admin():          # INST_ADMIN, ASSISTANTE_DG
        ctx.update(_admin_context(faculty))
    elif user.is_responsable():         # RESPONSABLE, ASSISTANTE
        ctx.update(_dept_context(user, faculty))
    elif user.is_admin():               # ADMIN avec faculty sélectionné
        ctx.update(_admin_context(faculty))
    elif user.is_enseignant():
        ctx.update(_teacher_context(user))
    elif user.is_etudiant():
        ctx.update(_student_context(user, request))

    return render(request, 'dashboard/index.html', ctx)


@login_required
def select_institute(request):
    """Super Admin choisit un institut pour le visiter."""
    if not request.user.is_admin():
        return redirect('dashboard:index')
    if request.method == 'POST':
        fac_id = request.POST.get('faculty_id')
        # Un département sélectionné appartient à l'institut PRÉCÉDEMMENT
        # visité — le laisser en session en changeant d'institut fait
        # ré-interroger son PK dans la base du NOUVEL institut
        # (DepartmentMiddleware._resolve_department, using(user_db)), qui y
        # renvoie silencieusement un département sans rapport (même PK, autre
        # institut) au lieu de DoesNotExist, puisque toute ligne trouvée dans
        # la table locale du nouvel institut lui appartient forcément — d'où
        # des données d'institut visiblement "disparues" (bulletins, listes de
        # classes...) après un changement d'institut. On la purge donc à
        # chaque changement, pas seulement à la désélection complète.
        request.session.pop('active_department_id', None)
        if fac_id:
            request.session['active_faculty_id'] = int(fac_id)
        else:
            request.session.pop('active_faculty_id', None)
    return redirect(request.POST.get('next', 'dashboard:index'))


def _super_admin_global_context():
    """
    Vue globale Super Admin (aucun institut sélectionné) : agrège les chiffres
    de CHAQUE institut en interrogeant explicitement sa propre base tenant via
    `.using(alias)`.

    Important : les modèles opérationnels (Student, Teacher, User, Department,
    AttendanceSheet…) sont routés par tenant — chaque institut a son propre
    fichier SQLite, et la copie locale des tables maîtres (faculties,
    institut_configs) y est TOUJOURS vide par conception. Itérer sur
    `InstitutConfig` (base maître) puis interroger chaque table opérationnelle
    via `.using(alias)` (qui court-circuite le routeur thread-local, voir
    QuerySet.db) est le seul moyen d'agréger les vraies données par institut
    sans mélanger les bases ni en oublier — y compris pour un institut créé
    après le démarrage du process, via `iter_institut_dbs()`.
    """
    from academic_core.apps.academic_structure.models import InstitutConfig, Department
    from academic_core.apps.academic_structure.utils import iter_institut_dbs
    from academic_core.apps.students.models import Student
    from academic_core.apps.teachers.models import Teacher
    from academic_core.apps.accounts.models import User
    from academic_core.apps.attendance.models import AttendanceSheet
    from datetime import date

    today = date.today()
    institutes = []
    total_students = total_teachers = total_users = 0
    unassigned_teachers = unassigned_users = 0

    for config, alias in iter_institut_dbs():
        fac = config.faculty
        if not fac:
            continue

        students_count = Student.objects.using(alias).filter(
            enrollments__is_active=True,
        ).distinct().count()
        teachers_count = Teacher.objects.using(alias).count()
        users_count    = User.objects.using(alias).filter(is_active=True).exclude(role__name='ADMIN').count()
        sheets_today   = AttendanceSheet.objects.using(alias).filter(session_date=today).count()

        # Détail par département
        depts = []
        for dept in Department.objects.using(alias).filter(is_active=True).order_by('name'):
            depts.append({
                'dept':     dept,
                'students': Student.objects.using(alias).filter(
                    enrollments__class_group__program__department=dept,
                    enrollments__is_active=True,
                ).distinct().count(),
                'teachers': Teacher.objects.using(alias).filter(user__department=dept).count(),
                'users':    User.objects.using(alias).filter(is_active=True, department=dept).count(),
            })

        institutes.append({
            'config':         config,
            'faculty':        fac,
            'students_count': students_count,
            'teachers_count': teachers_count,
            'users_count':    users_count,
            'sheets_today':   sheets_today,
            'is_active':      config.actif,
            'depts':          depts,
        })

        total_students += students_count
        total_teachers += teachers_count
        total_users    += users_count

        unassigned_teachers += Teacher.objects.using(alias).filter(user__department__isnull=True).count()
        _teacher_user_pks = Teacher.objects.using(alias).filter(
            user__department__isnull=True
        ).values_list('user_id', flat=True)
        unassigned_users += User.objects.using(alias).filter(
            is_active=True,
            department__isnull=True,
            direction__isnull=True,
            institut_config__isnull=True,
        ).exclude(role__name='ADMIN').exclude(pk__in=_teacher_user_pks).count()

    total_institutes = InstitutConfig.objects.using('default').count()

    return {
        'institutes':           institutes,
        'total_students':       total_students,
        'total_teachers':       total_teachers,
        'total_users':          total_users,
        'unassigned_teachers':  unassigned_teachers,
        'unassigned_users':     unassigned_users,
        'total_institutes':     total_institutes,
    }


def _admin_context(faculty=None):
    from academic_core.apps.students.models import Student, Enrollment
    from academic_core.apps.teachers.models import Teacher
    from academic_core.apps.attendance.models import AttendanceSheet
    from academic_core.apps.cancellations.models import CourseCancellation
    from academic_core.apps.accounts.models import User

    today = date.today()

    # Pas de filtre par faculté ici : ces modèles sont routés par tenant, et
    # la base courante est déjà celle de l'institut actif (middleware). Filtrer
    # en plus par `...__faculty=faculty` exclurait à tort tout enregistrement
    # dont un maillon intermédiaire (département, direction…) n'est pas
    # renseigné — ex : un enseignant sans département assigné.
    students_qs  = Student.objects.filter(enrollments__is_active=True).distinct()
    teachers_qs  = Teacher.objects.all()
    users_qs     = User.objects.filter(is_active=True)
    sheets_base  = AttendanceSheet.objects.all()
    cancels_base = CourseCancellation.objects.all()

    return {
        'total_students':      students_qs.count(),
        'total_teachers':      teachers_qs.count(),
        'total_users':         users_qs.count(),
        'sheets_today':        sheets_base.filter(session_date=today).count(),
        'sheets_pending':      sheets_base.filter(status='PENDING').count(),
        'sheets_validated':    sheets_base.filter(status='VALIDATED').count(),
        'cancellations_pending':  cancels_base.filter(status='PENDING').count(),
        'cancellations_approved': cancels_base.filter(status='APPROVED').count(),
        'recent_sheets': sheets_base.select_related(
            'timetable_entry__subject', 'timetable_entry__teacher__user'
        ).order_by('-session_date')[:5],
        'recent_cancellations': cancels_base.select_related(
            'timetable_entry__subject', 'requested_by'
        ).filter(status='PENDING').order_by('-requested_at')[:5],
    }


def _responsable_context(faculty=None):
    from academic_core.apps.attendance.models import AttendanceSheet
    from academic_core.apps.cancellations.models import CourseCancellation
    from academic_core.apps.timetable.models import TimetableEntry

    # Pas de filtre par faculté : voir commentaire dans _admin_context().
    sheets_base  = AttendanceSheet.objects.all()
    cancels_base = CourseCancellation.objects.all()
    entries_base = TimetableEntry.objects.all()

    return {
        'sheets_signed':   sheets_base.filter(status='SIGNED').count(),
        'sheets_pending':  sheets_base.filter(status='PENDING').count(),
        'cancellations_pending': cancels_base.filter(status='PENDING').count(),
        'total_entries':   entries_base.filter(is_active=True).count(),
        'pending_sheets': sheets_base.filter(status='SIGNED').select_related(
            'timetable_entry__subject', 'timetable_entry__teacher__user'
        ).order_by('-session_date')[:8],
        'pending_cancellations': cancels_base.filter(
            status='PENDING'
        ).select_related('timetable_entry__subject', 'requested_by').order_by('-requested_at')[:5],
    }


def _comptable_context(faculty=None):
    """Tableau de bord Comptable : uniquement la comptabilité."""
    from academic_core.apps.accounting.models import CaissePayment
    from academic_core.apps.students.models import PaymentInstallment
    today = date.today()

    # Pas de filtre par faculté : voir commentaire dans _admin_context().
    caisse_qs = CaissePayment.objects.select_related('student', 'academic_year')
    inst_qs   = PaymentInstallment.objects.filter(is_paid=True).select_related(
        'enrollment__student', 'enrollment__class_group'
    )

    today_caisse  = list(caisse_qs.filter(payment_date=today))
    today_inst    = list(inst_qs.filter(paid_date=today))
    encaisse_jour = sum(c.amount or 0 for c in today_caisse) + sum(i.amount_paid or 0 for i in today_inst)

    # Totaux du mois courant
    month_caisse  = caisse_qs.filter(payment_date__year=today.year, payment_date__month=today.month)
    month_inst    = inst_qs.filter(paid_date__year=today.year, paid_date__month=today.month)
    encaisse_mois = (
        sum(c.amount or 0 for c in month_caisse) +
        sum(i.amount_paid or 0 for i in month_inst)
    )

    # Derniers paiements (10)
    recent_caisse = caisse_qs.order_by('-payment_date', '-created_at')[:10]
    recent_inst   = inst_qs.order_by('-paid_date')[:10]

    return {
        'encaisse_jour':  encaisse_jour,
        'encaisse_mois':  encaisse_mois,
        'nb_transactions_jour': len(today_caisse) + len(today_inst),
        'recent_caisse':  recent_caisse,
        'recent_inst':    recent_inst,
    }


def _tresorier_context(faculty=None):
    """Tableau de bord Trésorier Général : inscriptions, finances globales, clôtures."""
    from academic_core.apps.students.models import Enrollment, Student, PaymentInstallment
    from academic_core.apps.accounting.models import AccountingClosure, CaissePayment
    from django.db.models import Sum
    today = date.today()

    # Pas de filtre par faculté : voir commentaire dans _admin_context().
    enr_qs = Enrollment.objects.select_related('student', 'class_group', 'academic_year', 'validated_by')
    caisse_qs = CaissePayment.objects.select_related('student', 'academic_year')

    nb_pending   = enr_qs.filter(status=Enrollment.STATUS_PENDING).count()
    nb_validated = enr_qs.filter(status=Enrollment.STATUS_VALIDATED).count()
    nb_rejected  = enr_qs.filter(status=Enrollment.STATUS_REJECTED).count()

    # Total encaissé = somme des paiements caisse liés aux inscriptions validées
    total_collected = (
        caisse_qs.filter(enrollment__status=Enrollment.STATUS_VALIDATED)
        .aggregate(s=Sum('amount'))['s'] or 0
    )

    # Restant dû = mensualités impayées sur les inscriptions validées
    inst_qs = PaymentInstallment.objects.filter(enrollment__status=Enrollment.STATUS_VALIDATED, is_paid=False)
    total_remaining = inst_qs.aggregate(s=Sum('amount_expected'))['s'] or 0

    # Inscriptions en attente (les plus récentes en premier)
    pending_enrollments = enr_qs.filter(
        status=Enrollment.STATUS_PENDING
    ).order_by('-enrollment_date')[:10]

    # Dernières inscriptions validées
    recent_validated = enr_qs.filter(
        status=Enrollment.STATUS_VALIDATED
    ).order_by('-validated_at')[:8]

    # Dernières clôtures
    recent_closures = AccountingClosure.objects.select_related(
        'closed_by', 'academic_year'
    ).order_by('-closure_date')[:5]

    # Encaissements du jour (caisse)
    encaisse_jour = (
        caisse_qs.filter(payment_date=today).aggregate(s=Sum('amount'))['s'] or 0
    )
    encaisse_mois = (
        caisse_qs.filter(
            payment_date__year=today.year, payment_date__month=today.month
        ).aggregate(s=Sum('amount'))['s'] or 0
    )

    return {
        'dashboard_role': 'tresorier',
        'nb_pending':          nb_pending,
        'nb_validated':        nb_validated,
        'nb_rejected':         nb_rejected,
        'total_collected':     total_collected,
        'total_remaining':     total_remaining,
        'pending_enrollments': pending_enrollments,
        'recent_validated':    recent_validated,
        'recent_closures':     recent_closures,
        'encaisse_jour':       encaisse_jour,
        'encaisse_mois':       encaisse_mois,
    }


def _caissier_context(faculty=None, request=None):
    """Tableau de bord Caissier : opérations de caisse avec filtres classe/niveau."""
    from academic_core.apps.accounting.models import CaissePayment
    from academic_core.apps.students.models import PaymentInstallment
    from academic_core.apps.academic_structure.models import Class, Level
    from django.db.models import Sum
    today = date.today()

    # Filtres GET
    class_filter = request.GET.get('classe', '') if request else ''
    level_filter = request.GET.get('level', '') if request else ''

    # Listes pour les dropdowns — pas de filtre par faculté : voir commentaire
    # dans _admin_context() (base déjà scopée à l'institut actif).
    levels_qs = Level.objects.order_by('name')
    classes_qs = Class.objects.select_related('level').order_by('name')
    if level_filter:
        classes_qs = classes_qs.filter(level_id=level_filter)
    from academic_core.apps.academic_structure.models import AcademicYear
    current_year = AcademicYear.objects.filter(is_current=True).first()
    if current_year:
        classes_qs = classes_qs.filter(academic_year=current_year)

    caisse_qs = CaissePayment.objects.select_related(
        'student__current_class__level', 'academic_year'
    )
    inst_qs = PaymentInstallment.objects.filter(is_paid=True).select_related(
        'enrollment__student', 'enrollment__class_group__level'
    )
    if class_filter:
        caisse_qs = caisse_qs.filter(
            Q(student__current_class_id=class_filter) |
            Q(student__enrollments__class_group_id=class_filter)
        ).distinct()
        inst_qs = inst_qs.filter(enrollment__class_group_id=class_filter)
    elif level_filter:
        caisse_qs = caisse_qs.filter(
            Q(student__current_class__level_id=level_filter) |
            Q(student__enrollments__class_group__level_id=level_filter)
        ).distinct()
        inst_qs = inst_qs.filter(enrollment__class_group__level_id=level_filter)

    encaisse_jour = (
        (caisse_qs.filter(payment_date=today).aggregate(s=Sum('amount'))['s'] or 0) +
        (inst_qs.filter(paid_date=today).aggregate(s=Sum('amount_paid'))['s'] or 0)
    )
    encaisse_mois = (
        (caisse_qs.filter(payment_date__year=today.year, payment_date__month=today.month)
         .aggregate(s=Sum('amount'))['s'] or 0) +
        (inst_qs.filter(paid_date__year=today.year, paid_date__month=today.month)
         .aggregate(s=Sum('amount_paid'))['s'] or 0)
    )
    nb_transactions_jour = (
        caisse_qs.filter(payment_date=today).count() +
        inst_qs.filter(paid_date=today).count()
    )

    recent_caisse = caisse_qs.order_by('-payment_date', '-created_at')[:20]
    recent_inst   = inst_qs.order_by('-paid_date')[:20]

    # Répartition du jour par type
    today_by_type = (
        caisse_qs.filter(payment_date=today)
        .values('payment_type')
        .annotate(total=Sum('amount'))
        .order_by('-total')
    )

    return {
        'dashboard_role':       'caissier',
        'encaisse_jour':        encaisse_jour,
        'encaisse_mois':        encaisse_mois,
        'nb_transactions_jour': nb_transactions_jour,
        'recent_caisse':        recent_caisse,
        'recent_inst':          recent_inst,
        'today_by_type':        list(today_by_type),
        'dash_levels':          levels_qs,
        'dash_classes':         classes_qs,
        'dash_class_filter':    class_filter,
        'dash_level_filter':    level_filter,
    }


def _controleur_context(faculty=None):
    """Tableau de bord Contrôleur interne : vue d'ensemble de toutes les directions."""
    from academic_core.apps.students.models import Student
    from academic_core.apps.teachers.models import Teacher
    from academic_core.apps.attendance.models import AttendanceSheet
    from academic_core.apps.cancellations.models import CourseCancellation
    from academic_core.apps.accounts.models import Direction, User

    today = date.today()

    # Pas de filtre par faculté : voir commentaire dans _admin_context().
    directions = Direction.objects.filter(is_active=True)

    # Compte de fiches institut-wide, répété par direction (une seule
    # faculté par base tenant, donc le total est le même pour chacune).
    sheets_base    = AttendanceSheet.objects.all()
    sheets_total   = sheets_base.count()
    dir_data = []
    for d in directions.order_by('name'):
        staff = User.objects.filter(direction=d, is_active=True).count()
        dir_data.append({'direction': d, 'staff': staff, 'sheets': sheets_total})

    cancels_base   = CourseCancellation.objects.all()
    students_total = Student.objects.filter(enrollments__is_active=True).distinct().count()
    teachers_total = Teacher.objects.all().count()

    return {
        'directions':           dir_data,
        'total_directions':     len(dir_data),
        'total_students':       students_total,
        'total_teachers':       teachers_total,
        'sheets_today':         sheets_base.filter(session_date=today).count(),
        'sheets_pending':       sheets_base.filter(status='PENDING').count(),
        'sheets_validated':     sheets_base.filter(status='VALIDATED').count(),
        'cancellations_pending': cancels_base.filter(status='PENDING').count(),
        'recent_sheets': sheets_base.select_related(
            'timetable_entry__subject', 'timetable_entry__teacher__user'
        ).order_by('-session_date')[:5],
    }


def _ciaq_context(user, faculty=None):
    """Tableau de bord CIAQ : qualité académique — directions des études, DG, départements."""
    from academic_core.apps.students.models import Student
    from academic_core.apps.teachers.models import Teacher
    from academic_core.apps.attendance.models import AttendanceSheet
    from academic_core.apps.timetable.models import TimetableEntry, SessionLog
    from academic_core.apps.academic_structure.models import Department
    from academic_core.apps.accounts.models import Direction

    today = date.today()

    # Directions académiques (contenant "étude" ou "général" ou "académi" dans le nom)
    # Pas de filtre par faculté : voir commentaire dans _admin_context().
    academic_keywords = ['étude', 'etude', 'académi', 'academi', 'général', 'general', 'pédagog', 'pedagogic']
    directions_qs = Direction.objects.filter(is_active=True)

    academic_dirs = [d for d in directions_qs if any(kw in d.name.lower() for kw in academic_keywords)]
    # Si aucun mot-clé ne correspond, on prend toutes les directions
    if not academic_dirs:
        academic_dirs = list(directions_qs)

    depts = Department.objects.filter(is_active=True)

    dept_data = []
    for dept in depts.order_by('name'):
        students = Student.objects.filter(
            enrollments__class_group__program__department=dept,
            enrollments__is_active=True,
        ).distinct().count()
        teachers = Teacher.objects.filter(user__department=dept).count()
        sheets   = AttendanceSheet.objects.filter(
            timetable_entry__class_group__program__department=dept
        ).count()
        logs_filled = SessionLog.objects.filter(
            timetable_entry__class_group__program__department=dept
        ).count()
        dept_data.append({
            'dept': dept, 'students': students, 'teachers': teachers,
            'sheets': sheets, 'logs_filled': logs_filled,
        })

    sheets_base = AttendanceSheet.objects.all()

    return {
        'academic_directions': academic_dirs,
        'dept_data':           dept_data,
        'total_depts':         len(dept_data),
        'sheets_today':        sheets_base.filter(session_date=today).count(),
        'sheets_pending':      sheets_base.filter(status='PENDING').count(),
        'sheets_validated':    sheets_base.filter(status='VALIDATED').count(),
        'recent_sheets': sheets_base.select_related(
            'timetable_entry__subject', 'timetable_entry__teacher__user',
            'timetable_entry__class_group',
        ).order_by('-session_date')[:5],
    }


def _direction_context(user, faculty=None):
    """Tableau de bord Admin/Assistante de direction : uniquement leur direction."""
    from academic_core.apps.students.models import Student
    from academic_core.apps.teachers.models import Teacher
    from academic_core.apps.attendance.models import AttendanceSheet
    from academic_core.apps.cancellations.models import CourseCancellation
    from academic_core.apps.accounts.models import User as AppUser
    from academic_core.apps.academic_structure.models import Department

    today      = date.today()
    direction  = user.direction  # FK sur l'utilisateur

    # Pas de filtre par faculté (voir _admin_context()) : seule la présence
    # d'une direction assignée à l'utilisateur détermine l'affichage — la
    # base courante est déjà celle du bon institut.
    if direction:
        sheets_base    = AttendanceSheet.objects.all()
        cancels_base   = CourseCancellation.objects.all()
        students_total = Student.objects.filter(enrollments__is_active=True).distinct().count()
        teachers_total = Teacher.objects.all().count()
        staff_total    = AppUser.objects.filter(direction=direction, is_active=True).count()
        depts = Department.objects.filter(is_active=True).order_by('name')
    else:
        sheets_base    = AttendanceSheet.objects.none()
        cancels_base   = CourseCancellation.objects.none()
        students_total = teachers_total = staff_total = 0
        depts = Department.objects.none()

    dept_data = []
    for dept in depts:
        dept_data.append({
            'dept':     dept,
            'students': Student.objects.filter(
                enrollments__class_group__program__department=dept,
                enrollments__is_active=True,
            ).distinct().count(),
            'teachers': Teacher.objects.filter(user__department=dept).count(),
        })

    return {
        'direction':            direction,
        'dept_data':            dept_data,
        'total_students':       students_total,
        'total_teachers':       teachers_total,
        'staff_direction':      staff_total,
        'sheets_today':         sheets_base.filter(session_date=today).count(),
        'sheets_pending':       sheets_base.filter(status='PENDING').count(),
        'sheets_validated':     sheets_base.filter(status='VALIDATED').count(),
        'cancellations_pending': cancels_base.filter(status='PENDING').count(),
        'recent_sheets': sheets_base.select_related(
            'timetable_entry__subject', 'timetable_entry__teacher__user',
            'timetable_entry__class_group',
        ).order_by('-session_date')[:5],
        'recent_cancellations': cancels_base.filter(status='PENDING').select_related(
            'timetable_entry__subject', 'requested_by'
        ).order_by('-requested_at')[:5],
    }


def _dept_context(user, faculty=None):
    """Tableau de bord Admin/Assistante de département : uniquement leur département."""
    from academic_core.apps.students.models import Student
    from academic_core.apps.teachers.models import Teacher
    from academic_core.apps.attendance.models import AttendanceSheet
    from academic_core.apps.cancellations.models import CourseCancellation
    from academic_core.apps.timetable.models import TimetableEntry

    today = date.today()
    dept  = user.department

    if dept:
        students_qs  = Student.objects.filter(
            enrollments__class_group__program__department=dept,
            enrollments__is_active=True,
        ).distinct()
        teachers_qs  = Teacher.objects.filter(user__department=dept)
        sheets_base  = AttendanceSheet.objects.filter(
            timetable_entry__class_group__program__department=dept
        )
        cancels_base = CourseCancellation.objects.filter(
            timetable_entry__class_group__program__department=dept
        )
        entries_base = TimetableEntry.objects.filter(
            class_group__program__department=dept, is_active=True
        )
    else:
        students_qs  = Student.objects.none()
        teachers_qs  = Teacher.objects.none()
        sheets_base  = AttendanceSheet.objects.none()
        cancels_base = CourseCancellation.objects.none()
        entries_base = TimetableEntry.objects.none()

    return {
        'department':           dept,
        'total_students':       students_qs.count(),
        'total_teachers':       teachers_qs.count(),
        'total_entries':        entries_base.count(),
        'sheets_today':         sheets_base.filter(session_date=today).count(),
        'sheets_pending':       sheets_base.filter(status='PENDING').count(),
        'sheets_validated':     sheets_base.filter(status='VALIDATED').count(),
        'cancellations_pending': cancels_base.filter(status='PENDING').count(),
        'cancellations_approved': cancels_base.filter(status='APPROVED').count(),
        'recent_sheets': sheets_base.select_related(
            'timetable_entry__subject', 'timetable_entry__teacher__user'
        ).order_by('-session_date')[:5],
        'recent_cancellations': cancels_base.filter(status='PENDING').select_related(
            'timetable_entry__subject', 'requested_by'
        ).order_by('-requested_at')[:5],
    }


def _teacher_context(user):
    from academic_core.apps.timetable.models import TimetableEntry
    from academic_core.apps.attendance.models import AttendanceSheet
    from academic_core.apps.academic_structure.models import Semester

    today = date.today()
    teacher = getattr(user, 'teacher_profile', None)
    if not teacher:
        return {}

    active_sem = Semester.objects.filter(is_active=True).first()
    today_day  = today.isoweekday()  # 1=Mon … 7=Sun

    today_entries = TimetableEntry.objects.filter(
        teacher=teacher, day_of_week=today_day, is_active=True
    ).select_related('subject', 'class_group', 'room')
    if active_sem:
        today_entries = today_entries.filter(semester__academic_year=active_sem.academic_year)

    pending_sheets_qs = AttendanceSheet.objects.filter(
        timetable_entry__teacher=teacher, status='PENDING'
    )
    if active_sem:
        pending_sheets_qs = pending_sheets_qs.filter(
            timetable_entry__semester__academic_year=active_sem.academic_year
        )
    pending_sheets = pending_sheets_qs.count()

    return {
        'teacher':         teacher,
        'today_entries':   today_entries,
        'pending_sheets':  pending_sheets,
        'hours_done':      teacher.get_total_hours_taught(active_sem.academic_year if active_sem else None),
        'contractual_hours': teacher.contractual_hours,
        'active_semester': active_sem,
    }


def _student_context(user, request):
    from academic_core.apps.timetable.models import TimetableEntry
    from academic_core.apps.grades.models import Grade, SemesterAverage
    from academic_core.apps.attendance.models import StudentAttendance
    from academic_core.apps.students.utils import resolve_student_year

    student = getattr(user, 'student_profile', None)
    if not student:
        return {}

    selected_year, available_years, enrollment = resolve_student_year(request, student)

    today       = date.today()
    today_day   = today.isoweekday()
    current_enrollment = student.current_enrollment()
    today_entries = []

    # Le planning du jour n'a de sens que pour l'année en cours — une année
    # passée sélectionnée le vide plutôt que de montrer un planning obsolète.
    is_current_year_selected = (
        current_enrollment and selected_year
        and selected_year.pk == current_enrollment.academic_year_id
    )
    if is_current_year_selected:
        today_entries = TimetableEntry.objects.filter(
            class_group=current_enrollment.class_group,
            day_of_week=today_day,
            is_active=True,
        ).select_related('subject', 'teacher__user', 'room')

    grades_qs = Grade.objects.filter(
        student=student,
        evaluation__subject__semester__academic_year=selected_year,
    ).select_related('evaluation__subject__semester').order_by(
        'evaluation__subject__semester__number', '-entered_at'
    )

    # Grouper par semestre
    sem_map = {}   # {semester: [grade, ...]}
    no_sem  = []
    for g in grades_qs:
        sem = g.evaluation.subject.semester if g.evaluation and g.evaluation.subject else None
        if sem:
            if sem not in sem_map:
                sem_map[sem] = []
            sem_map[sem].append(g)
        else:
            no_sem.append(g)

    grades_by_semester = sorted(sem_map.items(), key=lambda x: x[0].number)
    if no_sem:
        grades_by_semester.append((None, no_sem))

    absence_count = StudentAttendance.objects.filter(
        student=student, status='ABSENT',
        attendance_sheet__timetable_entry__semester__academic_year=selected_year,
    ).count()

    from academic_core.apps.attendance.models import AbsenceAlertConfig
    department = None
    if enrollment and enrollment.class_group and enrollment.class_group.program:
        department = enrollment.class_group.program.department
    absence_seuil = AbsenceAlertConfig.get_seuil(department) if department else 10

    sem_avgs = SemesterAverage.objects.filter(
        student=student, semester__academic_year=selected_year,
    ).select_related('semester')

    # Bouton « Attestation de non soutenance » : uniquement affiché aux
    # étudiants actuellement en Licence 3 / Master 2 (voir students/services.py
    # ::is_non_soutenance_target_level — même détection que dans la vue PDF,
    # qui reste seule responsable de la vérification complète d'éligibilité).
    from academic_core.apps.students.services import is_non_soutenance_target_level
    show_non_soutenance = bool(
        enrollment and enrollment.class_group and enrollment.class_group.level
        and is_non_soutenance_target_level(enrollment.class_group.level.name)
    )

    return {
        'student':             student,
        'today_entries':       today_entries,
        'grades_by_semester':  grades_by_semester,
        'absence_count':       absence_count,
        'absence_seuil':       absence_seuil,
        'sem_averages':        sem_avgs,
        'enrollment':          enrollment,
        'selected_year':       selected_year,
        'available_years':     available_years,
        'show_non_soutenance': show_non_soutenance,
    }
