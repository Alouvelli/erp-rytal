from django.db import models
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from academic_core.apps.academic_structure.models import Class, Semester
from academic_core.apps.subjects.models import Subject
from academic_core.apps.teachers.models import Teacher
from academic_core.apps.rooms.models import Room


class TimetableEntry(models.Model):
    DAY_MON = 1
    DAY_TUE = 2
    DAY_WED = 3
    DAY_THU = 4
    DAY_FRI = 5
    DAY_SAT = 6
    DAY_SUN = 7
    DAY_CHOICES = [
        (DAY_MON, _('Lundi')),
        (DAY_TUE, _('Mardi')),
        (DAY_WED, _('Mercredi')),
        (DAY_THU, _('Jeudi')),
        (DAY_FRI, _('Vendredi')),
        (DAY_SAT, _('Samedi')),
        (DAY_SUN, _('Dimanche')),
    ]

    RECURRENCE_WEEKLY = 'WEEKLY'
    RECURRENCE_BIWEEKLY = 'BIWEEKLY'
    RECURRENCE_ONCE = 'ONCE'
    RECURRENCE_CHOICES = [
        (RECURRENCE_WEEKLY, _('Hebdomadaire')),
        (RECURRENCE_BIWEEKLY, _('Bi-hebdomadaire')),
        (RECURRENCE_ONCE, _('Ponctuel')),
    ]

    semester = models.ForeignKey(
        Semester, on_delete=models.CASCADE, related_name='timetable_entries'
    )
    class_group = models.ForeignKey(
        Class, on_delete=models.CASCADE, related_name='timetable_entries',
        verbose_name=_('Classe')
    )
    subject = models.ForeignKey(
        Subject, on_delete=models.CASCADE, related_name='timetable_entries'
    )
    teacher = models.ForeignKey(
        Teacher, on_delete=models.CASCADE, related_name='timetable_entries'
    )
    room = models.ForeignKey(
        Room, on_delete=models.SET_NULL, null=True, related_name='timetable_entries'
    )
    day_of_week = models.PositiveSmallIntegerField(choices=DAY_CHOICES)
    start_time = models.TimeField(verbose_name=_('Heure de début'))
    end_time = models.TimeField(verbose_name=_('Heure de fin'))
    recurrence = models.CharField(
        max_length=15, choices=RECURRENCE_CHOICES, default=RECURRENCE_WEEKLY
    )
    specific_date = models.DateField(
        null=True, blank=True, verbose_name=_('Date spécifique (si ponctuel)')
    )
    color = models.CharField(max_length=7, default='#3788d8', verbose_name=_('Couleur'))
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'timetable_entries'
        verbose_name = _('Entrée emploi du temps')
        verbose_name_plural = _('Emplois du temps')
        indexes = [
            models.Index(fields=['semester', 'class_group']),
            models.Index(fields=['teacher', 'day_of_week']),
            models.Index(fields=['room', 'day_of_week']),
        ]

    def __str__(self):
        return f"{self.class_group} | {self.subject} | {self.get_day_of_week_display()} {self.start_time}"

    @property
    def duration_hours(self):
        from datetime import datetime, date
        start = datetime.combine(date.today(), self.start_time)
        end = datetime.combine(date.today(), self.end_time)
        return (end - start).seconds / 3600

    def clean(self):
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            raise ValidationError(_("L'heure de début doit être avant l'heure de fin."))

    def check_conflicts(self):
        """Returns list of conflict descriptions."""
        conflicts = []
        qs = TimetableEntry.objects.filter(
            semester=self.semester,
            day_of_week=self.day_of_week,
            is_active=True,
        ).exclude(pk=self.pk)

        # time overlap helper
        def overlaps(e):
            return e.start_time < self.end_time and e.end_time > self.start_time

        teacher_conflicts = [e for e in qs.filter(teacher=self.teacher) if overlaps(e)]
        room_conflicts = [e for e in qs.filter(room=self.room) if overlaps(e)]
        class_conflicts = [e for e in qs.filter(class_group=self.class_group) if overlaps(e)]

        if teacher_conflicts:
            conflicts.append(f"Conflit enseignant: {teacher_conflicts[0]}")
        if room_conflicts:
            conflicts.append(f"Conflit salle: {room_conflicts[0]}")
        if class_conflicts:
            conflicts.append(f"Conflit classe: {class_conflicts[0]}")

        return conflicts


class SessionLog(models.Model):
    """Cahier de texte numérique : objectifs + contenu réalisé par séance."""
    timetable_entry = models.ForeignKey(
        TimetableEntry, on_delete=models.CASCADE,
        related_name='session_logs', verbose_name=_('Créneau')
    )
    session_date = models.DateField(verbose_name=_('Date de la séance'))
    objectives   = models.TextField(verbose_name=_('Objectifs de la séance'))
    content      = models.TextField(blank=True, verbose_name=_('Contenu réalisé'))
    remarks      = models.TextField(blank=True, verbose_name=_('Observations'))
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    # ── Validation (Responsable de classe / Chef de Département) ────────────
    is_validated = models.BooleanField(default=False, verbose_name=_('Validé'))
    validated_at = models.DateTimeField(null=True, blank=True, verbose_name=_('Validé le'))
    validated_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='validated_session_logs', db_constraint=False,
        verbose_name=_('Validé par'),
    )

    class Meta:
        db_table        = 'timetable_session_logs'
        unique_together = ('timetable_entry', 'session_date')
        ordering        = ['session_date']
        verbose_name    = _('Log de séance')

    def __str__(self):
        return f"{self.timetable_entry.subject} — {self.session_date}"


