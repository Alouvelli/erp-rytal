from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils.translation import gettext_lazy as _
from academic_core.apps.students.models import Student, Enrollment
from academic_core.apps.subjects.models import Subject
from academic_core.apps.academic_structure.models import Semester, Program
from academic_core.apps.teachers.models import Teacher


class EvaluationType(models.Model):
    CC = 'CC'
    TP = 'TP'
    PROJECT = 'PROJECT'
    EXAM = 'EXAM'
    RATTRAPAGE = 'RATTRAPAGE'
    DEVOIR1 = 'DEVOIR1'
    DEVOIR2 = 'DEVOIR2'
    TYPE_CHOICES = [
        (CC, _('Contrôle continu')),
        (TP, _('Travaux pratiques')),
        (PROJECT, _('Projet')),
        (EXAM, _('Examen final')),
        (RATTRAPAGE, _('Rattrapage')),
        (DEVOIR1, _('Devoir 1')),
        (DEVOIR2, _('Devoir 2')),
    ]

    code = models.CharField(max_length=15, choices=TYPE_CHOICES, unique=True)
    label = models.CharField(max_length=100)
    weight = models.DecimalField(
        max_digits=5, decimal_places=2, default=1,
        help_text=_('Coefficient de pondération')
    )

    class Meta:
        db_table = 'evaluation_types'
        verbose_name = _('Type d\'évaluation')

    def __str__(self):
        return self.label


class Evaluation(models.Model):
    STATUS_SCHEDULED  = 'SCHEDULED'
    STATUS_ONGOING    = 'ONGOING'
    STATUS_GRADED     = 'GRADED'
    STATUS_LOCKED     = 'LOCKED'
    STATUS_CHOICES = [
        (STATUS_SCHEDULED, _('Programmée')),
        (STATUS_ONGOING,   _('En cours de correction')),
        (STATUS_GRADED,    _('Notes saisies')),
        (STATUS_LOCKED,    _('Verrouillée')),
    ]

    subject = models.ForeignKey(
        Subject, on_delete=models.CASCADE, related_name='evaluations'
    )
    semester = models.ForeignKey(
        Semester, on_delete=models.CASCADE, related_name='evaluations'
    )
    class_group = models.ForeignKey(
        'academic_structure.Class', on_delete=models.CASCADE,
        related_name='evaluations', null=True, blank=True,
        verbose_name=_('Classe')
    )
    evaluation_type = models.ForeignKey(
        EvaluationType, on_delete=models.CASCADE, related_name='evaluations'
    )
    teacher = models.ForeignKey(
        Teacher, on_delete=models.SET_NULL, null=True, related_name='evaluations'
    )
    title = models.CharField(max_length=200, verbose_name=_('Intitulé'))
    date = models.DateField(verbose_name=_('Date'))
    duration_minutes = models.PositiveSmallIntegerField(
        null=True, blank=True, verbose_name=_('Durée (minutes)')
    )
    room = models.CharField(max_length=100, blank=True, verbose_name=_('Lieu / Salle'))
    instructions = models.TextField(
        blank=True, verbose_name=_('Consignes / Instructions')
    )
    max_score = models.DecimalField(
        max_digits=5, decimal_places=2, default=20,
        verbose_name=_('Note maximale')
    )
    coefficient = models.DecimalField(
        max_digits=4, decimal_places=2, default=1,
        verbose_name=_('Coefficient')
    )
    status = models.CharField(
        max_length=15, choices=STATUS_CHOICES, default=STATUS_SCHEDULED,
        verbose_name=_('Statut')
    )
    notification_sent = models.BooleanField(
        default=False, verbose_name=_('Notification envoyée')
    )
    is_locked = models.BooleanField(
        default=False, verbose_name=_('Notes verrouillées')
    )
    locked_at = models.DateTimeField(null=True, blank=True)
    locked_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='locked_evaluations', db_constraint=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'evaluations'
        verbose_name = _('Évaluation')
        verbose_name_plural = _('Évaluations')
        ordering = ['semester', 'subject', 'date']

    def __str__(self):
        return f"{self.subject} | {self.evaluation_type} | {self.date}"


