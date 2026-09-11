from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.generic import DetailView
from django.http import JsonResponse
from django.db.models import Q, Count
from datetime import date, datetime, timedelta
from .models import AttendanceSheet, StudentAttendance, SubjectProgress, ExtraSessionRequest
from .services import check_subject_progress, can_sign_sheet, check_syllabus_compliance
from academic_core.apps.accounting.services import record_honoraire
from academic_core.apps.students.models import Student, Enrollment
from academic_core.apps.timetable.models import TimetableEntry
from academic_core.apps.notifications.utils import notify_users


def _get_teacher_profile(user):
    return getattr(user, 'teacher_profile', None)


def _sync_session_log(sheet):
    """Synchronise lesson_content/lesson_objectives d'une AttendanceSheet vers SessionLog."""
    lesson_content    = (sheet.lesson_content    or '').strip()
    lesson_objectives = (sheet.lesson_objectives or '').strip()
    if not lesson_content and not lesson_objectives:
        return
    try:
        from academic_core.apps.timetable.models import SessionLog
        SessionLog.objects.update_or_create(
            timetable_entry=sheet.timetable_entry,
            session_date=sheet.session_date,
            defaults={
                'objectives': lesson_objectives or lesson_content,
                'content':    lesson_content,
                'remarks':    sheet.teacher_comment or '',
            },
        )
    except Exception:
        pass  # Ne pas bloquer l'action principale si la synchro échoue


def _generate_sheets_for_date(target_date, teacher=None, department=None):
    """Crée les fiches d'émargement manquantes pour les séances du jour donné."""
    day_num = target_date.isoweekday()  # 1=Lundi … 6=Samedi

    qs = TimetableEntry.objects.filter(is_active=True).select_related(
        'teacher', 'class_group__program__department', 'semester'
    )
    if teacher:
        qs = qs.filter(teacher=teacher)
    if department:
        qs = qs.filter(class_group__program__department=department)

    # Séances hebdomadaires/bi-hebdomadaires dont le jour correspond
    recurring = qs.filter(
        recurrence__in=[TimetableEntry.RECURRENCE_WEEKLY, TimetableEntry.RECURRENCE_BIWEEKLY],
        day_of_week=day_num,
    )
    # Séances ponctuelles exactement ce jour
    once = qs.filter(recurrence=TimetableEntry.RECURRENCE_ONCE, specific_date=target_date)

    created = []
    for entry in list(recurring) + list(once):
        sheet, new = AttendanceSheet.objects.get_or_create(
            timetable_entry=entry,
            session_date=target_date,
        )
        if new:
            created.append(sheet)
    return created


@login_required
def attendance_dashboard(request):
    """Tableau de bord d'émargement — enseignants & admins."""
    user       = request.user
    today      = date.today()
    teacher    = _get_teacher_profile(user)
    is_admin   = user.can_manage_dept()
    dept       = getattr(request, 'active_department', None)

    # Générer les fiches d'aujourd'hui automatiquement
    if is_admin and dept:
        _generate_sheets_for_date(today, department=dept)
    elif teacher:
        _generate_sheets_for_date(today, teacher=teacher)

    # ── Queryset de base ──────────────────────────────────────────────────────
    base_qs = AttendanceSheet.objects.select_related(
        'timetable_entry__subject',
        'timetable_entry__class_group__level',
        'timetable_entry__teacher__user',
        'timetable_entry__room',
        'validated_by',
    )

    if is_admin and dept:
        base_qs = base_qs.filter(
            timetable_entry__class_group__program__department=dept
        )
    elif teacher:
        base_qs = base_qs.filter(timetable_entry__teacher=teacher)
    else:
        base_qs = base_qs.none()

    # Scope à l'année académique en cours (is_current=True de la faculté
    # active, ou celle choisie via ?annee= — voir resolve_academic_years).
    from academic_core.apps.academic_structure.utils import resolve_academic_years
    academic_years, selected_year = resolve_academic_years(request)
    base_qs = base_qs.filter(
        timetable_entry__semester__academic_year=selected_year
    ) if selected_year else base_qs.none()

    # Filtres GET
    filter_status = request.GET.get('status', '')
    filter_date   = request.GET.get('date', '')
    if filter_status:
        base_qs = base_qs.filter(status=filter_status)
    if filter_date:
        try:
            base_qs = base_qs.filter(session_date=datetime.strptime(filter_date, '%Y-%m-%d').date())
        except ValueError:
            pass

    # ── Séances du jour ───────────────────────────────────────────────────────
    now_local = timezone.localtime(timezone.now())

    # Index des annulations du jour (entry_id → CourseCancellation)
    from academic_core.apps.cancellations.models import CourseCancellation
    cancellations_today = {
        c.timetable_entry_id: c
        for c in CourseCancellation.objects.filter(
            session_date=today,
            status=CourseCancellation.STATUS_APPROVED,
        )
    }

    def _enrich(sheet):
        """Retourne un dict avec la fiche et ses infos de fenêtre de signature."""
        entry     = sheet.timetable_entry
        start_dt  = datetime.combine(today, entry.start_time)
        opens_dt  = start_dt - timedelta(minutes=10)
        closes_dt = start_dt + timedelta(minutes=20)
        now_naive = now_local.replace(tzinfo=None)
        after = now_naive > closes_dt
        return {
            'sheet':              sheet,
            'window_open':        opens_dt <= now_naive <= closes_dt,
            'before_window':      now_naive < opens_dt,
            'after_window':       after,
            'opens_at':           opens_dt.strftime('%H:%M'),
            'closes_at':          closes_dt.strftime('%H:%M'),
            'needs_cahier_texte': after and sheet.status == AttendanceSheet.STATUS_PENDING
                                  and not (sheet.lesson_content and sheet.lesson_objectives),
            'cancellation':       cancellations_today.get(entry.pk),
        }

    today_sheets = [
        _enrich(s) for s in base_qs.filter(
            session_date=today
        ).exclude(
            status=AttendanceSheet.STATUS_VALIDATED
        ).order_by('timetable_entry__start_time')
    ]
    # Historique : tout sauf les séances d'aujourd'hui non validées
    history_sheets = base_qs.exclude(
        session_date=today,
        status__in=[AttendanceSheet.STATUS_PENDING, AttendanceSheet.STATUS_SIGNED]
    ).order_by('-session_date')[:50]

    # Regroupement en arbre Classe → Enseignant → EC pour l'affichage sous
    # forme de liste déroulante à trois niveaux.
    tree = {}
    for sheet in history_sheets:
        entry = sheet.timetable_entry
        cls_key = entry.class_group.name
        tch_key = entry.teacher.full_name
        ec_key = (entry.subject.code, entry.subject.title)
        tree.setdefault(cls_key, {}).setdefault(tch_key, {}).setdefault(ec_key, []).append(sheet)

    history_grouped = [
        {
            'name': cls_key,
            'count': sum(len(sheets) for ecs in teachers.values() for sheets in ecs.values()),
            'teachers': [
                {
                    'name': tch_key,
                    'count': sum(len(sheets) for sheets in ecs.values()),
                    'ecs': [
                        {'code': code, 'title': title, 'sheets': sheets}
                        for (code, title), sheets in sorted(ecs.items())
                    ],
                }
                for tch_key, ecs in sorted(teachers.items())
            ],
        }
        for cls_key, teachers in sorted(tree.items())
    ]

    ctx = {
        'today':            today,
        'today_sheets':     today_sheets,
        'history_grouped':  history_grouped,
        'academic_years':   academic_years,
        'selected_year':    selected_year,
        'teacher':          teacher,
        'is_admin':         is_admin,
        'status_choices':   AttendanceSheet.STATUS_CHOICES,
        'filter_status':    filter_status,
        'filter_date':      filter_date,
    }
    return render(request, 'attendance/dashboard.html', ctx)


class AttendanceSheetDetailView(LoginRequiredMixin, DetailView):
    model = AttendanceSheet
    template_name = 'attendance/sheet_detail.html'
    context_object_name = 'sheet'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        sheet = self.object
        # class_group + academic_year (pas is_active) : un étudiant réinscrit
        # (nouvelle inscription is_active=True dans sa nouvelle classe) doit
        # rester visible dans le roster de ses séances passées ici.
        enrollments = Enrollment.objects.filter(
            class_group=sheet.timetable_entry.class_group,
            academic_year=sheet.timetable_entry.semester.academic_year,
            status=Enrollment.STATUS_VALIDATED,
        ).select_related('student__user')
        att_map = {
            a.student_id: a
            for a in StudentAttendance.objects.filter(attendance_sheet=sheet)
        }
        ctx['students_attendance'] = [
            (e.student, att_map.get(e.student_id))
            for e in enrollments
        ]
        ctx['status_choices'] = StudentAttendance.STATUS_CHOICES
        teacher_profile = _get_teacher_profile(self.request.user)
        ctx['teacher_profile'] = teacher_profile

        # Fiche expirée nécessitant le cahier de texte
        is_own_teacher = teacher_profile and sheet.timetable_entry.teacher == teacher_profile
        # Calcul de l'expiration : session passée OU session d'aujourd'hui dont la fenêtre est fermée
        window_expired = False
        if sheet.session_date <= date.today():
            entry = sheet.timetable_entry
            now_local = timezone.localtime(timezone.now()).replace(tzinfo=None)
            start_dt  = datetime.combine(sheet.session_date, entry.start_time)
            closes_dt = start_dt + timedelta(minutes=20)
            window_expired = now_local > closes_dt

        ctx['is_expired_pending'] = (
            sheet.status == AttendanceSheet.STATUS_PENDING
            and window_expired
            and is_own_teacher
        )
        ctx['needs_cahier_texte'] = ctx['is_expired_pending'] and not (
            sheet.lesson_content and sheet.lesson_objectives
        )
        ctx['export_pdf_url']  = f'/attendance/{sheet.pk}/export/pdf/'
        ctx['export_word_url'] = f'/attendance/{sheet.pk}/export/word/'
        return ctx


@login_required
def sign_attendance_sheet(request, pk):
    """
    Signature de la fiche d'émargement.
    - Enseignant : uniquement le jour de la séance, entre -10 min et +20 min du début.
    - Admin du département : peut signer à tout moment et valide directement.
    """
    from datetime import date, datetime, timedelta
    from decimal import Decimal
    from academic_core.apps.accounting.models import HourlyRate

    sheet = get_object_or_404(AttendanceSheet, pk=pk)
    user  = request.user

    if sheet.status != AttendanceSheet.STATUS_PENDING:
        messages.warning(request, "Cette fiche a déjà été traitée.")
        return redirect('attendance:sheet_detail', pk=pk)

    teacher_profile = _get_teacher_profile(user)
    is_dept_admin   = user.can_manage_dept()
    is_own_teacher  = teacher_profile and sheet.timetable_entry.teacher == teacher_profile

    # Accès : soit l'enseignant concerné, soit l'admin du département
    if not is_own_teacher and not is_dept_admin:
        messages.error(request, "Accès refusé.")
        return redirect('attendance:sheet_list')

    # ── Fenêtre de signature pour l'enseignant ────────────────────────────────
    signing_allowed   = True
    time_window_msg   = None
    window_opens_at   = None
    window_closes_at  = None

    if is_own_teacher and not is_dept_admin:
        entry      = sheet.timetable_entry
        today      = date.today()
        now_local  = timezone.localtime(timezone.now())

        if sheet.session_date != today:
            signing_allowed = False
            if sheet.session_date > today:
                time_window_msg = f"Cette séance est prévue le {sheet.session_date.strftime('%d/%m/%Y')}. Vous pourrez émarger ce jour-là."
            else:
                time_window_msg = "La fenêtre d'émargement de cette séance est expirée. Contactez l'administrateur du département."
        else:
            start_dt     = datetime.combine(today, entry.start_time)
            opens_dt     = start_dt - timedelta(minutes=10)
            closes_dt    = start_dt + timedelta(minutes=20)
            now_naive    = now_local.replace(tzinfo=None)
            window_opens_at  = opens_dt
            window_closes_at = closes_dt

            if now_naive < opens_dt:
                signing_allowed = False
                diff = (opens_dt - now_naive).seconds // 60
                time_window_msg = f"La fenêtre d'émargement ouvrira à {opens_dt.strftime('%H:%M')} (dans {diff} min)."
            elif now_naive > closes_dt:
                signing_allowed = False
                time_window_msg = f"La fenêtre d'émargement a fermé à {closes_dt.strftime('%H:%M')}. Contactez l'administrateur du département."

    # ── Honoraire de la séance ────────────────────────────────────────────────
    hourly_rate  = None
    session_amount = None
    try:
        entry = sheet.timetable_entry
        hourly_rate = HourlyRate.objects.get(
            department=entry.class_group.program.department,
            level=entry.class_group.level,
            academic_year=entry.semester.academic_year,
        )
        session_amount = hourly_rate.amount_for_session(entry.duration_hours)
    except Exception:
        pass

    # Vérifier si la séance a été annulée ou reportée pour cette date précise
    from academic_core.apps.cancellations.models import CourseCancellation as _Cancel
    _cancel = _Cancel.objects.filter(
        timetable_entry=sheet.timetable_entry,
        session_date=sheet.session_date,
        status=_Cancel.STATUS_APPROVED,
    ).first()
    if _cancel and not is_dept_admin:
        type_label = 'reportée' if _cancel.request_type == _Cancel.TYPE_POSTPONEMENT else 'annulée'
        signing_allowed = False
        time_window_msg = (
            f"Cette séance a été {type_label} pour le {sheet.session_date.strftime('%d/%m/%Y')}. "
            f"L'émargement n'est pas possible."
        )

    # Vérifier si le planning est suspendu pour cette classe à cette date
    from academic_core.apps.timetable.models import PlanningHoliday
    holiday_qs = PlanningHoliday.objects.filter(
        class_group=sheet.timetable_entry.class_group,
        start_date__lte=sheet.session_date,
        end_date__gte=sheet.session_date,
    )
    if holiday_qs.exists() and not is_dept_admin:
        h = holiday_qs.first()
        signing_allowed = False
        time_window_msg = (
            f"Le planning de cette classe est suspendu du {h.start_date.strftime('%d/%m/%Y')} "
            f"au {h.end_date.strftime('%d/%m/%Y')}"
            + (f" ({h.reason})" if h.reason else "") + ". Émargement impossible."
        )

    # Vérifier si le volume horaire est atteint (bloquage)
    volume_ok, volume_msg = can_sign_sheet(sheet)
    if not volume_ok and is_own_teacher and not is_dept_admin:
        signing_allowed = False
        time_window_msg = volume_msg

    if request.method == 'POST':
        if sheet.timetable_entry.semester.is_locked:
            messages.error(request, sheet.timetable_entry.semester.lock_message)
            return redirect('attendance:sheet_list')

        if not signing_allowed and not is_dept_admin:
            messages.error(request, time_window_msg or "Émargement non autorisé.")
            return redirect('attendance:sheet_list')

        # Re-check volume for admin path too
        if not volume_ok and is_dept_admin:
            messages.warning(request, f"Attention : {volume_msg}")

        lesson_content = request.POST.get('lesson_content', '').strip()
        if not lesson_content:
            messages.error(request, "Le contenu de la séance (cahier de texte) est obligatoire avant de signer.")
            ctx = _sign_context(sheet, hourly_rate, session_amount, is_dept_admin,
                                signing_allowed, time_window_msg, window_opens_at, window_closes_at,
                                volume_ok, volume_msg)
            return render(request, 'attendance/sign_sheet.html', ctx)

        lesson_objectives = request.POST.get('lesson_objectives', '').strip()
        sheet.lesson_content     = lesson_content
        sheet.lesson_objectives  = lesson_objectives
        sheet.teacher_comment    = request.POST.get('comment', '').strip()
        sheet.teacher_signature_at = timezone.now()

        if is_dept_admin and not is_own_teacher:
            # Admin signe à la place + valide directement
            sheet.signed_by_admin = True
            sheet.status          = AttendanceSheet.STATUS_VALIDATED
            sheet.validated_by    = user
            sheet.validated_at    = timezone.now()
            sheet.save()
            record_honoraire(sheet, validated_by=user)
            check_subject_progress(sheet)
            check_syllabus_compliance(sheet)
            messages.success(request, "Émargement effectué et validé par l'administrateur du département.")
        else:
            sheet.status = AttendanceSheet.STATUS_SIGNED
            sheet.save()
            messages.success(request, "Fiche d'émargement signée avec succès.")

        # ── Synchroniser vers le Cahier de Texte (SessionLog) ─────────────────
        _sync_session_log(sheet)

        return redirect('attendance:sheet_detail', pk=pk)

    ctx = _sign_context(sheet, hourly_rate, session_amount, is_dept_admin,
                        signing_allowed, time_window_msg, window_opens_at, window_closes_at,
                        volume_ok, volume_msg)
    return render(request, 'attendance/sign_sheet.html', ctx)