class TimetableConflict(models.Model):
    CONFLICT_TEACHER = 'TEACHER'
    CONFLICT_ROOM = 'ROOM'
    CONFLICT_CLASS = 'CLASS'
    CONFLICT_TYPE_CHOICES = [
        (CONFLICT_TEACHER, _('Conflit enseignant')),
        (CONFLICT_ROOM, _('Conflit salle')),
        (CONFLICT_CLASS, _('Conflit classe')),
    ]

    entry_1 = models.ForeignKey(
        TimetableEntry, on_delete=models.CASCADE, related_name='conflicts_as_first'
    )
    entry_2 = models.ForeignKey(
        TimetableEntry, on_delete=models.CASCADE, related_name='conflicts_as_second'
    )
    conflict_type = models.CharField(max_length=10, choices=CONFLICT_TYPE_CHOICES)
    detected_at = models.DateTimeField(auto_now_add=True)
    resolved = models.BooleanField(default=False)

    class Meta:
        db_table = 'timetable_conflicts'
        verbose_name = _('Conflit emploi du temps')


def _support_upload_path(instance, filename):
    import os
    ext = os.path.splitext(filename)[1]
    return f"supports/{instance.teacher_id}/{instance.subject_id}/{filename}"


class CourseSupport(models.Model):
    TYPE_CM    = 'CM'
    TYPE_TD    = 'TD'
    TYPE_TP    = 'TP'
    TYPE_OTHER = 'AUTRE'
    TYPE_CHOICES = [
        (TYPE_CM,    'Cours Magistral (CM)'),
        (TYPE_TD,    'Travaux Dirigés (TD)'),
        (TYPE_TP,    'Travaux Pratiques (TP)'),
        (TYPE_OTHER, 'Autre'),
    ]

    teacher     = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name='course_supports', verbose_name=_('Enseignant'))
    subject     = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='course_supports', verbose_name=_('Module (EC)'))
    class_group = models.ForeignKey(Class,   on_delete=models.CASCADE, related_name='course_supports', verbose_name=_('Classe'))
    semester    = models.ForeignKey(Semester, on_delete=models.CASCADE, related_name='course_supports', verbose_name=_('Semestre'))
    title       = models.CharField(max_length=255, verbose_name=_('Titre du support'))
    description = models.TextField(blank=True, verbose_name=_('Description'))
    support_type = models.CharField(max_length=10, choices=TYPE_CHOICES, default=TYPE_CM, verbose_name=_('Type'))
    file        = models.FileField(upload_to=_support_upload_path, verbose_name=_('Fichier'))
    shared_at   = models.DateTimeField(auto_now_add=True, verbose_name=_('Partagé le'))
    is_active   = models.BooleanField(default=True, verbose_name=_('Actif'))

    class Meta:
        db_table = 'course_supports'
        ordering = ['-shared_at']
        verbose_name = _('Support de cours')
        verbose_name_plural = _('Supports de cours')

    def __str__(self):
        return f"{self.get_support_type_display()} — {self.subject.title} ({self.class_group.name})"

    @property
    def filename(self):
        import os
        return os.path.basename(self.file.name) if self.file else ''

    @property
    def file_extension(self):
        import os
        _, ext = os.path.splitext(self.file.name)
        return ext.lower().lstrip('.') if self.file else ''


class PlanningHoliday(models.Model):
    """Période de suspension du planning pour une ou plusieurs classes."""
    from django.conf import settings

    class_group = models.ForeignKey(
        'academic_structure.Class',
        on_delete=models.CASCADE,
        related_name='planning_holidays',
        verbose_name=_('Classe'),
    )
    start_date = models.DateField(verbose_name=_('Date de début'))
    end_date   = models.DateField(verbose_name=_('Date de fin'))
    reason     = models.CharField(max_length=300, blank=True, verbose_name=_('Motif'))
    created_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='planning_holidays_created',
        verbose_name=_('Créé par'),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = 'planning_holidays'
        ordering  = ['-start_date']
        verbose_name        = _('Suspension de planning')
        verbose_name_plural = _('Suspensions de planning')

    def __str__(self):
        return f"Suspension {self.class_group} : {self.start_date} → {self.end_date}"

    @property
    def is_active(self):
        from datetime import date
        today = date.today()
        return self.start_date <= today <= self.end_date

    @property
    def is_expired(self):
        from datetime import date
        return date.today() > self.end_date

    @property
    def is_upcoming(self):
        from datetime import date
        return date.today() < self.start_date

    def covers_date(self, d):
        return self.start_date <= d <= self.end_date
