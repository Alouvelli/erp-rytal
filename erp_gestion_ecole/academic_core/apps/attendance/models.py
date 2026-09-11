import secrets
from decimal import Decimal
from django.db import models
from django.utils.translation import gettext_lazy as _
from academic_core.apps.timetable.models import TimetableEntry
from academic_core.apps.students.models import Student
from academic_core.apps.accounts.models import User


class AttendanceSheet(models.Model):
    """Fiche d'émargement générée automatiquement pour chaque séance."""
    STATUS_PENDING = 'PENDING'
    STATUS_SIGNED = 'SIGNED'
    STATUS_VALIDATED = 'VALIDATED'
    STATUS_REJECTED = 'REJECTED'
    STATUS_CHOICES = [
        (STATUS_PENDING, _('En attente')),
        (STATUS_SIGNED, _('Signé par l\'enseignant')),
        (STATUS_VALIDATED, _('Validé')),
        (STATUS_REJECTED, _('Rejeté')),
    ]

    timetable_entry = models.ForeignKey(
        TimetableEntry, on_delete=models.CASCADE, related_name='attendance_sheets'
    )
    session_date = models.DateField(verbose_name=_('Date de la séance'))
    status = models.CharField(
        max_length=15, choices=STATUS_CHOICES, default=STATUS_PENDING
    )
    lesson_content = models.TextField(
        blank=True,
        verbose_name=_('Contenu de la séance'),
        help_text=_('Décrivez le contenu dispensé (cahier de texte).')
    )
    lesson_objectives = models.TextField(
        blank=True,
        verbose_name=_('Objectifs pédagogiques')
    )
    teacher_signature_at = models.DateTimeField(null=True, blank=True)
    teacher_comment = models.TextField(blank=True)
    signed_by_admin = models.BooleanField(
        default=False,
        verbose_name=_('Signé par l\'administrateur'),
        help_text=_('Vrai si c\'est l\'admin qui a signé à la place de l\'enseignant.')
    )
    validated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='validated_sheets'
    )
    validated_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    # QR code de pointage de séance
    session_qr_token = models.CharField(
        max_length=64, unique=True, blank=True,
        verbose_name=_('Token QR séance'),
        help_text=_('Token unique pour le QR code de pointage des présences en séance.')
    )
    absent_auto_done = models.BooleanField(
        default=False,
        verbose_name=_('Absences auto-marquées'),
        help_text=_('Vrai une fois que la tâche périodique a marqué les absents de fin de séance.')
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'attendance_sheets'
        verbose_name = _('Fiche d\'émargement')
        verbose_name_plural = _('Fiches d\'émargement')
        unique_together = ('timetable_entry', 'session_date')
        ordering = ['-session_date']
        indexes = [
            models.Index(fields=['timetable_entry', 'session_date']),
            models.Index(fields=['status']),
        ]

    def save(self, *args, **kwargs):
        if not self.session_qr_token:
            self.session_qr_token = secrets.token_urlsafe(32)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.timetable_entry} | {self.session_date} | {self.get_status_display()}"


class StudentAttendance(models.Model):
    """Présence/absence d'un étudiant pour une séance."""
    STATUS_PRESENT = 'PRESENT'
    STATUS_ABSENT = 'ABSENT'
    STATUS_JUSTIFIED = 'JUSTIFIED'
    STATUS_LATE = 'LATE'
    STATUS_CHOICES = [
        (STATUS_PRESENT, _('Présent')),
        (STATUS_ABSENT, _('Absent')),
        (STATUS_JUSTIFIED, _('Absence justifiée')),
        (STATUS_LATE, _('Retard')),
    ]

    attendance_sheet = models.ForeignKey(
        AttendanceSheet, on_delete=models.CASCADE, related_name='student_attendances'
    )
    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name='attendances'
    )
    status = models.CharField(
        max_length=15, choices=STATUS_CHOICES, default=STATUS_PRESENT
    )
    comment = models.TextField(blank=True)
    JUSTIFICATION_PENDING  = 'PENDING'
    JUSTIFICATION_APPROVED = 'APPROVED'
    JUSTIFICATION_REJECTED = 'REJECTED'
    JUSTIFICATION_STATUS_CHOICES = [
        (JUSTIFICATION_PENDING,  _('En attente')),
        (JUSTIFICATION_APPROVED, _('Approuvée')),
        (JUSTIFICATION_REJECTED, _('Rejetée')),
    ]

    justification_document = models.FileField(
        upload_to='justifications/', null=True, blank=True
    )
    justified_at = models.DateTimeField(
        null=True, blank=True,
        help_text=_('Date à laquelle la justification a été approuvée (statut passé à Justifiée).')
    )
    justification_status = models.CharField(
        max_length=10, choices=JUSTIFICATION_STATUS_CHOICES, blank=True,
        verbose_name=_('Statut de la justification'),
        help_text=_('Vide tant que l\'étudiant n\'a soumis aucune justification.')
    )
    justification_reason = models.TextField(
        blank=True, verbose_name=_('Motif fourni par l\'étudiant')
    )
    justification_submitted_at = models.DateTimeField(null=True, blank=True)
    justification_reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    justification_reviewed_at = models.DateTimeField(null=True, blank=True)
    justification_admin_note = models.TextField(
        blank=True, verbose_name=_('Note de l\'administrateur (motif de rejet le cas échéant)')
    )
    self_checkin = models.BooleanField(
        default=False,
        verbose_name=_('Auto-pointage'),
        help_text=_('Vrai si l\'étudiant a scanné le QR code de la séance.')
    )

    class Meta:
        db_table = 'student_attendances'
        verbose_name = _('Présence étudiant')
        verbose_name_plural = _('Présences étudiants')
        unique_together = ('attendance_sheet', 'student')
        indexes = [
            models.Index(fields=['student', 'status']),
        ]

    def __str__(self):
        return f"{self.student} | {self.attendance_sheet.session_date} | {self.get_status_display()}"