def _course_plan_sessions_json(entry):
    """Séances du plan de cours de l'enseignant pour ce module (subject ×
    class_group × academic_year) — sérialisées pour le sélecteur JS
    d'auto-remplissage du cahier de texte (voir sign_sheet.html /
    fill_cahier_texte.html)."""
    import json
    from .models import CoursePlan

    try:
        plan = CoursePlan.objects.get(
            subject=entry.subject, class_group=entry.class_group,
            academic_year=entry.semester.academic_year, teacher=entry.teacher,
        )
    except CoursePlan.DoesNotExist:
        return '[]'

    sessions = [
        {
            'id':       s.pk,
            'numero':   s.numero,
            'titre':    s.titre,
            'objectif': s.objectif,
            'contenu':  s.contenu_prevu,
        }
        for s in plan.sessions.all()
    ]
    return json.dumps(sessions)


def _sign_context(sheet, hourly_rate, session_amount, is_dept_admin,
                  signing_allowed, time_window_msg, window_opens_at, window_closes_at,
                  volume_ok=True, volume_msg=None):
    entry = sheet.timetable_entry
    try:
        progress = SubjectProgress.objects.get(
            subject=entry.subject,
            class_group=entry.class_group,
            academic_year=entry.semester.academic_year,
        )
    except SubjectProgress.DoesNotExist:
        progress = None
    return {
        'sheet':           sheet,
        'hourly_rate':     hourly_rate,
        'session_amount':  session_amount,
        'is_dept_admin':   is_dept_admin,
        'signing_allowed': signing_allowed,
        'time_window_msg': time_window_msg,
        'window_opens_at':  window_opens_at,
        'window_closes_at': window_closes_at,
        'volume_ok':        volume_ok,
        'volume_msg':       volume_msg,
        'progress':         progress,
        'plan_sessions_json': _course_plan_sessions_json(entry),
    }


@login_required
def validate_attendance_sheet(request, pk):
    """Le responsable pédagogique ou l'enseignant propriétaire valide ou rejette une fiche."""
    sheet = get_object_or_404(AttendanceSheet, pk=pk)
    user = request.user

    teacher_profile = _get_teacher_profile(user)
    is_own_teacher  = teacher_profile and sheet.timetable_entry.teacher == teacher_profile
    is_dept_admin   = user.can_manage_dept()

    if not (is_dept_admin or is_own_teacher):
        messages.error(request, "Accès refusé.")
        return redirect('attendance:sheet_list')

    if sheet.status != AttendanceSheet.STATUS_SIGNED:
        messages.warning(request, "La fiche doit être signée avant validation.")
        return redirect('attendance:sheet_detail', pk=pk)

    if request.method == 'POST':
        if sheet.timetable_entry.semester.is_locked:
            messages.error(request, sheet.timetable_entry.semester.lock_message)
            return redirect('attendance:sheet_detail', pk=pk)

        action = request.POST.get('action')
        if action == 'validate':
            # Auto-marquer absents les non-pointés avant de valider
            _auto_mark_absents(sheet, sheet.timetable_entry)
            sheet.status = AttendanceSheet.STATUS_VALIDATED
            sheet.validated_by = user
            sheet.validated_at = timezone.now()
            sheet.save()
            _sync_session_log(sheet)
            record_honoraire(sheet, validated_by=user)
            check_subject_progress(sheet)
            check_syllabus_compliance(sheet)
            if not is_own_teacher:
                # Notifier l'enseignant seulement si c'est l'admin qui valide
                notify_users(
                    recipients=[sheet.timetable_entry.teacher.user],
                    notification_type='SHEET_VALIDATED',
                    title="Émargement validé",
                    message=f"Votre fiche du {sheet.session_date} a été validée.",
                    link=f"/attendance/{sheet.pk}/",
                )
            messages.success(request, "Fiche validée. Les absences ont été enregistrées automatiquement.")
        elif action == 'reject':
            if not is_dept_admin:
                messages.error(request, "Seul l'administrateur peut rejeter une fiche.")
                return redirect('attendance:sheet_detail', pk=pk)
            sheet.status = AttendanceSheet.STATUS_REJECTED
            sheet.rejection_reason = request.POST.get('reason', '')
            sheet.validated_by = user
            sheet.validated_at = timezone.now()
            sheet.save()
            messages.warning(request, "Fiche rejetée.")
        return redirect('attendance:sheet_detail', pk=pk)

    return render(request, 'attendance/validate_sheet.html', {
        'sheet':        sheet,
        'is_own_teacher': is_own_teacher,
        'is_dept_admin':  is_dept_admin,
    })


@login_required
def reject_attendance_sheet(request, pk):
    """L'administrateur de département peut rejeter n'importe quelle fiche (PENDING ou SIGNED)."""
    if request.method != 'POST':
        return redirect('attendance:sheet_detail', pk=pk)

    sheet = get_object_or_404(AttendanceSheet, pk=pk)
    user  = request.user

    if not user.can_manage_dept():
        messages.error(request, "Seul l'administrateur de département peut rejeter une fiche.")
        return redirect('attendance:sheet_detail', pk=pk)

    if sheet.status == AttendanceSheet.STATUS_VALIDATED:
        messages.warning(request, "Une fiche déjà validée ne peut pas être rejetée directement. Modifiez-la d'abord.")
        return redirect('attendance:sheet_detail', pk=pk)

    if sheet.status == AttendanceSheet.STATUS_REJECTED:
        messages.info(request, "Cette fiche est déjà rejetée.")
        return redirect('attendance:sheet_detail', pk=pk)

    if sheet.timetable_entry.semester.is_locked:
        messages.error(request, sheet.timetable_entry.semester.lock_message)
        return redirect('attendance:sheet_detail', pk=pk)

    reason = request.POST.get('reason', '').strip()
    sheet.status           = AttendanceSheet.STATUS_REJECTED
    sheet.rejection_reason = reason
    sheet.validated_by     = user
    sheet.validated_at     = timezone.now()
    sheet.save(update_fields=['status', 'rejection_reason', 'validated_by', 'validated_at'])

    notify_users(
        recipients=[sheet.timetable_entry.teacher.user],
        notification_type='SHEET_VALIDATED',
        title="Émargement rejeté",
        message=f"Votre fiche du {sheet.session_date} ({sheet.timetable_entry.subject.title}) a été rejetée."
                + (f" Motif : {reason}" if reason else ""),
        link=f"/attendance/{sheet.pk}/",
    )
    messages.warning(request, "Fiche d'émargement rejetée.")
    return redirect('attendance:sheet_list')


@login_required
def edit_attendance_sheet(request, pk):
    """Le responsable ou l'admin peut modifier une fiche d'émargement."""
    sheet = get_object_or_404(AttendanceSheet, pk=pk)
    user = request.user

    if not (user.can_manage_dept()):
        messages.error(request, "Accès refusé.")
        return redirect('attendance:sheet_list')

    if request.method == 'POST':
        if sheet.timetable_entry.semester.is_locked:
            messages.error(request, sheet.timetable_entry.semester.lock_message)
            return redirect('attendance:sheet_detail', pk=pk)

        sheet.session_date = request.POST.get('session_date', sheet.session_date)
        sheet.status = request.POST.get('status', sheet.status)
        sheet.teacher_comment = request.POST.get('teacher_comment', sheet.teacher_comment)
        sheet.rejection_reason = request.POST.get('rejection_reason', sheet.rejection_reason)
        if sheet.status in [AttendanceSheet.STATUS_VALIDATED, AttendanceSheet.STATUS_REJECTED]:
            sheet.validated_by = user
            sheet.validated_at = timezone.now()
        sheet.save()
        messages.success(request, "Fiche modifiée avec succès.")
        return redirect('attendance:sheet_detail', pk=pk)

    return render(request, 'attendance/sheet_edit.html', {
        'sheet': sheet,
        'status_choices': AttendanceSheet.STATUS_CHOICES,
    })


@login_required
def fill_cahier_texte(request, pk):
    """
    Permet à l'enseignant de saisir les objectifs et le contenu du cours
    lorsque la fenêtre d'émargement est expirée (séance passée, fiche PENDING).
    Les deux champs sont obligatoires.
    """
    sheet = get_object_or_404(AttendanceSheet, pk=pk)
    user = request.user
    teacher_profile = _get_teacher_profile(user)

    is_own_teacher = teacher_profile and sheet.timetable_entry.teacher == teacher_profile
    if not is_own_teacher and not user.can_manage_dept():
        messages.error(request, "Accès refusé.")
        return redirect('attendance:sheet_list')

    if sheet.status != AttendanceSheet.STATUS_PENDING:
        messages.warning(request, "Le cahier de texte ne peut être modifié que sur une fiche en attente.")
        return redirect('attendance:sheet_detail', pk=pk)

    # Séance future → pas encore passée, utiliser l'émargement normal
    if sheet.session_date > date.today():
        messages.warning(request, "Utilisez l'émargement normal pour les séances à venir.")
        return redirect('attendance:sheet_detail', pk=pk)

    # Séance d'aujourd'hui : vérifier si la fenêtre est encore ouverte
    if sheet.session_date == date.today():
        entry = sheet.timetable_entry
        now_local = timezone.localtime(timezone.now()).replace(tzinfo=None)
        from datetime import datetime as _dt
        start_dt  = _dt.combine(date.today(), entry.start_time)
        closes_dt = start_dt + timedelta(minutes=20)
        if now_local <= closes_dt:
            messages.warning(request, "La fenêtre d'émargement est encore ouverte. Utilisez le bouton Signer.")
            return redirect('attendance:sign_sheet', pk=pk)

    if request.method == 'POST':
        if sheet.timetable_entry.semester.is_locked:
            messages.error(request, sheet.timetable_entry.semester.lock_message)
            return redirect('attendance:sheet_detail', pk=pk)

        lesson_objectives = request.POST.get('lesson_objectives', '').strip()
        lesson_content    = request.POST.get('lesson_content', '').strip()
        errors = []
        if not lesson_objectives:
            errors.append("Les objectifs du cours sont obligatoires.")
        if not lesson_content:
            errors.append("Le contenu du cours est obligatoire.")

        if errors:
            for e in errors:
                messages.error(request, e)
            return render(request, 'attendance/fill_cahier_texte.html', {
                'sheet': sheet,
                'lesson_objectives': lesson_objectives,
                'lesson_content': lesson_content,
                'plan_sessions_json': _course_plan_sessions_json(sheet.timetable_entry),
            })

        sheet.lesson_objectives = lesson_objectives
        sheet.lesson_content    = lesson_content
        sheet.save(update_fields=['lesson_objectives', 'lesson_content'])
        _sync_session_log(sheet)
        messages.success(request, "Cahier de texte enregistré. La fiche reste en attente de validation par l'administrateur.")
        return redirect('attendance:sheet_detail', pk=pk)

    return render(request, 'attendance/fill_cahier_texte.html', {
        'sheet': sheet,
        'lesson_objectives': sheet.lesson_objectives,
        'lesson_content': sheet.lesson_content,
        'plan_sessions_json': _course_plan_sessions_json(sheet.timetable_entry),
    })


@login_required
def delete_attendance_sheet(request, pk):
    """Le responsable ou l'admin peut supprimer une fiche d'émargement."""
    sheet = get_object_or_404(AttendanceSheet, pk=pk)
    user = request.user

    if not (user.can_manage_dept()):
        messages.error(request, "Accès refusé.")
        return redirect('attendance:sheet_list')

    if request.method == 'POST':
        if sheet.timetable_entry.semester.is_locked:
            messages.error(request, sheet.timetable_entry.semester.lock_message)
            return redirect('attendance:sheet_list')

        sheet.delete()
        messages.success(request, "Fiche d'émargement supprimée.")
        return redirect('attendance:sheet_list')

    return render(request, 'attendance/sheet_confirm_delete.html', {'sheet': sheet})