class Grade(models.Model):
    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name='grades'
    )
    evaluation = models.ForeignKey(
        Evaluation, on_delete=models.CASCADE, related_name='grades'
    )
    score = models.DecimalField(
        max_digits=5, decimal_places=2,
        validators=[MinValueValidator(0)],
        verbose_name=_('Note')
    )
    comment = models.TextField(blank=True)
    entered_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True,
        related_name='entered_grades', db_constraint=False,
    )
    entered_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'grades'
        verbose_name = _('Note')
        verbose_name_plural = _('Notes')
        unique_together = ('student', 'evaluation')
        indexes = [
            models.Index(fields=['student', 'evaluation']),
        ]

    def __str__(self):
        return f"{self.student} | {self.evaluation} | {self.score}/{self.evaluation.max_score}"


class SubjectAverage(models.Model):
    """Moyenne calculée par matière et par semestre."""
    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name='subject_averages'
    )
    subject = models.ForeignKey(
        Subject, on_delete=models.CASCADE, related_name='student_averages'
    )
    semester = models.ForeignKey(
        Semester, on_delete=models.CASCADE, related_name='subject_averages'
    )
    average = models.DecimalField(max_digits=5, decimal_places=2)
    is_validated = models.BooleanField(default=False)
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'subject_averages'
        verbose_name = _('Moyenne module (EC)')
        unique_together = ('student', 'subject', 'semester')

    def __str__(self):
        return f"{self.student} | {self.subject} S{self.semester.number}: {self.average}"


class SemesterAverage(models.Model):
    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name='semester_averages'
    )
    semester = models.ForeignKey(
        Semester, on_delete=models.CASCADE, related_name='student_averages'
    )
    average = models.DecimalField(max_digits=5, decimal_places=2)
    rank = models.PositiveSmallIntegerField(null=True, blank=True)
    total_students = models.PositiveSmallIntegerField(null=True, blank=True)
    mention = models.CharField(max_length=50, blank=True)
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'semester_averages'
        verbose_name = _('Moyenne semestrielle')
        unique_together = ('student', 'semester')

    def __str__(self):
        return f"{self.student} | S{self.semester.number}: {self.average}"


# ─── LMD : Unités d'Enseignement ──────────────────────────────────────────────

class UniteEnseignement(models.Model):
    code = models.CharField(max_length=20, verbose_name=_('Code UE'))
    title = models.CharField(max_length=200, verbose_name=_('Intitulé'))
    program = models.ForeignKey(
        Program, on_delete=models.CASCADE, related_name='unites_enseignement',
        verbose_name=_('Filière')
    )
    semester = models.ForeignKey(
        Semester, on_delete=models.CASCADE, related_name='unites_enseignement',
        verbose_name=_('Semestre')
    )
    credits = models.PositiveSmallIntegerField(default=6, verbose_name=_('Crédits UE'))
    order = models.PositiveSmallIntegerField(default=1, verbose_name=_('Ordre d\'affichage'))

    class Meta:
        db_table = 'unites_enseignement'
        verbose_name = _('Unité d\'Enseignement')
        verbose_name_plural = _('Unités d\'Enseignement')
        ordering = ['semester', 'order', 'code']
        unique_together = ('code', 'program', 'semester')

    def __str__(self):
        return f"{self.code} - {self.title}"


# ─── LMD : Bulletins ──────────────────────────────────────────────────────────

class Bulletin(models.Model):
    STATUS_DRAFT = 'DRAFT'
    STATUS_PUBLISHED = 'PUBLISHED'
    STATUS_LOCKED = 'LOCKED'
    STATUS_CHOICES = [
        (STATUS_DRAFT, _('Brouillon')),
        (STATUS_PUBLISHED, _('Publié')),
        (STATUS_LOCKED, _('Verrouillé')),
    ]

    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name='bulletins',
        verbose_name=_('Etudiant')
    )
    semester = models.ForeignKey(
        Semester, on_delete=models.CASCADE, related_name='bulletins',
        verbose_name=_('Semestre')
    )
    class_group = models.ForeignKey(
        'academic_structure.Class', on_delete=models.SET_NULL, null=True,
        related_name='bulletins', verbose_name=_('Classe')
    )
    status = models.CharField(
        max_length=15, choices=STATUS_CHOICES, default=STATUS_DRAFT
    )
    semester_average = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        verbose_name=_('Moyenne semestrielle')
    )
    total_credits_obtained = models.PositiveSmallIntegerField(default=0)
    total_credits_possible = models.PositiveSmallIntegerField(default=0)
    mention = models.CharField(max_length=50, blank=True)
    jury_decision = models.CharField(max_length=200, blank=True)
    generated_at = models.DateTimeField(auto_now=True)
    generated_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='generated_bulletins', db_constraint=False,
    )

    class Meta:
        db_table = 'bulletins'
        verbose_name = _('Bulletin')
        verbose_name_plural = _('Bulletins')
        unique_together = ('student', 'semester')

    def __str__(self):
        return f"Bulletin {self.student} | S{self.semester.number}"