class SubjectProgress(models.Model):
    """Suivi du volume horaire effectué par matière × classe × année académique."""
    subject = models.ForeignKey(
        'subjects.Subject', on_delete=models.CASCADE, related_name='progress_records'
    )
    class_group = models.ForeignKey(
        'academic_structure.Class', on_delete=models.CASCADE, related_name='subject_progress'
    )
    academic_year = models.ForeignKey(
        'academic_structure.AcademicYear', on_delete=models.CASCADE, related_name='subject_progress'
    )
    teacher = models.ForeignKey(
        'teachers.Teacher', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='subject_progress'
    )
    hours_done = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal('0'))
    extra_hours = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal('0'),
                                      verbose_name=_('Heures supplémentaires approuvées'))
    notified_60 = models.BooleanField(default=False)
    notified_90 = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'subject_progress'
        unique_together = ('subject', 'class_group', 'academic_year')
        verbose_name = _('Progression module (EC)')
        verbose_name_plural = _('Progressions modules (EC)')

    def __str__(self):
        return f"{self.subject.title} | {self.class_group} | {self.academic_year}"

    @property
    def volume_total(self):
        return (self.subject.volume_hours or Decimal('0')) + self.extra_hours

    @property
    def percent_done(self):
        if not self.volume_total:
            return 0
        return int((self.hours_done / self.volume_total) * 100)

    @property
    def is_complete(self):
        return self.hours_done >= self.volume_total and self.volume_total > 0


class ExtraSessionRequest(models.Model):
    """Demande de séances supplémentaires quand le volume horaire est atteint."""
    STATUS_PENDING = 'PENDING'
    STATUS_APPROVED = 'APPROVED'
    STATUS_REJECTED = 'REJECTED'
    STATUS_CHOICES = [
        (STATUS_PENDING,  _('En attente')),
        (STATUS_APPROVED, _('Approuvée')),
        (STATUS_REJECTED, _('Rejetée')),
    ]

    subject = models.ForeignKey(
        'subjects.Subject', on_delete=models.CASCADE, related_name='extra_requests'
    )
    class_group = models.ForeignKey(
        'academic_structure.Class', on_delete=models.CASCADE, related_name='extra_requests'
    )
    academic_year = models.ForeignKey(
        'academic_structure.AcademicYear', on_delete=models.CASCADE, related_name='extra_requests'
    )
    teacher = models.ForeignKey(
        'teachers.Teacher', on_delete=models.CASCADE, related_name='extra_requests'
    )
    reason = models.TextField(verbose_name=_('Motif de la demande'))
    extra_hours_requested = models.DecimalField(max_digits=5, decimal_places=2,
                                                verbose_name=_('Heures demandées'))
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    extra_hours_approved = models.DecimalField(max_digits=5, decimal_places=2,
                                               null=True, blank=True,
                                               verbose_name=_('Heures approuvées'))
    admin_note = models.TextField(blank=True, verbose_name=_('Note de l\'administrateur'))
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reviewed_extra_requests'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'extra_session_requests'
        ordering = ['-created_at']
        verbose_name = _('Demande de séances supplémentaires')
        verbose_name_plural = _('Demandes de séances supplémentaires')

    def __str__(self):
        return f"{self.teacher} | {self.subject.title} | {self.class_group} | {self.get_status_display()}"


class AbsenceAlertConfig(models.Model):
    """Seuil d'absences (configurable par le chef de département) déclenchant
    l'envoi automatique d'une alerte email au tuteur + chef de département +
    assistante (voir attendance/services.py::check_student_absence_alerts)."""
    department = models.OneToOneField(
        'academic_structure.Department', on_delete=models.CASCADE,
        related_name='absence_alert_config', verbose_name=_('Département'),
    )
    seuil_absences = models.PositiveSmallIntegerField(
        default=10,
        verbose_name=_('Seuil d\'absences'),
        help_text=_('Nombre de séances d\'absence non justifiées au-delà duquel '
                    'une alerte automatique est envoyée au tuteur et au département.')
    )
    updated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'absence_alert_configs'
        verbose_name = _('Seuil d\'alerte absences')
        verbose_name_plural = _('Seuils d\'alerte absences')

    def __str__(self):
        return f"{self.department} — seuil {self.seuil_absences}"

    @classmethod
    def get_seuil(cls, department, default=10):
        if not department:
            return default
        cfg = cls.objects.filter(department=department).first()
        return cfg.seuil_absences if cfg else default


