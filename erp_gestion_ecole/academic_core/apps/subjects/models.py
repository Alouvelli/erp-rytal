from decimal import Decimal
import math
import re
from django.db import models
from django.utils.translation import gettext_lazy as _
from academic_core.apps.academic_structure.models import Program, Semester


def _syllabus_upload_path(instance, filename):
    return f"syllabus/{instance.program_id}/{instance.code}/{filename}"


def natural_sort_key(code):
    """
    Clé de tri "naturel" pour les codes EC/UE : compare les segments numériques
    par leur valeur entière plutôt que caractère par caractère, pour que
    'EC10' se classe après 'EC9' (un tri alphabétique classique donnerait
    'EC10' < 'EC2' puisque '1' < '2').
    """
    return [
        int(chunk) if chunk.isdigit() else chunk.lower()
        for chunk in re.split(r'(\d+)', code or '')
    ]


class Subject(models.Model):
    TYPE_CM = 'CM'
    TYPE_TD = 'TD'
    TYPE_TP = 'TP'
    TYPE_CHOICES = [
        (TYPE_CM, _('Cours magistral')),
        (TYPE_TD, _('Travaux dirigés')),
        (TYPE_TP, _('Travaux pratiques')),
    ]

    code = models.CharField(max_length=20, unique=True, verbose_name=_('Code'))
    title = models.CharField(max_length=200, verbose_name=_('Intitulé'))
    program = models.ForeignKey(
        Program, on_delete=models.CASCADE, related_name='subjects'
    )
    semester = models.ForeignKey(
        Semester, on_delete=models.SET_NULL, null=True, related_name='subjects'
    )
    subject_type = models.CharField(
        max_length=5, choices=TYPE_CHOICES, default=TYPE_CM
    )
    coefficient = models.DecimalField(
        max_digits=4, decimal_places=2, default=1, verbose_name=_('Coefficient')
    )
    credits = models.PositiveSmallIntegerField(default=0, verbose_name=_('Crédits ECTS'))

    # Volumes horaires détaillés
    volume_cm = models.DecimalField(
        max_digits=6, decimal_places=2, default=0,
        verbose_name=_('Volume CM (h)')
    )
    volume_td = models.DecimalField(
        max_digits=6, decimal_places=2, default=0,
        verbose_name=_('Volume TD (h)')
    )
    volume_tp = models.DecimalField(
        max_digits=6, decimal_places=2, default=0,
        verbose_name=_('Volume TP (h)')
    )
    volume_tpe = models.DecimalField(
        max_digits=6, decimal_places=2, default=0,
        verbose_name=_('Volume TPE (h)')
    )
    # Volume horaire officiel = CM + TD + TP (utilisé pour les crédits)
    volume_hours = models.DecimalField(
        max_digits=6, decimal_places=2, default=0,
        verbose_name=_('Volume horaire (CM+TD+TP)')
    )
    # Volume total UE = CM + TD + TP + TPE
    volume_total_ue = models.DecimalField(
        max_digits=6, decimal_places=2, default=0,
        verbose_name=_('Volume total UE (h)')
    )

    responsible_teacher = models.ForeignKey(
        'teachers.Teacher', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='responsible_subjects', verbose_name=_('Enseignant responsable')
    )
    syllabus = models.FileField(
        upload_to=_syllabus_upload_path, null=True, blank=True,
        verbose_name=_('Syllabus'),
        help_text=_("Document de référence fourni à l'enseignant lors de l'attribution de l'EC ; il est tenu de le suivre."),
    )
    ue = models.ForeignKey(
        'grades.UniteEnseignement', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='subjects',
        verbose_name=_("Unité d'Enseignement")
    )
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'subjects'
        verbose_name = _('Module (EC)')
        verbose_name_plural = _('Modules (EC)')
        ordering = ['code']

    def save(self, *args, **kwargs):
        cm  = self.volume_cm  or 0
        td  = self.volume_td  or 0
        tp  = self.volume_tp  or 0
        tpe = self.volume_tpe or 0
        # Volume horaire officiel = CM + TD + TP (base des crédits)
        self.volume_hours = cm + td + tp
        # Volume total UE = CM + TD + TP + TPE
        self.volume_total_ue = cm + td + tp + tpe
        # Crédits = volume total UE (CM+TD+TP+TPE) / 20, partie entière
        if self.volume_total_ue > 0:
            self.credits = int(float(self.volume_total_ue) // 20)
        else:
            self.credits = 0
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.code} - {self.title}"