class BulletinUEResult(models.Model):
    bulletin = models.ForeignKey(
        Bulletin, on_delete=models.CASCADE, related_name='ue_results'
    )
    ue = models.ForeignKey(
        UniteEnseignement, on_delete=models.CASCADE, related_name='bulletin_results'
    )
    average = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    credits_obtained = models.PositiveSmallIntegerField(default=0)
    is_validated = models.BooleanField(default=False)
    order = models.PositiveSmallIntegerField(default=1)

    class Meta:
        db_table = 'bulletin_ue_results'
        unique_together = ('bulletin', 'ue')
        ordering = ['order']


class BulletinECResult(models.Model):
    bulletin = models.ForeignKey(
        Bulletin, on_delete=models.CASCADE, related_name='ec_results'
    )
    ue_result = models.ForeignKey(
        BulletinUEResult, on_delete=models.CASCADE, related_name='ec_results',
        null=True, blank=True
    )
    subject = models.ForeignKey(
        Subject, on_delete=models.CASCADE, related_name='bulletin_results'
    )
    cc_average = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    exam_score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    rattrapage_score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    final_average = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    appreciation = models.CharField(max_length=20, blank=True)
    is_validated = models.BooleanField(default=False)

    class Meta:
        db_table = 'bulletin_ec_results'
        unique_together = ('bulletin', 'subject')
        ordering = ['subject__code']


# ─── Examens & Concours : validation administrative des notes par EC ─────────

class ECValidation(models.Model):
    """
    Validation, par la Direction des Études, des notes d'un EC pour une classe
    et un semestre donnés. Déclenche l'import automatique des notes dans la
    gestion des bulletins (recalcul + sauvegarde des Bulletin/BulletinECResult).
    """
    subject = models.ForeignKey(
        Subject, on_delete=models.CASCADE, related_name='ec_validations'
    )
    class_group = models.ForeignKey(
        'academic_structure.Class', on_delete=models.CASCADE,
        related_name='ec_validations', verbose_name=_('Classe')
    )
    semester = models.ForeignKey(
        Semester, on_delete=models.CASCADE, related_name='ec_validations'
    )
    is_validated = models.BooleanField(default=False)
    validated_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='validated_ecs', db_constraint=False,
    )
    validated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'ec_validations'
        verbose_name = _('Validation EC (Examens & Concours)')
        verbose_name_plural = _('Validations EC (Examens & Concours)')
        unique_together = ('subject', 'class_group', 'semester')

    def __str__(self):
        return f"{self.subject} | {self.class_group} | S{self.semester.number}"


# ─── Réclamations de notes ─────────────────────────────────────────────────

class GradeComplaint(models.Model):
    """
    Réclamation de note traitée pour un étudiant sur un semestre donné —
    enregistrer une réclamation ici signifie qu'elle a été traitée
    favorablement (l'étudiant est comptabilisé comme validé grâce à elle,
    au même titre qu'un repêchage) : voir grades/class_results_services.py,
    utilisé par le « Rapport Annuel de la Direction ».
    """
    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name='grade_complaints',
        verbose_name=_('Étudiant'),
    )
    class_group = models.ForeignKey(
        'academic_structure.Class', on_delete=models.CASCADE,
        related_name='grade_complaints', verbose_name=_('Classe'),
    )
    semester = models.ForeignKey(
        Semester, on_delete=models.CASCADE, related_name='grade_complaints',
        verbose_name=_('Semestre'),
    )
    description = models.TextField(blank=True, verbose_name=_('Motif de la réclamation'))
    processed_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='grade_complaints_processed', db_constraint=False,
        verbose_name=_('Traitée par'),
    )
    processed_at = models.DateTimeField(auto_now_add=True, verbose_name=_('Traitée le'))

    class Meta:
        db_table = 'grade_complaints'
        verbose_name = _('Réclamation de note')
        verbose_name_plural = _('Réclamations de notes')
        ordering = ['-processed_at']

    def __str__(self):
        return f"Réclamation — {self.student} — {self.class_group} — S{self.semester.number}"