class StudentAbsenceAlert(models.Model):
    """Trace qu'une alerte d'absence a déjà été envoyée pour un étudiant sur
    un semestre donné — évite les envois répétés à chaque hausse du compteur
    une fois le seuil franchi (une alerte par étudiant par semestre)."""
    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name='absence_alerts'
    )
    semester = models.ForeignKey(
        'academic_structure.Semester', on_delete=models.CASCADE, related_name='absence_alerts'
    )
    department = models.ForeignKey(
        'academic_structure.Department', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='absence_alerts'
    )
    absence_count = models.PositiveIntegerField()
    threshold_used = models.PositiveSmallIntegerField()
    guardian_email_sent = models.BooleanField(default=False)
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'student_absence_alerts'
        unique_together = ('student', 'semester')
        verbose_name = _('Alerte absence étudiant')
        verbose_name_plural = _('Alertes absences étudiants')

    def __str__(self):
        return f"{self.student} | {self.semester} | {self.absence_count} absences"


class CoursePlan(models.Model):
    """Plan de cours (syllabus) qu'un enseignant définit pour un EC qui lui
    est assigné (subject × class_group × academic_year) — permet de suivre
    combien de séances planifiées restent à faire (voir propriétés ci-dessous
    et attendance/services.py::compute_course_plan_progress), et sert de base
    à la vérification automatique de conformité au syllabus (voir
    check_syllabus_compliance) : quelques mots-clés sont extraits
    aléatoirement du contenu prévu (voir generate_syllabus_keywords) puis
    recherchés dans le contenu réel des 5 premières séances émargées."""
    subject = models.ForeignKey(
        'subjects.Subject', on_delete=models.CASCADE, related_name='course_plans'
    )
    class_group = models.ForeignKey(
        'academic_structure.Class', on_delete=models.CASCADE, related_name='course_plans'
    )
    academic_year = models.ForeignKey(
        'academic_structure.AcademicYear', on_delete=models.CASCADE, related_name='course_plans'
    )
    teacher = models.ForeignKey(
        'teachers.Teacher', on_delete=models.CASCADE, related_name='course_plans'
    )
    syllabus_keywords = models.JSONField(
        default=list, blank=True,
        verbose_name=_('Mots-clés du syllabus'),
        help_text=_('Générés automatiquement et aléatoirement à partir du contenu prévu des séances.')
    )
    compliance_checked = models.BooleanField(
        default=False,
        help_text=_('Vrai une fois la vérification de conformité effectuée (sur les 5 premières séances émargées).')
    )
    compliance_match_pct = models.FloatField(null=True, blank=True)
    compliance_alert_sent = models.BooleanField(default=False)
    compliance_checked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'course_plans'
        unique_together = ('subject', 'class_group', 'academic_year', 'teacher')
        verbose_name = _('Plan de cours')
        verbose_name_plural = _('Plans de cours')

    def __str__(self):
        return f"{self.subject.title} | {self.class_group} | {self.teacher}"

    @property
    def total_seances_planifiees(self):
        return self.sessions.count()

    @property
    def seances_faites(self):
        from .models import AttendanceSheet
        return AttendanceSheet.objects.filter(
            timetable_entry__subject=self.subject,
            timetable_entry__class_group=self.class_group,
            timetable_entry__teacher=self.teacher,
            timetable_entry__semester__academic_year=self.academic_year,
            status=AttendanceSheet.STATUS_VALIDATED,
        ).exclude(lesson_content='').count()

    @property
    def seances_restantes(self):
        return max(self.total_seances_planifiees - self.seances_faites, 0)

    @property
    def percent_progression(self):
        total = self.total_seances_planifiees
        if not total:
            return 0
        return min(int(self.seances_faites / total * 100), 100)


class CoursePlanSession(models.Model):
    """Une séance planifiée dans le plan de cours (titre + contenu prévu)."""
    course_plan = models.ForeignKey(
        CoursePlan, on_delete=models.CASCADE, related_name='sessions'
    )
    numero = models.PositiveSmallIntegerField(verbose_name=_('N° de séance'))
    titre = models.CharField(max_length=200, verbose_name=_('Titre'))
    objectif = models.TextField(
        blank=True, verbose_name=_('Objectif de la séance'),
        help_text=_('Repris automatiquement dans le champ « Objectifs » du cahier de texte à l\'émargement.')
    )
    contenu_prevu = models.TextField(verbose_name=_('Contenu prévu'))
    duree_heures = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        verbose_name=_('Durée prévue (heures)')
    )

    class Meta:
        db_table = 'course_plan_sessions'
        unique_together = ('course_plan', 'numero')
        ordering = ['numero']
        verbose_name = _('Séance planifiée')
        verbose_name_plural = _('Séances planifiées')

    def __str__(self):
        return f"Séance {self.numero} — {self.titre}"