@login_required
def record_student_attendance(request, sheet_pk):
    """Enregistrement des présences/absences des étudiants."""
    sheet = get_object_or_404(AttendanceSheet, pk=sheet_pk)
    user = request.user

    teacher_profile = _get_teacher_profile(user)
    is_own_teacher = teacher_profile and sheet.timetable_entry.teacher == teacher_profile
    if not (is_own_teacher or user.can_manage_dept()):
        messages.error(request, "Accès refusé.")
        return redirect('attendance:sheet_list')

    if request.method == 'POST':
        if sheet.timetable_entry.semester.is_locked:
            messages.error(request, sheet.timetable_entry.semester.lock_message)
            return redirect('attendance:sheet_detail', pk=sheet_pk)

        enrollments = Enrollment.objects.filter(
            class_group=sheet.timetable_entry.class_group,
            academic_year=sheet.timetable_entry.semester.academic_year,
            status=Enrollment.STATUS_VALIDATED,
        )
        absent_students = []
        for enrollment in enrollments:
            student = enrollment.student
            status = request.POST.get(f'status_{student.pk}', StudentAttendance.STATUS_PRESENT)
            comment = request.POST.get(f'comment_{student.pk}', '')
            StudentAttendance.objects.update_or_create(
                attendance_sheet=sheet,
                student=student,
                defaults={'status': status, 'comment': comment},
            )
            if status == StudentAttendance.STATUS_ABSENT:
                absent_students.append(student)

        if absent_students:
            notify_users(
                recipients=[s.user for s in absent_students],
                notification_type='ABSENCE',
                title="Absence enregistrée",
                message=f"Une absence a été enregistrée pour le {sheet.session_date} — {sheet.timetable_entry.subject.title}.",
                priority='HIGH',
            )

        messages.success(request, "Présences enregistrées avec succès.")
        return redirect('attendance:sheet_detail', pk=sheet_pk)

    enrollments = Enrollment.objects.filter(
        class_group=sheet.timetable_entry.class_group,
        academic_year=sheet.timetable_entry.semester.academic_year,
        status=Enrollment.STATUS_VALIDATED,
    ).select_related('student__user')
    att_map = {
        a.student_id: a
        for a in StudentAttendance.objects.filter(attendance_sheet=sheet)
    }
    students_data = [(e.student, att_map.get(e.student_id)) for e in enrollments]
    return render(request, 'attendance/record_attendance.html', {
        'sheet': sheet,
        'students_data': students_data,
        'status_choices': StudentAttendance.STATUS_CHOICES,
    })


@login_required
def update_student_attendance(request, att_pk):
    """Mise à jour d'une présence individuelle (POST inline depuis sheet_detail)."""
    att = get_object_or_404(StudentAttendance, pk=att_pk)
    sheet = att.attendance_sheet
    teacher_profile = _get_teacher_profile(request.user)
    is_own_teacher = teacher_profile and sheet.timetable_entry.teacher == teacher_profile
    if not (is_own_teacher or request.user.can_manage_dept()):
        messages.error(request, "Accès refusé.")
        return redirect('attendance:sheet_detail', pk=sheet.pk)

    if request.method == 'POST':
        if sheet.timetable_entry.semester.is_locked:
            messages.error(request, sheet.timetable_entry.semester.lock_message)
            return redirect('attendance:sheet_detail', pk=sheet.pk)

        att.status  = request.POST.get('status', att.status)
        att.comment = request.POST.get('comment', att.comment)
        att.save()
        messages.success(request, "Présence mise à jour.")
    return redirect('attendance:sheet_detail', pk=sheet.pk)


@login_required
def my_absences(request):
    """Liste des absences de l'étudiant connecté."""
    if not request.user.is_etudiant():
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    try:
        student = request.user.student_profile
    except Exception:
        return render(request, 'attendance/my_absences.html', {'absences': [], 'stats': {}})

    from academic_core.apps.students.utils import resolve_student_year
    selected_year, available_years, enrollment = resolve_student_year(request, student)

    attendances = (
        StudentAttendance.objects
        .filter(
            student=student,
            attendance_sheet__timetable_entry__semester__academic_year=selected_year,
        )
        .select_related(
            'attendance_sheet__timetable_entry__subject',
            'attendance_sheet__timetable_entry__teacher__user',
            'attendance_sheet__timetable_entry__class_group',
        )
        .order_by('-attendance_sheet__session_date')
    )

    total     = attendances.count()
    present   = attendances.filter(status=StudentAttendance.STATUS_PRESENT).count()
    absent    = attendances.filter(status=StudentAttendance.STATUS_ABSENT).count()
    justified = attendances.filter(status=StudentAttendance.STATUS_JUSTIFIED).count()
    late      = attendances.filter(status=StudentAttendance.STATUS_LATE).count()
    gender    = getattr(student, 'gender', 'M') or 'M'

    from .models import AbsenceAlertConfig
    department = None
    if enrollment and enrollment.class_group and enrollment.class_group.program:
        department = enrollment.class_group.program.department
    absence_seuil = AbsenceAlertConfig.get_seuil(department) if department else 10

    return render(request, 'attendance/my_absences.html', {
        'attendances':     attendances,
        'student':         student,
        'gender':          gender,
        'enrollment':      enrollment,
        'selected_year':   selected_year,
        'available_years': available_years,
        'absence_seuil':   absence_seuil,
        'stats': {
            'total':     total,
            'present':   present,
            'absent':    absent,
            'justified': justified,
            'late':      late,
        },
    })


@login_required
def justify_absence(request, att_pk):
    """
    Permet à l'étudiant de soumettre une justification (motif + pièce jointe
    optionnelle) pour l'une de ses propres absences non justifiées. Ne
    change PAS le statut de l'absence (reste ABSENT, donc toujours
    comptabilisée) tant qu'un administrateur du département ne l'a pas
    approuvée (voir absence_justification_review) — seule l'approbation
    fait passer le statut à JUSTIFIED, ce qui la retire automatiquement du
    décompte utilisé partout ailleurs (tableau de bord, alertes d'absences).
    Une nouvelle soumission est possible après un rejet.
    """
    att = get_object_or_404(StudentAttendance, pk=att_pk)
    student = getattr(request.user, 'student_profile', None)
    if not student or att.student_id != student.pk:
        messages.error(request, "Accès refusé.")
        return redirect('attendance:my_absences')

    if att.status != StudentAttendance.STATUS_ABSENT:
        messages.warning(request, "Seule une absence non justifiée peut être justifiée.")
        return redirect('attendance:my_absences')

    if att.justification_status in (StudentAttendance.JUSTIFICATION_PENDING, StudentAttendance.JUSTIFICATION_APPROVED):
        messages.warning(request, "Une justification a déjà été soumise pour cette absence.")
        return redirect('attendance:my_absences')

    if request.method == 'POST':
        reason = request.POST.get('justification_reason', '').strip()
        if not reason:
            messages.error(request, "Veuillez indiquer le motif de votre absence.")
            return redirect('attendance:my_absences')

        att.justification_reason = reason
        if request.FILES.get('justification_document'):
            att.justification_document = request.FILES['justification_document']
        att.justification_status = StudentAttendance.JUSTIFICATION_PENDING
        att.justification_submitted_at = timezone.now()
        att.justification_reviewed_by = None
        att.justification_reviewed_at = None
        att.justification_admin_note = ''
        att.save(update_fields=[
            'justification_reason', 'justification_document', 'justification_status',
            'justification_submitted_at', 'justification_reviewed_by',
            'justification_reviewed_at', 'justification_admin_note',
        ])

        entry = att.attendance_sheet.timetable_entry
        department = getattr(getattr(entry.class_group, 'program', None), 'department', None)
        if department:
            from academic_core.apps.accounts.models import User, Role
            recipients = list(
                User.objects.filter(
                    role__name__in=[Role.RESPONSABLE, Role.ASSISTANTE],
                    department=department, is_active=True,
                ).distinct()
            )
            if recipients:
                notify_users(
                    recipients=recipients,
                    notification_type='ABSENCE',
                    title=f"Justification d'absence à examiner — {student.full_name}",
                    message=(
                        f"{student.full_name} a soumis une justification pour son absence du "
                        f"{att.attendance_sheet.session_date} en {entry.subject.title}."
                    ),
                    priority='MEDIUM',
                    link='/attendance/justifications/',
                )

        messages.success(request, "Votre justification a été envoyée. Elle sera examinée par le département.")

    return redirect('attendance:my_absences')


@login_required
def absence_justifications_admin(request):
    """Liste des justifications d'absence en attente pour le département du chef/assistante connecté."""
    if not request.user.can_manage_dept():
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    dept = request.active_department
    if not dept:
        messages.warning(request, "Veuillez sélectionner un département.")
        return redirect('academic_structure:select_department')

    justifications = (
        StudentAttendance.objects
        .filter(
            justification_status=StudentAttendance.JUSTIFICATION_PENDING,
            attendance_sheet__timetable_entry__class_group__program__department=dept,
        )
        .select_related(
            'student__user', 'attendance_sheet__timetable_entry__subject',
            'attendance_sheet__timetable_entry__class_group',
        )
        .order_by('justification_submitted_at')
    )

    return render(request, 'attendance/absence_justifications_admin.html', {
        'justifications': justifications,
        'dept': dept,
    })


@login_required
def absence_justification_review(request, att_pk):
    """Approuve ou rejette une justification d'absence soumise par un étudiant."""
    att = get_object_or_404(StudentAttendance, pk=att_pk)
    if not request.user.can_manage_dept():
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    if att.justification_status != StudentAttendance.JUSTIFICATION_PENDING:
        messages.warning(request, "Cette justification a déjà été traitée.")
        return redirect('attendance:absence_justifications_admin')

    if request.method == 'POST':
        action = request.POST.get('action')
        att.justification_reviewed_by = request.user
        att.justification_reviewed_at = timezone.now()

        if action == 'approve':
            att.status = StudentAttendance.STATUS_JUSTIFIED
            att.justification_status = StudentAttendance.JUSTIFICATION_APPROVED
            att.justified_at = timezone.now()
            att.save()
            messages.success(request, "Justification approuvée — l'absence est désormais justifiée.")
            title = "Votre justification d'absence a été approuvée"
            message = (
                f"Votre justification pour l'absence du {att.attendance_sheet.session_date} en "
                f"{att.attendance_sheet.timetable_entry.subject.title} a été approuvée. "
                f"Cette absence n'est plus comptabilisée."
            )
        elif action == 'reject':
            admin_note = request.POST.get('admin_note', '').strip()
            att.justification_status = StudentAttendance.JUSTIFICATION_REJECTED
            att.justification_admin_note = admin_note
            att.save()
            messages.warning(request, "Justification rejetée.")
            title = "Votre justification d'absence a été rejetée"
            message = (
                f"Votre justification pour l'absence du {att.attendance_sheet.session_date} en "
                f"{att.attendance_sheet.timetable_entry.subject.title} a été rejetée."
                + (f" Motif : {admin_note}" if admin_note else "")
                + " Cette absence reste comptabilisée. Vous pouvez soumettre une nouvelle justification."
            )
        else:
            messages.error(request, "Action invalide.")
            return redirect('attendance:absence_justifications_admin')

        if att.student.user:
            notify_users(
                recipients=[att.student.user],
                notification_type='ABSENCE',
                title=title,
                message=message,
                priority='MEDIUM',
                link='/attendance/mes-absences/',
            )

    return redirect('attendance:absence_justifications_admin')


@login_required
def delete_student_attendance(request, att_pk):
    """Suppression d'une présence individuelle."""
    att = get_object_or_404(StudentAttendance, pk=att_pk)
    sheet = att.attendance_sheet
    teacher_profile = _get_teacher_profile(request.user)
    is_own_teacher = teacher_profile and sheet.timetable_entry.teacher == teacher_profile
    if not (is_own_teacher or request.user.can_manage_dept()):
        messages.error(request, "Accès refusé.")
        return redirect('attendance:sheet_detail', pk=sheet.pk)

    if request.method == 'POST':
        if sheet.timetable_entry.semester.is_locked:
            messages.error(request, sheet.timetable_entry.semester.lock_message)
            return redirect('attendance:sheet_detail', pk=sheet.pk)

        att.delete()
        messages.success(request, "Présence supprimée.")
    return redirect('attendance:sheet_detail', pk=sheet.pk)


# ── Demandes de séances supplémentaires ──────────────────────────────────────

@login_required
def my_modules(request):
    """Vue 'Mes modules' : toutes les matières assignées à l'enseignant avec avancement."""
    from academic_core.apps.academic_structure.models import AcademicYear
    from .models import CoursePlan

    teacher = _get_teacher_profile(request.user)
    if not teacher:
        messages.error(request, "Accès réservé aux enseignants.")
        return redirect('dashboard:index')

    current_year = AcademicYear.objects.filter(is_current=True).first()

    entries = (
        TimetableEntry.objects
        .filter(teacher=teacher, is_active=True)
        .select_related('subject', 'class_group__program__department', 'semester__academic_year')
        .order_by('class_group__program__department__name', 'subject__title')
    )
    if current_year:
        entries = entries.filter(semester__academic_year=current_year)

    # Plans de cours déjà définis (avec au moins une séance) pour cet enseignant,
    # pour savoir quels modules affichent le bouton "Plan de cours" en alerte.
    plans_with_sessions = set(
        CoursePlan.objects.filter(teacher=teacher, sessions__isnull=False)
        .values_list('subject_id', 'class_group_id', 'academic_year_id')
        .distinct()
    )

    # Build a deduplicated list of (subject, class_group, semester/academic_year)
    seen = set()
    modules = []
    for entry in entries:
        key = (entry.subject_id, entry.class_group_id, entry.semester_id)
        if key in seen:
            continue
        seen.add(key)

        acad_year = entry.semester.academic_year if entry.semester else current_year
        try:
            progress = SubjectProgress.objects.get(
                subject=entry.subject,
                class_group=entry.class_group,
                academic_year=acad_year,
            )
            hours_done = progress.hours_done
            extra_hours = progress.extra_hours
            volume_total = progress.volume_total
            percent = progress.percent_done
        except SubjectProgress.DoesNotExist:
            hours_done = 0
            extra_hours = 0
            volume_total = entry.subject.volume_hours or 0
            percent = 0

        vol_restant = max(float(volume_total) - float(hours_done), 0)
        modules.append({
            'subject':      entry.subject,
            'class_group':  entry.class_group,
            'semester':     entry.semester,
            'department':   entry.class_group.program.department if entry.class_group.program else None,
            'extra_hours':  extra_hours,
            'volume_total': volume_total,
            'hours_done':   hours_done,
            'vol_restant':  vol_restant,
            'percent':      percent,
            'is_complete':  vol_restant <= 0,
            'has_course_plan': (entry.subject_id, entry.class_group_id, acad_year.pk if acad_year else None) in plans_with_sessions,
        })

    return render(request, 'attendance/my_modules.html', {
        'modules': modules,
        'current_year': current_year,
    })


