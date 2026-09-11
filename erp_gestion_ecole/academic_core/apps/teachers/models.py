from django.db import models
from django.utils.translation import gettext_lazy as _
from academic_core.apps.accounts.models import User


class Grade(models.Model):
    """Grade académique de l'enseignant (MCF, PU, etc.)"""
    code = models.CharField(max_length=20, unique=True)
    label = models.CharField(max_length=100)
    order = models.PositiveSmallIntegerField(default=1)

    class Meta:
        db_table = 'teacher_grades'
        verbose_name = _('Grade')
        verbose_name_plural = _('Grades')
        ordering = ['order']

    def __str__(self):
        return f"{self.code} - {self.label}"


class Teacher(models.Model):
    STATUT_PERMANENT = 'PERMANENT'
    STATUT_VACATAIRE = 'VACATAIRE'
    STATUT_CHOICES = [
        (STATUT_PERMANENT, _('Permanent')),
        (STATUT_VACATAIRE, _('Vacataire')),
    ]

    SITUATION_CELIBATAIRE = 'CELIBATAIRE'
    SITUATION_MARIE = 'MARIE'
    SITUATION_DIVORCE = 'DIVORCE'
    SITUATION_VEUF = 'VEUF'
    SITUATION_CHOICES = [
        (SITUATION_CELIBATAIRE, _('Célibataire')),
        (SITUATION_MARIE, _('Marié(e)')),
        (SITUATION_DIVORCE, _('Divorcé(e)')),
        (SITUATION_VEUF, _('Veuf(ve)')),
    ]

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name='teacher_profile'
    )
    matricule = models.CharField(max_length=30, unique=True, verbose_name=_('Matricule'))
    grade = models.ForeignKey(
        Grade, on_delete=models.SET_NULL, null=True, related_name='teachers'
    )
    specialty = models.CharField(max_length=200, verbose_name=_('Spécialité'))
    statut = models.CharField(
        max_length=20, choices=STATUT_CHOICES, default=STATUT_PERMANENT
    )
    contractual_hours = models.DecimalField(
        max_digits=6, decimal_places=2, default=0,
        verbose_name=_('Volume horaire contractuel')
    )
    hire_date = models.DateField(null=True, blank=True, verbose_name=_('Date d\'embauche'))
    bio = models.TextField(blank=True)

    # ── Informations civiles (contrat de prestation de service) ──────────────
    date_naissance = models.DateField(null=True, blank=True, verbose_name=_('Date de naissance'))
    lieu_naissance = models.CharField(max_length=200, blank=True, verbose_name=_('Lieu de naissance'))
    nationalite = models.CharField(max_length=100, blank=True, default='Sénégalaise', verbose_name=_('Nationalité'))
    num_cin_passeport = models.CharField(max_length=100, blank=True, verbose_name=_('N° CIN / Passeport'))
    situation_matrimoniale = models.CharField(
        max_length=20, choices=SITUATION_CHOICES, blank=True, verbose_name=_('Situation matrimoniale'),
    )
    adresse = models.CharField(max_length=255, blank=True, verbose_name=_('Adresse complète'))
    lieu_residence = models.CharField(max_length=200, blank=True, verbose_name=_('Lieu de résidence habituelle'))
    profession = models.CharField(max_length=150, blank=True, verbose_name=_('Profession'))
    ninea = models.CharField(max_length=50, blank=True, verbose_name=_('NINEA'))

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'teachers'
        verbose_name = _('Enseignant')
        verbose_name_plural = _('Enseignants')

    def __str__(self):
        return f"{self.matricule} - {self.user.get_full_name()}"

    @property
    def full_name(self):
        return self.user.get_full_name()

    @property
    def email(self):
        return self.user.email

    def get_total_hours_taught(self, academic_year=None):
        from academic_core.apps.attendance.models import AttendanceSheet
        qs = AttendanceSheet.objects.filter(
            timetable_entry__teacher=self,
            status='VALIDATED',
        )
        if academic_year:
            qs = qs.filter(timetable_entry__semester__academic_year=academic_year)
        total = sum(
            (s.timetable_entry.duration_hours for s in qs),
            0
        )
        return total


class ContratEnseignant(models.Model):
    """
    Contrat de prestation de service entre l'institut et un enseignant, pour un
    département et une année académique donnés. Un enseignant intervenant dans
    plusieurs départements a un contrat distinct par département.

    Le tableau des modules (Article 1) n'est jamais figé : il est recalculé à
    la demande depuis les TimetableEntry actifs, afin de toujours refléter les
    affectations d'EC en cours (voir modules_rows()).
    """
    teacher = models.ForeignKey(
        Teacher, on_delete=models.CASCADE, related_name='contrats',
        verbose_name=_('Enseignant'),
    )
    department = models.ForeignKey(
        'academic_structure.Department', on_delete=models.CASCADE,
        related_name='contrats_enseignants', verbose_name=_('Département'),
    )
    academic_year = models.ForeignKey(
        'academic_structure.AcademicYear', on_delete=models.CASCADE,
        related_name='contrats_enseignants', verbose_name=_('Année académique'),
    )
    lieu_signature = models.CharField(max_length=100, blank=True, default='Dakar', verbose_name=_('Lieu de signature'))
    date_signature = models.DateField(null=True, blank=True, verbose_name=_('Date de signature'))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'contrats_enseignants'
        verbose_name = _('Contrat enseignant')
        verbose_name_plural = _('Contrats enseignants')
        unique_together = ('teacher', 'department', 'academic_year')
        ordering = ['department__name', 'teacher__user__last_name']

    def __str__(self):
        return f"Contrat {self.teacher.full_name} — {self.department.name} ({self.academic_year})"

    def modules_rows(self):
        """
        Calcule EN DIRECT (jamais figé) les lignes du tableau de l'Article 1 :
        une ligne par (matière, semestre) enseigné par ce professeur dans ce
        département pour cette année académique, classes concernées listées,
        volume horaire = Subject.volume_hours (volume officiel du module).
        """
        from academic_core.apps.timetable.models import TimetableEntry

        entries = (
            TimetableEntry.objects
            .filter(
                teacher=self.teacher, is_active=True,
                semester__academic_year=self.academic_year,
                class_group__program__department=self.department,
            )
            .select_related('subject', 'semester', 'class_group')
        )

        grouped = {}
        for e in entries:
            key = (e.subject_id, e.semester_id)
            g = grouped.setdefault(key, {
                'subject': e.subject, 'semester': e.semester, 'classes': set(),
            })
            g['classes'].add(e.class_group.name)

        rows = [
            {
                'module': g['subject'].title,
                'semestre': f"S{g['semester'].number}",
                'classes': ', '.join(sorted(g['classes'])),
                'volume': g['subject'].volume_hours,
            }
            for g in grouped.values()
        ]
        return sorted(rows, key=lambda r: (r['semestre'], r['module']))