@login_required
def module_detail(request, subject_id, class_group_id, semester_id, teacher_id=None):
    """
    Détail d'un module (EC × classe × semestre) : liste des séances déroulées.

    - Sans teacher_id : l'enseignant consulte l'un de ses propres modules
      (depuis « Mes modules »).
    - Avec teacher_id : un admin/responsable de département consulte le module
      d'un enseignant quelconque (depuis « Modules planifiés »), à condition
      que ce module reste dans son périmètre (département/faculté actifs).
    """
    from academic_core.apps.timetable.models import SessionLog
    from academic_core.apps.teachers.models import Teacher

    is_admin_view = teacher_id is not None
    back_url   = 'attendance:my_modules'
    back_label = 'Mes modules'

    if is_admin_view:
        if not request.user.can_manage_dept():
            messages.error(request, "Accès réservé aux administrateurs de département.")
            return redirect('dashboard:index')
        teacher = get_object_or_404(Teacher, pk=teacher_id)
        back_url   = 'attendance:planned_modules_admin'
        back_label = 'Modules planifiés'
    else:
        teacher = _get_teacher_profile(request.user)
        if not teacher:
            messages.error(request, "Accès réservé aux enseignants.")
            return redirect('dashboard:index')

    entries = list(
        TimetableEntry.objects
        .filter(
            teacher=teacher, subject_id=subject_id,
            class_group_id=class_group_id, semester_id=semester_id,
        )
        .select_related('subject', 'class_group', 'semester__academic_year', 'room')
    )
    if not entries:
        messages.error(request, "Module introuvable ou non assigné.")
        return redirect(back_url)

    if is_admin_view:
        dept    = getattr(request, 'active_department', None)
        faculty = getattr(request, 'active_faculty', None)
        entry_dept = entries[0].class_group.program.department if entries[0].class_group.program else None
        out_of_scope = (
            (dept and entry_dept and entry_dept.pk != dept.pk) or
            (not dept and faculty and entry_dept and entry_dept.faculty_id != faculty.pk)
        )
        if out_of_scope:
            messages.error(request, "Ce module n'est pas dans votre périmètre.")
            return redirect(back_url)

    subject     = entries[0].subject
    class_group = entries[0].class_group
    semester    = entries[0].semester

    entry_pks = [e.pk for e in entries]

    sheets = (
        AttendanceSheet.objects
        .filter(timetable_entry_id__in=entry_pks)
        .select_related('timetable_entry')
        .order_by('-session_date')
    )

    logs = SessionLog.objects.filter(timetable_entry_id__in=entry_pks)
    log_map = {(l.timetable_entry_id, l.session_date): l for l in logs}

    sessions = []
    for sheet in sheets:
        sessions.append({
            'sheet':    sheet,
            'entry':    sheet.timetable_entry,
            'date':     sheet.session_date,
            'log':      log_map.get((sheet.timetable_entry_id, sheet.session_date)),
            'duration': sheet.timetable_entry.duration_hours,
        })

    acad_year = semester.academic_year if semester else None
    try:
        progress = SubjectProgress.objects.get(
            subject=subject, class_group=class_group, academic_year=acad_year,
        )
    except SubjectProgress.DoesNotExist:
        progress = None

    hours_done   = progress.hours_done if progress else 0
    extra_hours  = progress.extra_hours if progress else 0
    volume_total = progress.volume_total if progress else (subject.volume_hours or 0)
    percent      = progress.percent_done if progress else 0
    vol_restant  = max(float(volume_total) - float(hours_done), 0)

    return render(request, 'attendance/module_detail.html', {
        'subject':       subject,
        'class_group':   class_group,
        'semester':      semester,
        'sessions':      sessions,
        'hours_done':    hours_done,
        'extra_hours':   extra_hours,
        'volume_total':  volume_total,
        'vol_restant':   vol_restant,
        'percent':       percent,
        'is_complete':   vol_restant <= 0 and float(volume_total) > 0,
        'teacher':       teacher if is_admin_view else None,
        'back_url':      back_url,
        'back_label':    back_label,
    })


@login_required
def extra_request_create(request):
    """L'enseignant soumet une demande de séances supplémentaires."""
    from academic_core.apps.subjects.models import Subject
    from academic_core.apps.academic_structure.models import Class, AcademicYear

    teacher = _get_teacher_profile(request.user)
    if not teacher:
        messages.error(request, "Accès réservé aux enseignants.")
        return redirect('dashboard:index')

    # Pré-remplissage depuis les paramètres GET
    subject_pk = request.GET.get('subject') or request.POST.get('subject')
    class_pk   = request.GET.get('class')   or request.POST.get('class_group')
    year_pk    = request.GET.get('year')    or request.POST.get('academic_year')

    # Une nouvelle demande de séances supplémentaires concerne l'année
    # académique en cours — les modules/classes proposés doivent donc être
    # ceux effectivement enseignés cette année-là.
    faculty_te = getattr(teacher.user, 'department', None)
    faculty_te = faculty_te.faculty if faculty_te else None
    current_year = AcademicYear.objects.filter(is_current=True)
    current_year = current_year.filter(faculty=faculty_te) if faculty_te else current_year
    current_year = current_year.first()

    subjects_qs = Subject.objects.filter(timetable_entries__teacher=teacher)
    classes_qs  = Class.objects.filter(timetable_entries__teacher=teacher)
    if current_year:
        subjects_qs = subjects_qs.filter(timetable_entries__semester__academic_year=current_year)
        classes_qs  = classes_qs.filter(timetable_entries__semester__academic_year=current_year)
    subjects     = subjects_qs.distinct().order_by('title')
    classes      = classes_qs.distinct().order_by('name')
    years        = AcademicYear.objects.order_by('-start_date')
    if faculty_te:
        years = years.filter(faculty=faculty_te)

    if request.method == 'POST':
        subject = get_object_or_404(Subject, pk=request.POST.get('subject'))
        class_group = get_object_or_404(Class, pk=request.POST.get('class_group'))
        academic_year = get_object_or_404(AcademicYear, pk=request.POST.get('academic_year'))
        reason = request.POST.get('reason', '').strip()
        extra_hours_requested = request.POST.get('extra_hours_requested', '').strip()

        if not reason or not extra_hours_requested:
            messages.error(request, "Tous les champs sont obligatoires.")
        else:
            from decimal import Decimal as D
            req = ExtraSessionRequest.objects.create(
                subject=subject,
                class_group=class_group,
                academic_year=academic_year,
                teacher=teacher,
                reason=reason,
                extra_hours_requested=D(extra_hours_requested),
            )
            # Notifier les admins du département
            from academic_core.apps.accounts.models import User, Role
            dept = class_group.program.department
            admins = User.objects.filter(
                role__name__in=[Role.RESPONSABLE, Role.ASSISTANTE, Role.ADMIN],
                department=dept,
            )
            notify_users(
                recipients=list(admins),
                notification_type='EXTRA_REQUEST',
                title=f"Demande séances supplémentaires — {subject.title}",
                message=(
                    f"{teacher.user.get_full_name()} demande {extra_hours_requested}h "
                    f"supplémentaires pour {subject.title} ({class_group})."
                ),
                priority='HIGH',
                link=f"/attendance/extra-request/{req.pk}/review/",
            )
            messages.success(request, "Votre demande a été envoyée à l'administrateur du département.")
            return redirect('attendance:my_extra_requests')

    ctx = {
        'subjects':    subjects,
        'classes':     classes,
        'years':       years,
        'sel_subject': subject_pk,
        'sel_class':   class_pk,
        'sel_year':    year_pk,
    }
    return render(request, 'attendance/extra_request_form.html', ctx)


@login_required
def my_extra_requests(request):
    """Liste des demandes de l'enseignant connecté."""
    from academic_core.apps.academic_structure.models import AcademicYear

    teacher = _get_teacher_profile(request.user)
    if not teacher:
        messages.error(request, "Accès réservé aux enseignants.")
        return redirect('dashboard:index')
    requests_qs = ExtraSessionRequest.objects.filter(teacher=teacher).select_related(
        'subject', 'class_group', 'academic_year', 'reviewed_by'
    )
    current_year = AcademicYear.objects.filter(is_current=True).first()
    if current_year:
        requests_qs = requests_qs.filter(academic_year=current_year)
    return render(request, 'attendance/my_extra_requests.html', {'extra_requests': requests_qs})


@login_required
def extra_request_review(request, pk):
    """L'admin du département approuve ou rejette une demande."""
    if not request.user.can_manage_dept():
        messages.error(request, "Accès refusé.")
        return redirect('attendance:extra_requests_admin')

    req = get_object_or_404(ExtraSessionRequest, pk=pk)
    if req.status != ExtraSessionRequest.STATUS_PENDING:
        messages.warning(request, "Cette demande a déjà été traitée.")
        return redirect('attendance:extra_requests_admin')

    if request.method == 'POST':
        action = request.POST.get('action')
        admin_note = request.POST.get('admin_note', '').strip()
        req.reviewed_by = request.user
        req.admin_note = admin_note
        req.reviewed_at = timezone.now()

        if action == 'approve':
            from decimal import Decimal as D
            approved_hours = request.POST.get('extra_hours_approved', '').strip()
            if not approved_hours:
                messages.error(request, "Indiquez le nombre d'heures approuvées.")
                return render(request, 'attendance/extra_request_review.html', {'req': req})
            req.extra_hours_approved = D(approved_hours)
            req.status = ExtraSessionRequest.STATUS_APPROVED

            # Mettre à jour SubjectProgress
            progress, _ = SubjectProgress.objects.get_or_create(
                subject=req.subject,
                class_group=req.class_group,
                academic_year=req.academic_year,
                defaults={'teacher': req.teacher},
            )
            progress.extra_hours += D(approved_hours)
            # Réinitialiser les flags de notification si retour sous les seuils
            if progress.percent_done < 60:
                progress.notified_60 = False
                progress.notified_90 = False
            elif progress.percent_done < 90:
                progress.notified_90 = False
            progress.save()

            notify_users(
                recipients=[req.teacher.user],
                notification_type='EXTRA_APPROVED',
                title=f"Demande approuvée — {req.subject.title}",
                message=(
                    f"Votre demande de séances supplémentaires pour {req.subject.title} "
                    f"({req.class_group}) a été approuvée : {approved_hours}h accordées."
                    + (f"\nNote : {admin_note}" if admin_note else ""),
                ),
                priority='HIGH',
            )
            req.save()
            messages.success(request, f"Demande approuvée — {approved_hours}h accordées.")

        elif action == 'reject':
            req.status = ExtraSessionRequest.STATUS_REJECTED
            req.save()
            notify_users(
                recipients=[req.teacher.user],
                notification_type='EXTRA_REJECTED',
                title=f"Demande rejetée — {req.subject.title}",
                message=(
                    f"Votre demande de séances supplémentaires pour {req.subject.title} "
                    f"({req.class_group}) a été rejetée."
                    + (f"\nMotif : {admin_note}" if admin_note else "")
                ),
                priority='MEDIUM',
            )
            messages.warning(request, "Demande rejetée.")

        return redirect('attendance:extra_requests_admin')

    return render(request, 'attendance/extra_request_review.html', {'req': req})


@login_required
def extra_requests_admin(request):
    """Liste de toutes les demandes pour l'admin du département."""
    if not request.user.can_manage_dept():
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')
    dept    = getattr(request, 'active_department', None)
    faculty = getattr(request, 'active_faculty', None)
    qs = ExtraSessionRequest.objects.select_related(
        'subject__semester', 'class_group', 'academic_year', 'teacher__user', 'reviewed_by'
    )
    if dept:
        qs = qs.filter(class_group__program__department=dept)
    elif faculty:
        qs = qs.filter(class_group__program__department__faculty=faculty)
    else:
        qs = qs.none()

    # Année académique : par défaut l'année en cours — "Toutes les années"
    # reste disponible pour consulter l'historique.
    fac_for_years = faculty or (dept.faculty if dept else None)
    from academic_core.apps.academic_structure.models import AcademicYear, Class, Semester
    from academic_core.apps.subjects.models import Subject
    academic_years = AcademicYear.objects.order_by('-start_date')
    academic_years = academic_years.filter(faculty=fac_for_years) if fac_for_years else academic_years.none()
    year_param = request.GET.get('year')
    if year_param == 'all':
        selected_year = None
    elif year_param:
        selected_year = academic_years.filter(pk=year_param).first()
    else:
        selected_year = academic_years.filter(is_current=True).first()
    if selected_year:
        qs = qs.filter(academic_year=selected_year)

    classes_qs = Class.objects.select_related('program').order_by('name')
    semesters_qs = Semester.objects.select_related('academic_year').order_by(
        '-academic_year__start_date', 'number'
    )
    subjects_qs = Subject.objects.order_by('code')
    if dept:
        classes_qs = classes_qs.filter(program__department=dept)
        semesters_qs = semesters_qs.filter(academic_year__faculty=dept.faculty)
        subjects_qs = subjects_qs.filter(program__department=dept)
    elif faculty:
        classes_qs = classes_qs.filter(program__department__faculty=faculty)
        semesters_qs = semesters_qs.filter(academic_year__faculty=faculty)
        subjects_qs = subjects_qs.filter(program__department__faculty=faculty)
    if selected_year:
        classes_qs = classes_qs.filter(academic_year=selected_year)
        semesters_qs = semesters_qs.filter(academic_year=selected_year)
        subjects_qs = subjects_qs.filter(semester__academic_year=selected_year)

    class_id    = request.GET.get('class_id')
    semester_id = request.GET.get('semester_id')
    subject_id  = request.GET.get('subject_id')
    if class_id:
        qs = qs.filter(class_group_id=class_id)
    if semester_id:
        qs = qs.filter(subject__semester_id=semester_id)
    if subject_id:
        qs = qs.filter(subject_id=subject_id)

    return render(request, 'attendance/extra_requests_admin.html', {
        'extra_requests': qs,
        'academic_years': academic_years,
        'selected_year_param': year_param or '',
        'filter_classes':   classes_qs,
        'filter_semesters': semesters_qs,
        'filter_subjects':  subjects_qs.distinct(),
        'selected_class_id':    class_id or '',
        'selected_semester_id': semester_id or '',
        'selected_subject_id':  subject_id or '',
    })


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
# Utilitaire : URL accessible depuis le réseau local (pour QR codes)
# ─────────────────────────────────────────────────────────────────────────────

def _get_accessible_base_url(request):
    """
    Retourne une URL de base accessible depuis le réseau local.
    Si l'hôte de la requête est 127.0.0.1 ou localhost, remplace par
    l'adresse IP LAN réelle de la machine afin que les QR codes
    scannés depuis un téléphone fonctionnent.
    """
    import socket
    host = request.get_host()  # ex: "127.0.0.1:8080" ou "192.168.1.10:8080"
    hostname = host.split(':')[0]
    port     = host.split(':')[1] if ':' in host else None

    if hostname in ('127.0.0.1', 'localhost', '0.0.0.0', '::1'):
        # Récupérer l'IP LAN réelle
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            lan_ip = s.getsockname()[0]
            s.close()
        except Exception:
            lan_ip = hostname  # fallback

        host = f"{lan_ip}:{port}" if port else lan_ip

    scheme = 'https' if request.is_secure() else 'http'
    return f"{scheme}://{host}"


# QR code de séance — affichage (plein écran, pour enseignant/admin/assistante)
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def session_qr_display(request, pk):
    """
    Affiche le QR code de la séance en plein écran.
    Accessible uniquement par l'enseignant de la séance, l'admin du département
    ou l'assistante du département.
    """
    sheet = get_object_or_404(
        AttendanceSheet.objects.select_related(
            'timetable_entry__teacher__user',
            'timetable_entry__subject',
            'timetable_entry__class_group',
        ),
        pk=pk,
    )
    teacher_profile = _get_teacher_profile(request.user)
    is_own_teacher  = teacher_profile and sheet.timetable_entry.teacher == teacher_profile
    is_admin        = request.user.can_manage_dept()

    if not (is_own_teacher or is_admin):
        messages.error(request, "Accès refusé.")
        return redirect('attendance:sheet_detail', pk=pk)

    from academic_core.apps.students.qr_utils import qr_image_to_base64, session_qr_payload
    base_url = _get_accessible_base_url(request)
    payload  = session_qr_payload(sheet, base_url)
    qr_b64   = qr_image_to_base64(payload, size_px=400)

    return render(request, 'attendance/session_qr_display.html', {
        'sheet':       sheet,
        'qr_b64':      qr_b64,
        'checkin_url': payload,
        'base_url':    base_url,
    })


# ─────────────────────────────────────────────────────────────────────────────
# QR code de séance — téléchargement PDF
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def session_qr_pdf(request, pk):
    """Génère un PDF A4 propre avec le QR code de la séance."""
    import io
    from django.http import HttpResponse
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from academic_core.apps.students.qr_utils import _make_qr_image, session_qr_payload
    from academic_core.apps.academic_structure.models import Institut
    from academic_core.pdf_utils import logo_image, watermark_canvas

    sheet = get_object_or_404(
        AttendanceSheet.objects.select_related(
            'timetable_entry__teacher__user',
            'timetable_entry__subject',
            'timetable_entry__class_group__program__department',
            'timetable_entry__semester',
        ),
        pk=pk,
    )
    teacher_profile = _get_teacher_profile(request.user)
    is_own_teacher  = teacher_profile and sheet.timetable_entry.teacher == teacher_profile
    is_admin        = request.user.can_manage_dept()
    if not (is_own_teacher or is_admin):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden()

    entry    = sheet.timetable_entry
    subject  = entry.subject
    class_gr = entry.class_group
    teacher  = entry.teacher.user

    # ── Générer l'image QR ────────────────────────────────────────────────────
    base_url   = _get_accessible_base_url(request)
    payload    = session_qr_payload(sheet, base_url)
    qr_pil     = _make_qr_image(payload, size_px=600)
    qr_buf     = io.BytesIO()
    qr_pil.save(qr_buf, format='PNG')
    qr_buf.seek(0)

    # ── Construire le PDF ─────────────────────────────────────────────────────
    pdf_buf = io.BytesIO()
    doc = SimpleDocTemplate(
        pdf_buf, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm, topMargin=1.8*cm, bottomMargin=1.5*cm,
    )
    W, H = A4
    usable = W - 4*cm

    styles = getSampleStyleSheet()
    navy   = colors.HexColor('#1e3a5f')
    purple = colors.HexColor('#7c3aed')
    green  = colors.HexColor('#16a34a')
    grey   = colors.HexColor('#64748b')

    s_title = ParagraphStyle('T', fontSize=16, textColor=navy,
                              alignment=TA_CENTER, fontName='Helvetica-Bold', leading=20)
    s_sub   = ParagraphStyle('S', fontSize=10, textColor=grey,
                              alignment=TA_CENTER, fontName='Helvetica', leading=14)
    s_label = ParagraphStyle('L', fontSize=9,  textColor=grey,
                              fontName='Helvetica', alignment=TA_CENTER)
    s_val   = ParagraphStyle('V', fontSize=11, textColor=navy,
                              fontName='Helvetica-Bold', alignment=TA_CENTER)
    s_url   = ParagraphStyle('U', fontSize=7.5, textColor=grey,
                              fontName='Helvetica', alignment=TA_CENTER, wordWrap='LTR')
    s_note  = ParagraphStyle('N', fontSize=8.5, textColor=colors.HexColor('#92400e'),
                              fontName='Helvetica', alignment=TA_CENTER, leading=13)

    day_fr  = {0:'Lundi',1:'Mardi',2:'Mercredi',3:'Jeudi',4:'Vendredi',5:'Samedi',6:'Dimanche'}
    weekday = day_fr.get(sheet.session_date.weekday(), '')
    date_str = f"{weekday} {sheet.session_date.strftime('%d/%m/%Y')}"
    time_str = f"{entry.start_time.strftime('%H:%M')} – {entry.end_time.strftime('%H:%M')}"

    story = []

    # Logo
    try:
        logo = logo_image(height_cm=1.8)
        story.append(logo)
        story.append(Spacer(1, 0.4*cm))
    except Exception:
        pass

    # Titre
    story.append(Paragraph("QR Code de Pointage", s_title))
    story.append(Spacer(1, 0.15*cm))
    story.append(Paragraph("Scannez ce code pour enregistrer votre présence", s_sub))
    story.append(Spacer(1, 0.5*cm))

    # Fiche info en tableau
    info_data = [
        [Paragraph('<font color="#64748b" size="8">MODULE</font>', s_label),
         Paragraph('<font color="#64748b" size="8">CLASSE</font>', s_label),
         Paragraph('<font color="#64748b" size="8">ENSEIGNANT</font>', s_label)],
        [Paragraph(f'<b>{subject.title}</b>', s_val),
         Paragraph(f'<b>{class_gr.name}</b>', s_val),
         Paragraph(f'<b>{teacher.get_full_name()}</b>', s_val)],
    ]
    info_table = Table(info_data, colWidths=[usable/3]*3)
    info_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8fafc')),
        ('ROWBACKGROUNDS', (0,0), (-1,-1), [colors.HexColor('#f0f4ff'), colors.HexColor('#f8fafc')]),
        ('BOX',    (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
        ('GRID',   (0,0), (-1,-1), 0.3, colors.HexColor('#e2e8f0')),
        ('TOPPADDING',    (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('ALIGN',  (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 0.3*cm))

    # Date / horaire
    date_data = [
        [Paragraph('<font color="#64748b" size="8">DATE</font>', s_label),
         Paragraph('<font color="#64748b" size="8">HORAIRE</font>', s_label)],
        [Paragraph(f'<b>{date_str}</b>', s_val),
         Paragraph(f'<b>{time_str}</b>', s_val)],
    ]
    date_table = Table(date_data, colWidths=[usable*0.55, usable*0.45])
    date_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f0f4ff')),
        ('BOX',   (0,0), (-1,-1), 0.5, colors.HexColor('#c7d2fe')),
        ('GRID',  (0,0), (-1,-1), 0.3, colors.HexColor('#e0e7ff')),
        ('TOPPADDING',    (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('ALIGN',  (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    story.append(date_table)
    story.append(Spacer(1, 0.6*cm))

    # QR Code centré, grande taille
    qr_rl = RLImage(qr_buf, width=10*cm, height=10*cm)
    qr_table = Table([[qr_rl]], colWidths=[usable])
    qr_table.setStyle(TableStyle([
        ('ALIGN',  (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOX',    (0,0), (-1,-1), 1, colors.HexColor('#e2e8f0')),
        ('BACKGROUND', (0,0), (-1,-1), colors.white),
        ('TOPPADDING',    (0,0), (-1,-1), 12),
        ('BOTTOMPADDING', (0,0), (-1,-1), 12),
    ]))
    story.append(qr_table)
    story.append(Spacer(1, 0.4*cm))

    # URL en clair (fallback)
    story.append(Paragraph(payload, s_url))
    story.append(Spacer(1, 0.4*cm))

    # Note d'instruction
    story.append(Paragraph(
        "⚠ Ce QR code est valable uniquement pour cette séance. "
        "Chaque étudiant doit scanner avec son propre compte.",
        s_note
    ))

    doc.build(story, onFirstPage=watermark_canvas, onLaterPages=watermark_canvas)
    pdf_buf.seek(0)

    safe_name = f"QR_{class_gr.name}_{subject.code}_{sheet.session_date.strftime('%Y%m%d')}".replace(' ', '_')
    response = HttpResponse(pdf_buf.read(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{safe_name}.pdf"'
    return response


# ─────────────────────────────────────────────────────────────────────────────
# Auto-pointage étudiant via QR code de séance
# ─────────────────────────────────────────────────────────────────────────────

def _find_sheet_by_token(token):
    """
    Cherche un AttendanceSheet par token dans toutes les bases SQLite connues.
    Pointe le thread-local vers la bonne base si trouvé hors de la base courante.
    Retourne l'objet ou None.
    """
    from django.conf import settings
    from academic_core.db_router import set_current_db, get_current_db

    # 1. Essai dans la base courante (rapide)
    try:
        return AttendanceSheet.objects.get(session_qr_token=token)
    except AttendanceSheet.DoesNotExist:
        pass

    # 2. Parcourir toutes les autres bases enregistrées
    current = get_current_db()
    for alias in settings.DATABASES:
        if alias == current:
            continue
        try:
            sheet = AttendanceSheet.objects.using(alias).get(session_qr_token=token)
            # Pointer le thread-local sur cette base pour toute la suite de la vue
            set_current_db(alias)
            return sheet
        except AttendanceSheet.DoesNotExist:
            continue

    return None


def _auto_mark_absents(sheet, entry):
    """
    Marque automatiquement absents tous les étudiants inscrits dans la classe
    qui n'ont pas encore pointé via QR pour cette feuille.
    Le statut d'absence tient compte du genre (ABSENT / ABSENTE).
    """
    enrolled = (
        Student.objects
        .filter(
            enrollments__class_group=entry.class_group,
            enrollments__academic_year=entry.semester.academic_year,
            enrollments__status=Enrollment.STATUS_VALIDATED,
        )
        .select_related('user')
        .distinct()
    )
    already_marked = set(
        StudentAttendance.objects.filter(attendance_sheet=sheet)
        .values_list('student_id', flat=True)
    )
    to_create = []
    for student in enrolled:
        if student.pk not in already_marked:
            # Détecter le genre pour le commentaire
            genre = getattr(student, 'gender', None) or getattr(student.user, 'gender', None)
            if genre and str(genre).upper() in ('F', 'FEMALE', 'FEMININ', 'FÉMININ'):
                comment = "Absente (non-pointage QR)"
            else:
                comment = "Absent (non-pointage QR)"
            to_create.append(StudentAttendance(
                attendance_sheet=sheet,
                student=student,
                status=StudentAttendance.STATUS_ABSENT,
                comment=comment,
            ))
    if to_create:
        StudentAttendance.objects.bulk_create(to_create, ignore_conflicts=True)


def student_checkin(request, token):
    """
    Pointage de présence par QR code — sans connexion requise.
    L'étudiant saisit son matricule, le système vérifie son inscription
    et enregistre sa présence directement.
    """
    sheet = _find_sheet_by_token(token)
    if sheet is None:
        from django.http import Http404
        raise Http404("QR code invalide ou expiré.")
    entry = sheet.timetable_entry

    # ── Validité du pointage ───────────────────────────────────────────────────
    window_error = None
    QR_WINDOW_MINUTES = 20  # fenêtre après signature de l'enseignant

    if sheet.status not in (AttendanceSheet.STATUS_PENDING, AttendanceSheet.STATUS_SIGNED):
        if sheet.status == AttendanceSheet.STATUS_VALIDATED:
            window_error = "Cette séance a été validée. Le pointage QR est clôturé."
        else:
            window_error = "Le pointage QR n'est pas disponible pour cette séance."

    elif sheet.status == AttendanceSheet.STATUS_SIGNED and sheet.teacher_signature_at:
        # Vérifier la fenêtre de 20 min après la signature
        from datetime import timedelta as _td
        deadline = sheet.teacher_signature_at + _td(minutes=QR_WINDOW_MINUTES)
        if timezone.now() > deadline:
            # Fenêtre expirée — auto-marquer absents les non-pointés
            _auto_mark_absents(sheet, entry)
            window_error = (
                f"La fenêtre de pointage de {QR_WINDOW_MINUTES} min est expirée. "
                f"Les étudiants non pointés ont été marqués absents."
            )

    error   = None
    success = False
    student = None
    already = False

    if request.method == 'POST' and not window_error:
        matricule = request.POST.get('matricule', '').strip().upper()
        if not matricule:
            error = "Veuillez saisir votre numéro de matricule."
        else:
            from academic_core.apps.students.models import Student
            try:
                student = Student.objects.get(matricule__iexact=matricule)
            except Student.DoesNotExist:
                error = f"Aucun étudiant trouvé avec le matricule « {matricule} »."
            else:
                # Vérifier inscription dans la classe (année de la séance,
                # pas is_active : un étudiant réinscrit ailleurs doit pouvoir
                # pointer sur une séance passée de cette classe)
                enrolled = Enrollment.objects.filter(
                    student=student,
                    class_group=entry.class_group,
                    academic_year=entry.semester.academic_year,
                    status=Enrollment.STATUS_VALIDATED,
                ).exists()
                if not enrolled:
                    error = f"{student.full_name} n'est pas inscrit(e) dans la classe {entry.class_group.name}."
                    student = None
                else:
                    att, created = StudentAttendance.objects.get_or_create(
                        attendance_sheet=sheet,
                        student=student,
                        defaults={
                            'status':       StudentAttendance.STATUS_PRESENT,
                            'self_checkin': True,
                        },
                    )
                    if not created:
                        already = True
                        if att.status != StudentAttendance.STATUS_PRESENT:
                            att.status       = StudentAttendance.STATUS_PRESENT
                            att.self_checkin = True
                            att.save()
                    success = True

    # Liste des étudiants inscrits dans la classe (pour affichage)
    enrolled_students = (
        Student.objects
        .filter(
            enrollments__class_group=entry.class_group,
            enrollments__academic_year=entry.semester.academic_year,
            enrollments__status=Enrollment.STATUS_VALIDATED,
        )
        .select_related('user')
        .order_by('user__last_name', 'user__first_name')
        .distinct()
    )
    # Présences déjà enregistrées
    checked_in_ids = set(
        StudentAttendance.objects
        .filter(attendance_sheet=sheet, status=StudentAttendance.STATUS_PRESENT)
        .values_list('student_id', flat=True)
    )

    return render(request, 'attendance/checkin_anonymous.html', {
        'sheet':             sheet,
        'entry':             entry,
        'window_error':      window_error,
        'error':             error,
        'success':           success,
        'student':           student,
        'already':           already,
        'token':             token,
        'enrolled_students': enrolled_students,
        'checked_in_ids':    checked_in_ids,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Pointage authentifié — l'étudiant scanne le QR de l'enseignant (connecté)
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def student_authenticated_checkin(request, token):
    """L'étudiant connecté scanne le QR de la séance depuis 'Ma carte Présence'.
    Son identité est déduite de la session — pas de saisie de matricule."""
    sheet = _find_sheet_by_token(token)
    if sheet is None:
        return JsonResponse({'ok': False, 'error': 'QR invalide ou expiré.'}, status=404)

    entry = sheet.timetable_entry

    # Vérifier que l'utilisateur est bien un étudiant
    try:
        from academic_core.apps.students.models import Student
        student = request.user.student_profile
    except Exception:
        return JsonResponse({'ok': False, 'error': 'Cette fonctionnalité est réservée aux étudiants.'}, status=403)

    # Fenêtre de pointage
    if sheet.status == AttendanceSheet.STATUS_VALIDATED:
        return JsonResponse({'ok': False, 'error': 'Cette séance est déjà validée.'})
    if sheet.status not in (AttendanceSheet.STATUS_PENDING, AttendanceSheet.STATUS_SIGNED):
        return JsonResponse({'ok': False, 'error': 'Le pointage n\'est pas ouvert pour cette séance.'})

    # Bloquer dès que la séance est terminée (session_date + end_time)
    from datetime import datetime as _dt
    session_end = timezone.make_aware(
        _dt.combine(sheet.session_date, entry.end_time)
    )
    if timezone.now() > session_end:
        _auto_mark_absents(sheet, entry)
        sheet.absent_auto_done = True
        sheet.save(update_fields=['absent_auto_done'])
        genre_student = None
        try:
            genre_student = getattr(request.user.student_profile, 'gender', None)
        except Exception:
            pass
        label_absent = 'Absente' if genre_student and str(genre_student).upper() in ('F', 'FEMALE', 'FEMININ', 'FÉMININ') else 'Absent'
        return JsonResponse({
            'ok': False,
            'error': f'La séance est terminée. Votre statut a été enregistré comme {label_absent}.',
        })

    # Fenêtre QR (20 min après signature enseignant)
    if sheet.status == AttendanceSheet.STATUS_SIGNED and sheet.teacher_signature_at:
        from datetime import timedelta as _td
        deadline = sheet.teacher_signature_at + _td(minutes=20)
        if timezone.now() > deadline:
            _auto_mark_absents(sheet, entry)
            return JsonResponse({'ok': False, 'error': 'La fenêtre de pointage de 20 min est expirée.'})

    # Vérifier inscription dans la classe (année de la séance, pas is_active)
    enrolled = Enrollment.objects.filter(
        student=student,
        class_group=entry.class_group,
        academic_year=entry.semester.academic_year,
        status=Enrollment.STATUS_VALIDATED,
    ).exists()
    if not enrolled:
        return JsonResponse({
            'ok': False,
            'error': f'Vous n\'êtes pas inscrit(e) dans la classe {entry.class_group.name}.',
        })

    att, created = StudentAttendance.objects.get_or_create(
        attendance_sheet=sheet,
        student=student,
        defaults={'status': StudentAttendance.STATUS_PRESENT, 'self_checkin': True},
    )
    if not created and att.status != StudentAttendance.STATUS_PRESENT:
        att.status = StudentAttendance.STATUS_PRESENT
        att.self_checkin = True
        att.save(update_fields=['status', 'self_checkin'])

    genre = getattr(student, 'gender', 'M') or 'M'
    label = 'Présente' if genre == 'F' else 'Présent'

    return JsonResponse({
        'ok': True,
        'already': not created,
        'label': label,
        'nom': student.user.get_full_name(),
        'subject': entry.subject.title,
        'class_group': entry.class_group.name,
        'date': sheet.session_date.strftime('%d/%m/%Y'),
    })


# ─────────────────────────────────────────────────────────────────────────────
# Scanner QR étudiant — validation présence par l'enseignant (conservé)
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def scan_student_checkin(request, pk):
    """Page de scan QR code étudiant pour l'enseignant.
    L'enseignant ouvre cette page sur son téléphone, scanne la carte présence
    de chaque étudiant pour valider leur présence à la séance."""
    sheet = get_object_or_404(
        AttendanceSheet.objects.select_related(
            'timetable_entry__teacher__user',
            'timetable_entry__subject',
            'timetable_entry__class_group',
        ),
        pk=pk,
    )
    teacher_profile = _get_teacher_profile(request.user)
    is_own_teacher  = teacher_profile and sheet.timetable_entry.teacher == teacher_profile
    is_admin        = request.user.can_manage_dept()

    if not (is_own_teacher or is_admin):
        messages.error(request, "Accès refusé.")
        return redirect('attendance:sheet_detail', pk=pk)

    if sheet.status == AttendanceSheet.STATUS_VALIDATED:
        messages.warning(request, "Cette séance est validée. Le pointage QR est clôturé.")
        return redirect('attendance:sheet_detail', pk=pk)

    # Liste des présences actuelles
    presences = (
        StudentAttendance.objects
        .filter(attendance_sheet=sheet, status=StudentAttendance.STATUS_PRESENT)
        .select_related('student__user')
        .order_by('student__user__last_name')
    )

    return render(request, 'attendance/scan_student_checkin.html', {
        'sheet':     sheet,
        'presences': presences,
    })


@login_required
def ajax_scan_validate(request, pk):
    """Endpoint AJAX appelé quand l'enseignant scanne le QR d'un étudiant.
    Reçoit le payload JSON du QR, valide la présence, retourne JSON."""
    import json as _json
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Méthode non autorisée'}, status=405)

    sheet = get_object_or_404(AttendanceSheet, pk=pk)
    teacher_profile = _get_teacher_profile(request.user)
    is_own_teacher  = teacher_profile and sheet.timetable_entry.teacher == teacher_profile
    is_admin        = request.user.can_manage_dept()

    if not (is_own_teacher or is_admin):
        return JsonResponse({'ok': False, 'error': 'Accès refusé'}, status=403)

    if sheet.status == AttendanceSheet.STATUS_VALIDATED:
        return JsonResponse({'ok': False, 'error': 'Séance déjà validée'}, status=400)

    # Lire le payload QR
    try:
        body    = _json.loads(request.body)
        raw_qr  = body.get('qr_data', '')
        payload = _json.loads(raw_qr)
        if payload.get('type') != 'presence':
            return JsonResponse({'ok': False, 'error': 'QR invalide — pas une carte présence'})
        matricule = payload.get('mat', '').strip().upper()
        genre     = payload.get('genre', 'M')
    except Exception:
        return JsonResponse({'ok': False, 'error': 'Données QR illisibles'}, status=400)

    if not matricule:
        return JsonResponse({'ok': False, 'error': 'Matricule manquant dans le QR'})

    from academic_core.apps.students.models import Student
    try:
        student = Student.objects.select_related('user').get(matricule__iexact=matricule)
    except Student.DoesNotExist:
        return JsonResponse({'ok': False, 'error': f'Étudiant introuvable : {matricule}'})

    # Vérifier inscription dans la classe de la séance (année de la séance,
    # pas is_active)
    enrolled = Enrollment.objects.filter(
        student=student,
        class_group=sheet.timetable_entry.class_group,
        academic_year=sheet.timetable_entry.semester.academic_year,
        status=Enrollment.STATUS_VALIDATED,
    ).exists()
    if not enrolled:
        return JsonResponse({
            'ok': False,
            'error': f'{student.user.get_full_name()} n\'est pas inscrit(e) dans la classe {sheet.timetable_entry.class_group.name}',
        })

    att, created = StudentAttendance.objects.get_or_create(
        attendance_sheet=sheet,
        student=student,
        defaults={'status': StudentAttendance.STATUS_PRESENT, 'self_checkin': False},
    )
    if not created:
        if att.status != StudentAttendance.STATUS_PRESENT:
            att.status = StudentAttendance.STATUS_PRESENT
            att.save(update_fields=['status'])

    label_presence = 'Présente' if genre == 'F' else 'Présent'
    total_present = StudentAttendance.objects.filter(
        attendance_sheet=sheet, status=StudentAttendance.STATUS_PRESENT
    ).count()

    return JsonResponse({
        'ok': True,
        'already': not created and att.status == StudentAttendance.STATUS_PRESENT,
        'nom': student.user.get_full_name(),
        'matricule': student.matricule,
        'label': label_presence,
        'total_present': total_present,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Liste des absences d'une classe pour une séance — admin/enseignant/assistante
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def session_absence_list(request, pk):
    """
    Affiche la liste des absences pour une séance donnée.
    - Admins / Enseignant de la séance / Assistante : voient toute la classe.
    - Étudiant : voit uniquement ses propres absences (redirige vers my_absences).
    """
    sheet = get_object_or_404(
        AttendanceSheet.objects.select_related(
            'timetable_entry__subject',
            'timetable_entry__class_group',
            'timetable_entry__teacher__user',
        ),
        pk=pk,
    )

    teacher_profile = _get_teacher_profile(request.user)
    is_own_teacher  = teacher_profile and sheet.timetable_entry.teacher == teacher_profile
    is_admin        = request.user.can_manage_dept()

    if not (is_own_teacher or is_admin):
        if request.user.is_etudiant():
            return redirect('attendance:my_absences')
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    entry = sheet.timetable_entry
    enrolled = (
        Student.objects
        .filter(
            enrollments__class_group=entry.class_group,
            enrollments__academic_year=entry.semester.academic_year,
            enrollments__status=Enrollment.STATUS_VALIDATED,
        )
        .select_related('user')
        .order_by('user__last_name', 'user__first_name')
        .distinct()
    )
    att_map = {
        a.student_id: a
        for a in StudentAttendance.objects
            .filter(attendance_sheet=sheet)
            .select_related('student')
    }
    students_data = [(s, att_map.get(s.pk)) for s in enrolled]
    present_count = sum(1 for _, a in students_data if a and a.status == StudentAttendance.STATUS_PRESENT)
    absent_count  = sum(1 for _, a in students_data if a and a.status == StudentAttendance.STATUS_ABSENT)

    return render(request, 'attendance/session_absence_list.html', {
        'sheet':         sheet,
        'students_data': students_data,
        'present_count': present_count,
        'absent_count':  absent_count,
    })


# ── Admin département : modules planifiés (tous les enseignants) ───────────────

@login_required
def planned_modules_admin(request):
    """Admin/responsable : vue globale de l'avancement de tous les modules planifiés."""
    if not request.user.can_manage_dept():
        messages.error(request, "Accès réservé aux administrateurs de département.")
        return redirect('dashboard:index')

    from academic_core.apps.academic_structure.models import AcademicYear, Semester
    from collections import defaultdict
    from .models import CoursePlan

    dept   = getattr(request, 'active_department', None)
    faculty = getattr(request, 'active_faculty', None)

    # Filtres GET
    semester_id = request.GET.get('semester')
    search_q    = request.GET.get('q', '').strip()

    # Année académique : par défaut l'année en cours, "Toutes les années"
    # reste sélectionnable explicitement pour consulter l'historique.
    fac_for_years = faculty or (dept.faculty if dept else None)
    academic_years = AcademicYear.objects.order_by('-start_date')
    academic_years = academic_years.filter(faculty=fac_for_years) if fac_for_years else academic_years.none()
    year_param = request.GET.get('year')
    if year_param == 'all':
        selected_year = None
    elif year_param:
        selected_year = academic_years.filter(pk=year_param).first()
    else:
        selected_year = academic_years.filter(is_current=True).first()

    # Semestres disponibles pour le filtre
    semesters = Semester.objects.select_related('academic_year').order_by(
        '-academic_year__start_date', 'number')
    if faculty:
        semesters = semesters.filter(academic_year__faculty=faculty)
    if selected_year:
        semesters = semesters.filter(academic_year=selected_year)

    # Entrées de planning du département
    entries_qs = TimetableEntry.objects.filter(is_active=True).select_related(
        'subject', 'class_group__program__department', 'semester__academic_year',
        'teacher__user',
    )
    if dept:
        entries_qs = entries_qs.filter(class_group__program__department=dept)
    elif faculty:
        entries_qs = entries_qs.filter(class_group__program__department__faculty=faculty)
    if selected_year:
        entries_qs = entries_qs.filter(semester__academic_year=selected_year)
    if semester_id:
        entries_qs = entries_qs.filter(semester_id=semester_id)
    if search_q:
        entries_qs = entries_qs.filter(
            teacher__user__first_name__icontains=search_q
        ) | entries_qs.filter(
            teacher__user__last_name__icontains=search_q
        ) | entries_qs.filter(
            subject__title__icontains=search_q
        )

    # Plans de cours déjà définis (avec au moins une séance), pour afficher un
    # lien « Plan de cours » utilisable par les administrateurs/chef de
    # département/assistante (voir course_plan_view) sur chaque module.
    plans_qs = CoursePlan.objects.filter(sessions__isnull=False)
    if dept:
        plans_qs = plans_qs.filter(class_group__program__department=dept)
    elif faculty:
        plans_qs = plans_qs.filter(class_group__program__department__faculty=faculty)
    plans_with_sessions = set(
        plans_qs.values_list('teacher_id', 'subject_id', 'class_group_id', 'academic_year_id').distinct()
    )

    # Dédupliquer par (teacher, subject, class_group, semester)
    seen = set()
    teacher_map = {}  # teacher -> [modules]

    for entry in entries_qs.order_by(
        'teacher__user__last_name', 'teacher__user__first_name',
        'subject__title', 'class_group__name'
    ):
        key = (entry.teacher_id, entry.subject_id, entry.class_group_id, entry.semester_id)
        if key in seen:
            continue
        seen.add(key)

        acad_year = entry.semester.academic_year if entry.semester else None
        try:
            progress = SubjectProgress.objects.get(
                subject=entry.subject,
                class_group=entry.class_group,
                academic_year=acad_year,
            ) if acad_year else None
        except SubjectProgress.DoesNotExist:
            progress = None

        hours_done   = float(progress.hours_done)  if progress else 0
        extra_hours  = float(progress.extra_hours) if progress else 0
        volume_total = float(progress.volume_total) if progress else float(entry.subject.volume_hours or 0)
        percent      = float(progress.percent_done) if progress else 0
        vol_restant  = max(volume_total - hours_done, 0)
        is_complete  = vol_restant <= 0 and volume_total > 0

        module = {
            'subject':       entry.subject,
            'class_group':   entry.class_group,
            'semester':      entry.semester,
            'extra_hours':   extra_hours,
            'volume_total':  volume_total,
            'hours_done':    hours_done,
            'vol_restant':   vol_restant,
            'percent':       percent,
            'is_complete':   is_complete,
            'entry':         entry,
            'has_course_plan': (entry.teacher_id, entry.subject_id, entry.class_group_id, acad_year.pk if acad_year else None) in plans_with_sessions,
        }

        teacher = entry.teacher
        if teacher not in teacher_map:
            teacher_map[teacher] = []
        teacher_map[teacher].append(module)

    # Construire la liste triée
    teachers_data = []
    for teacher, mods in teacher_map.items():
        total_vol   = sum(m['volume_total'] for m in mods)
        total_done  = sum(m['hours_done']   for m in mods)
        total_rest  = sum(m['vol_restant']  for m in mods)
        global_pct  = round(total_done / total_vol * 100) if total_vol else 0
        nb_complete = sum(1 for m in mods if m['is_complete'])
        teachers_data.append({
            'teacher':     teacher,
            'modules':     mods,
            'total_vol':   total_vol,
            'total_done':  total_done,
            'total_rest':  total_rest,
            'global_pct':  global_pct,
            'nb_modules':  len(mods),
            'nb_complete': nb_complete,
        })

    # Stats globales
    grand_modules  = sum(t['nb_modules']  for t in teachers_data)
    grand_complete = sum(t['nb_complete'] for t in teachers_data)

    return render(request, 'attendance/planned_modules.html', {
        'teachers_data':  teachers_data,
        'semesters':      semesters,
        'semester_id':    semester_id,
        'academic_years': academic_years,
        'selected_year_param': year_param or '',
        'search_q':       search_q,
        'grand_modules':  grand_modules,
        'grand_complete': grand_complete,
    })


# ─── Export PDF feuille de présence ──────────────────────────────────────────

@login_required
def export_sheet_pdf(request, pk):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
    )
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from io import BytesIO
    import django.http
    from academic_core.pdf_utils import watermark_canvas

    sheet = get_object_or_404(AttendanceSheet, pk=pk)
    user  = request.user
    teacher_profile = _get_teacher_profile(user)
    if not (user.can_manage_dept() or
            (teacher_profile and sheet.timetable_entry.teacher == teacher_profile)):
        messages.error(request, "Accès refusé.")
        return redirect('attendance:sheet_detail', pk=pk)

    entry = sheet.timetable_entry
    attendances = sheet.student_attendances.select_related('student__user').order_by(
        'student__user__last_name', 'student__user__first_name'
    )

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2.5*cm, bottomMargin=2*cm,
        title="Feuille de présence",
    )

    styles = getSampleStyleSheet()
    navy   = colors.HexColor('#1e3a5f')
    light  = colors.HexColor('#eff6ff')
    red    = colors.HexColor('#dc2626')
    green  = colors.HexColor('#16a34a')
    orange = colors.HexColor('#d97706')
    grey   = colors.HexColor('#64748b')
    white  = colors.white

    title_style = ParagraphStyle('t', parent=styles['Normal'],
        fontSize=16, fontName='Helvetica-Bold', textColor=navy, spaceAfter=4)
    sub_style   = ParagraphStyle('s', parent=styles['Normal'],
        fontSize=9, textColor=grey, spaceAfter=2)
    label_style = ParagraphStyle('l', parent=styles['Normal'],
        fontSize=8.5, fontName='Helvetica-Bold', textColor=grey)
    value_style = ParagraphStyle('v', parent=styles['Normal'],
        fontSize=9, fontName='Helvetica-Bold', textColor=navy)

    STATUS_LABELS = {
        'PRESENT':   ('Présent·e', green),
        'ABSENT':    ('Absent·e',  red),
        'LATE':      ('Retard',    orange),
        'JUSTIFIED': ('Justifié·e', colors.HexColor('#7c3aed')),
    }

    elems = []

    # En-tête
    elems.append(Paragraph("FEUILLE DE PRÉSENCE", title_style))
    dept = entry.class_group.program.department
    elems.append(Paragraph(str(dept), sub_style))
    elems.append(HRFlowable(width='100%', thickness=2, color=navy, spaceAfter=10))

    # Tableau info séance
    status_map = {
        AttendanceSheet.STATUS_PENDING:   'En attente',
        AttendanceSheet.STATUS_SIGNED:    'Signé',
        AttendanceSheet.STATUS_VALIDATED: 'Validé',
        AttendanceSheet.STATUS_REJECTED:  'Rejeté',
    }
    info_data = [
        ['Module (EC)', entry.subject.title,        'Date',     sheet.session_date.strftime('%d/%m/%Y')],
        ['Enseignant', entry.teacher.user.get_full_name(), 'Créneau', f"{entry.start_time.strftime('%H:%M')} – {entry.end_time.strftime('%H:%M')}"],
        ['Classe',     entry.class_group.name,       'Durée',    f"{entry.duration_hours:.1f} h"],
        ['Salle',      entry.room.name if entry.room else '—', 'Statut', status_map.get(sheet.status, sheet.status)],
    ]
    info_table = Table(info_data, colWidths=[3*cm, 6.5*cm, 2.5*cm, 5*cm])
    info_table.setStyle(TableStyle([
        ('FONTNAME',    (0,0), (-1,-1), 'Helvetica'),
        ('FONTSIZE',    (0,0), (-1,-1), 8.5),
        ('FONTNAME',    (0,0), (0,-1), 'Helvetica-Bold'),
        ('FONTNAME',    (2,0), (2,-1), 'Helvetica-Bold'),
        ('TEXTCOLOR',   (0,0), (0,-1), grey),
        ('TEXTCOLOR',   (2,0), (2,-1), grey),
        ('TEXTCOLOR',   (1,0), (1,-1), navy),
        ('TEXTCOLOR',   (3,0), (3,-1), navy),
        ('BACKGROUND',  (0,0), (-1,-1), light),
        ('ROWBACKGROUNDS', (0,0), (-1,-1), [light, white]),
        ('GRID',        (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
        ('TOPPADDING',  (0,0), (-1,-1), 5),
        ('BOTTOMPADDING',(0,0),(-1,-1), 5),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING',(0,0), (-1,-1), 6),
    ]))
    elems.append(info_table)
    elems.append(Spacer(1, 0.5*cm))

    # Tableau présences
    header = ['#', 'Nom complet', 'Matricule', 'Présence', 'Commentaire']
    rows = [header]
    for i, att in enumerate(attendances, 1):
        label, _ = STATUS_LABELS.get(att.status, (att.status, grey))
        rows.append([
            str(i),
            att.student.user.get_full_name(),
            att.student.matricule,
            label,
            att.comment or '',
        ])

    if not attendances.exists():
        rows.append(['—', 'Aucun étudiant enregistré', '', '', ''])

    col_w = [1*cm, 5.5*cm, 3*cm, 3*cm, 4.5*cm]
    att_table = Table(rows, colWidths=col_w, repeatRows=1)
    ts = TableStyle([
        # En-tête
        ('BACKGROUND',   (0,0), (-1,0), navy),
        ('TEXTCOLOR',    (0,0), (-1,0), white),
        ('FONTNAME',     (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE',     (0,0), (-1,0), 9),
        ('ALIGN',        (0,0), (-1,0), 'CENTER'),
        # Corps
        ('FONTNAME',     (0,1), (-1,-1), 'Helvetica'),
        ('FONTSIZE',     (0,1), (-1,-1), 8.5),
        ('ALIGN',        (0,1), (0,-1), 'CENTER'),
        ('ROWBACKGROUNDS',(0,1),(-1,-1), [white, colors.HexColor('#f8fafc')]),
        ('GRID',         (0,0), (-1,-1), 0.4, colors.HexColor('#e2e8f0')),
        ('TOPPADDING',   (0,0), (-1,-1), 5),
        ('BOTTOMPADDING',(0,0),(-1,-1), 5),
        ('LEFTPADDING',  (0,0), (-1,-1), 5),
        ('RIGHTPADDING', (0,0), (-1,-1), 5),
    ])
    # Couleurs présence
    for i, att in enumerate(attendances, 1):
        _, col = STATUS_LABELS.get(att.status, (att.status, grey))
        ts.add('TEXTCOLOR', (3, i), (3, i), col)
        ts.add('FONTNAME',  (3, i), (3, i), 'Helvetica-Bold')
    att_table.setStyle(ts)
    elems.append(att_table)

    # Pied de page : résumé
    total = attendances.count()
    nb_present  = attendances.filter(status='PRESENT').count()
    nb_absent   = attendances.filter(status='ABSENT').count()
    nb_late     = attendances.filter(status='LATE').count()
    nb_just     = attendances.filter(status='JUSTIFIED').count()

    elems.append(Spacer(1, 0.4*cm))
    summary_data = [[
        f"Total : {total}",
        f"Présents : {nb_present}",
        f"Absents : {nb_absent}",
        f"Retards : {nb_late}",
        f"Justifiés : {nb_just}",
    ]]
    sum_table = Table(summary_data, colWidths=[3.4*cm]*5)
    sum_table.setStyle(TableStyle([
        ('BACKGROUND',  (0,0), (-1,-1), navy),
        ('TEXTCOLOR',   (0,0), (-1,-1), white),
        ('FONTNAME',    (0,0), (-1,-1), 'Helvetica-Bold'),
        ('FONTSIZE',    (0,0), (-1,-1), 8),
        ('ALIGN',       (0,0), (-1,-1), 'CENTER'),
        ('TOPPADDING',  (0,0), (-1,-1), 5),
        ('BOTTOMPADDING',(0,0),(-1,-1), 5),
    ]))
    elems.append(sum_table)

    # Zone de signature
    elems.append(Spacer(1, 1*cm))
    sig_data = [['Signature de l\'enseignant', 'Cachet du département']]
    sig_table = Table(sig_data, colWidths=[8.5*cm, 8.5*cm])
    sig_table.setStyle(TableStyle([
        ('FONTNAME',    (0,0), (-1,-1), 'Helvetica-Bold'),
        ('FONTSIZE',    (0,0), (-1,-1), 8.5),
        ('TEXTCOLOR',   (0,0), (-1,-1), grey),
        ('ALIGN',       (0,0), (-1,-1), 'CENTER'),
        ('BOX',         (0,0), (0,0), 0.5, grey),
        ('BOX',         (1,0), (1,0), 0.5, grey),
        ('TOPPADDING',  (0,0), (-1,-1), 30),
        ('BOTTOMPADDING',(0,0),(-1,-1), 6),
    ]))
    elems.append(sig_table)

    elems.append(Spacer(1, .4*cm))

    doc.build(elems, onFirstPage=watermark_canvas, onLaterPages=watermark_canvas)
    buf.seek(0)
    fname = f"presence_{entry.subject.code}_{entry.class_group.name}_{sheet.session_date}.pdf"
    resp = django.http.HttpResponse(buf, content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="{fname}"'
    return resp


# ─── Export Word feuille de présence ─────────────────────────────────────────

@login_required
def export_sheet_word(request, pk):
    from docx import Document
    from docx.shared import Pt, Cm, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.table import WD_ALIGN_VERTICAL
    from io import BytesIO
    import django.http
    from academic_core.pdf_utils import add_docx_watermark

    sheet = get_object_or_404(AttendanceSheet, pk=pk)
    user  = request.user
    teacher_profile = _get_teacher_profile(user)
    if not (user.can_manage_dept() or
            (teacher_profile and sheet.timetable_entry.teacher == teacher_profile)):
        messages.error(request, "Accès refusé.")
        return redirect('attendance:sheet_detail', pk=pk)

    entry = sheet.timetable_entry
    attendances = sheet.student_attendances.select_related('student__user').order_by(
        'student__user__last_name', 'student__user__first_name'
    )

    NAVY = RGBColor(0x1e, 0x3a, 0x5f)
    GREY = RGBColor(0x64, 0x74, 0x8b)
    WHITE = RGBColor(0xff, 0xff, 0xff)
    RED   = RGBColor(0xdc, 0x26, 0x26)
    GREEN = RGBColor(0x16, 0xa3, 0x4a)
    ORANGE= RGBColor(0xd9, 0x77, 0x06)
    PURPLE= RGBColor(0x7c, 0x3a, 0xed)

    STATUS_INFO = {
        'PRESENT':   ('Présent·e', GREEN),
        'ABSENT':    ('Absent·e',  RED),
        'LATE':      ('Retard',    ORANGE),
        'JUSTIFIED': ('Justifié·e',PURPLE),
    }

    doc = Document()

    # Marges
    for section in doc.sections:
        section.top_margin    = Cm(2)
        section.bottom_margin = Cm(2)
        section.left_margin   = Cm(2.5)
        section.right_margin  = Cm(2.5)

    # Titre
    t = doc.add_heading('FEUILLE DE PRÉSENCE', level=1)
    t.runs[0].font.color.rgb = NAVY
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER

    dept = entry.class_group.program.department
    sub = doc.add_paragraph(str(dept))
    sub.runs[0].font.color.rgb = GREY
    sub.runs[0].font.size = Pt(10)
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph()

    # Tableau infos séance (4 cols)
    status_map = {
        AttendanceSheet.STATUS_PENDING:   'En attente',
        AttendanceSheet.STATUS_SIGNED:    'Signé',
        AttendanceSheet.STATUS_VALIDATED: 'Validé',
        AttendanceSheet.STATUS_REJECTED:  'Rejeté',
    }
    info_rows = [
        ('Module (EC)', entry.subject.title,
         'Date',       sheet.session_date.strftime('%d/%m/%Y')),
        ('Enseignant', entry.teacher.user.get_full_name(),
         'Créneau',    f"{entry.start_time.strftime('%H:%M')} – {entry.end_time.strftime('%H:%M')}"),
        ('Classe',     entry.class_group.name,
         'Durée',      f"{entry.duration_hours:.1f} h"),
        ('Salle',      entry.room.name if entry.room else '—',
         'Statut',     status_map.get(sheet.status, sheet.status)),
    ]
    info_tbl = doc.add_table(rows=len(info_rows), cols=4)
    info_tbl.style = 'Table Grid'
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    def set_cell_bg(cell, hex_color):
        tc = cell._tc
        tcPr = tc.get_or_add_tcPr()
        shd = OxmlElement('w:shd')
        shd.set(qn('w:val'), 'clear')
        shd.set(qn('w:color'), 'auto')
        shd.set(qn('w:fill'), hex_color)
        tcPr.append(shd)

    for i, (l1, v1, l2, v2) in enumerate(info_rows):
        row = info_tbl.rows[i]
        for ci, (txt, bold, color) in enumerate([
            (l1, True, GREY), (v1, False, NAVY),
            (l2, True, GREY), (v2, False, NAVY),
        ]):
            cell = row.cells[ci]
            cell.text = txt
            run = cell.paragraphs[0].runs[0]
            run.bold = bold
            run.font.size = Pt(9)
            run.font.color.rgb = color
            bg = 'eff6ff' if i % 2 == 0 else 'ffffff'
            set_cell_bg(cell, bg)

    doc.add_paragraph()

    # Titre section présences
    ph = doc.add_heading('Liste des présences', level=2)
    ph.runs[0].font.color.rgb = NAVY

    # Tableau présences
    att_cols = ['#', 'Nom complet', 'Matricule', 'Présence', 'Commentaire']
    att_list = list(attendances)
    att_tbl = doc.add_table(rows=1 + len(att_list) or 2, cols=5)
    att_tbl.style = 'Table Grid'

    # En-tête
    hdr = att_tbl.rows[0].cells
    for ci, txt in enumerate(att_cols):
        hdr[ci].text = txt
        run = hdr[ci].paragraphs[0].runs[0]
        run.bold = True
        run.font.size = Pt(9)
        run.font.color.rgb = WHITE
        set_cell_bg(hdr[ci], '1e3a5f')

    for i, att in enumerate(att_list, 1):
        row = att_tbl.rows[i].cells
        label, color = STATUS_INFO.get(att.status, (att.status, GREY))
        for ci, (txt, col, bold) in enumerate([
            (str(i),                           GREY,  False),
            (att.student.user.get_full_name(), NAVY,  True),
            (att.student.matricule,            GREY,  False),
            (label,                            color, True),
            (att.comment or '',                GREY,  False),
        ]):
            row[ci].text = txt
            run = row[ci].paragraphs[0].runs[0]
            run.bold  = bold
            run.font.size = Pt(9)
            run.font.color.rgb = col
            set_cell_bg(row[ci], 'f8fafc' if i % 2 == 0 else 'ffffff')

    if not att_list:
        row = att_tbl.rows[1].cells
        row[0].merge(row[4])
        row[0].text = 'Aucun étudiant enregistré'
        row[0].paragraphs[0].runs[0].font.color.rgb = GREY

    doc.add_paragraph()

    # Résumé
    total      = len(att_list)
    nb_present = sum(1 for a in att_list if a.status == 'PRESENT')
    nb_absent  = sum(1 for a in att_list if a.status == 'ABSENT')
    nb_late    = sum(1 for a in att_list if a.status == 'LATE')
    nb_just    = sum(1 for a in att_list if a.status == 'JUSTIFIED')

    sum_tbl = doc.add_table(rows=1, cols=5)
    sum_tbl.style = 'Table Grid'
    for ci, txt in enumerate([
        f"Total : {total}", f"Présents : {nb_present}",
        f"Absents : {nb_absent}", f"Retards : {nb_late}",
        f"Justifiés : {nb_just}",
    ]):
        c = sum_tbl.rows[0].cells[ci]
        c.text = txt
        run = c.paragraphs[0].runs[0]
        run.bold = True
        run.font.size = Pt(8.5)
        run.font.color.rgb = WHITE
        set_cell_bg(c, '1e3a5f')

    doc.add_paragraph()

    # Signature
    sig_tbl = doc.add_table(rows=3, cols=2)
    sig_tbl.style = 'Table Grid'
    for ci, txt in enumerate(['Signature de l\'enseignant', 'Cachet du département']):
        c = sig_tbl.rows[0].cells[ci]
        c.text = txt
        run = c.paragraphs[0].runs[0]
        run.bold = True
        run.font.size = Pt(8.5)
        run.font.color.rgb = GREY
    for r in [1, 2]:
        for ci in range(2):
            sig_tbl.rows[r].cells[ci].text = ''

    add_docx_watermark(doc)
    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)

    fname = f"presence_{entry.subject.code}_{entry.class_group.name}_{sheet.session_date}.docx"
    resp = django.http.HttpResponse(
        buf,
        content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    )
    resp['Content-Disposition'] = f'attachment; filename="{fname}"'
    return resp


@login_required
def absence_alert_config_view(request):
    """
    Permet au chef de département (RESPONSABLE/ASSISTANTE, ou admin) de
    consulter/modifier le seuil d'absences (AbsenceAlertConfig.seuil_absences)
    de son département — seuil utilisé par la tâche périodique quotidienne
    check_student_absence_alerts_task pour déclencher l'email automatique au
    tuteur + chef de département + assistante (voir attendance/services.py::
    check_student_absence_alerts). Même principe de page dédiée qu'accounting::
    hourly_rate_list/HourlyRate, mais en singleton par département (un seul
    seuil, pas une liste à créer/supprimer).
    """
    from .models import AbsenceAlertConfig

    if not request.user.can_manage_dept():
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    dept = request.active_department
    if not dept:
        messages.warning(request, "Veuillez sélectionner un département.")
        return redirect('academic_structure:select_department')

    config, _created = AbsenceAlertConfig.objects.get_or_create(
        department=dept, defaults={'updated_by': request.user}
    )

    if request.method == 'POST':
        try:
            seuil = int(request.POST.get('seuil_absences', '').strip())
        except (ValueError, TypeError):
            seuil = None
        if not seuil or seuil < 1:
            messages.error(request, "Veuillez saisir un nombre d'absences valide (supérieur à 0).")
        else:
            config.seuil_absences = seuil
            config.updated_by = request.user
            config.save()
            messages.success(
                request,
                f"Seuil d'alerte absences mis à jour : {seuil} séance(s) pour le département {dept.name}."
            )
            return redirect('attendance:absence_alert_config')

    return render(request, 'attendance/absence_alert_config.html', {
        'config': config,
        'dept': dept,
    })


@login_required
def course_plan_edit(request, subject_id, class_group_id, semester_id):
    """
    Permet à l'enseignant assigné à un EC (subject × class_group × semestre)
    de définir/modifier son plan de cours (liste de séances prévues avec
    titre + contenu) — accessible dès l'assignation du module, depuis « Mes
    modules ». Génère automatiquement les mots-clés du syllabus à
    l'enregistrement (voir services.py::generate_syllabus_keywords), utilisés
    ensuite pour la vérification de conformité (check_syllabus_compliance).
    """
    from decimal import Decimal
    from .forms import CoursePlanSessionFormSet
    from .models import CoursePlan
    from .services import generate_syllabus_keywords, compute_course_plan_progress
    from academic_core.apps.timetable.models import TimetableEntry as _TE

    teacher = _get_teacher_profile(request.user)
    if not teacher:
        messages.error(request, "Accès réservé aux enseignants.")
        return redirect('dashboard:index')

    entry = (
        _TE.objects
        .filter(teacher=teacher, subject_id=subject_id, class_group_id=class_group_id, semester_id=semester_id)
        .select_related('subject', 'class_group', 'semester__academic_year')
        .first()
    )
    if not entry:
        messages.error(request, "Module introuvable ou non assigné.")
        return redirect('attendance:my_modules')

    # Durée d'une séance = durée réelle du créneau dans l'emploi du temps —
    # imposée côté serveur (jamais un champ du formulaire) pour que
    # l'enseignant ne puisse pas la modifier, voir forms.py::CoursePlanSessionForm.
    session_duration = Decimal(str(round(entry.duration_hours, 2)))

    plan, _created = CoursePlan.objects.get_or_create(
        subject=entry.subject, class_group=entry.class_group,
        academic_year=entry.semester.academic_year, teacher=teacher,
    )

    if request.method == 'POST':
        formset = CoursePlanSessionFormSet(request.POST, instance=plan, prefix='sessions')
        if formset.is_valid():
            instances = formset.save(commit=False)
            for obj in formset.deleted_objects:
                obj.delete()
            for instance in instances:
                instance.duree_heures = session_duration
                instance.save()
            generate_syllabus_keywords(plan)
            messages.success(request, "Plan de cours enregistré avec succès.")
            return redirect('attendance:course_plan_edit',
                            subject_id=subject_id, class_group_id=class_group_id, semester_id=semester_id)
    else:
        formset = CoursePlanSessionFormSet(instance=plan, prefix='sessions')

    return render(request, 'attendance/course_plan_edit.html', {
        'formset': formset,
        'plan': plan,
        'subject': entry.subject,
        'class_group': entry.class_group,
        'semester': entry.semester,
        'session_duration': session_duration,
        'progress': compute_course_plan_progress(plan) if plan.pk else None,
    })


@login_required
def course_plan_view(request, teacher_id, subject_id, class_group_id, semester_id):
    """
    Consultation en lecture seule du plan de cours d'un enseignant pour un EC
    donné — accessible aux administrateurs, au chef de département et à son
    assistante (can_manage_dept()), depuis « Modules planifiés ». Ne permet
    aucune modification : seul l'enseignant titulaire édite son plan de cours
    (voir course_plan_edit).
    """
    from .models import CoursePlan
    from .services import compute_course_plan_progress
    from academic_core.apps.teachers.models import Teacher

    if not request.user.can_manage_dept():
        messages.error(request, "Accès réservé aux administrateurs de département.")
        return redirect('dashboard:index')

    teacher = get_object_or_404(Teacher, pk=teacher_id)
    entry = (
        TimetableEntry.objects
        .filter(teacher=teacher, subject_id=subject_id, class_group_id=class_group_id, semester_id=semester_id)
        .select_related('subject', 'class_group__program__department', 'semester__academic_year')
        .first()
    )
    if not entry:
        messages.error(request, "Module introuvable.")
        return redirect('attendance:planned_modules_admin')

    dept    = getattr(request, 'active_department', None)
    faculty = getattr(request, 'active_faculty', None)
    entry_dept = entry.class_group.program.department if entry.class_group.program else None
    out_of_scope = (
        (dept and entry_dept and entry_dept.pk != dept.pk) or
        (not dept and faculty and entry_dept and entry_dept.faculty_id != faculty.pk)
    )
    if out_of_scope:
        messages.error(request, "Ce module n'est pas dans votre périmètre.")
        return redirect('attendance:planned_modules_admin')

    try:
        plan = CoursePlan.objects.get(
            subject=entry.subject, class_group=entry.class_group,
            academic_year=entry.semester.academic_year, teacher=teacher,
        )
    except CoursePlan.DoesNotExist:
        plan = None

    return render(request, 'attendance/course_plan_view.html', {
        'plan': plan,
        'teacher': teacher,
        'subject': entry.subject,
        'class_group': entry.class_group,
        'semester': entry.semester,
        'sessions': plan.sessions.all() if plan else [],
        'progress': compute_course_plan_progress(plan) if plan else None,
    })
