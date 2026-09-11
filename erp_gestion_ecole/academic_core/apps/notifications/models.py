from django.db import models
from django.utils.translation import gettext_lazy as _
from academic_core.apps.accounts.models import User


class Notification(models.Model):
    TYPE_NEW_GRADE = 'NEW_GRADE'
    TYPE_ABSENCE = 'ABSENCE'
    TYPE_COURSE_CANCELLED = 'COURSE_CANCELLED'
    TYPE_TIMETABLE_CHANGE = 'TIMETABLE_CHANGE'
    TYPE_SHEET_VALIDATED = 'SHEET_VALIDATED'
    TYPE_EVAL_DEVOIR = 'EVAL_DEVOIR'
    TYPE_EVAL_EXAMEN = 'EVAL_EXAMEN'
    TYPE_VOLUME_COMPLETE = 'VOL_COMPLETE'
    TYPE_EXTRA_REQUEST = 'EXTRA_REQUEST'
    TYPE_EXTRA_APPROVED = 'EXTRA_APPROVED'
    TYPE_EXTRA_REJECTED = 'EXTRA_REJECTED'
    TYPE_GENERAL = 'GENERAL'
    TYPE_COURSE_SUPPORT = 'COURSE_SUPPORT'
    TYPE_INSCRIPTION_PENDING   = 'INSCRIPTION_PENDING'
    TYPE_INSCRIPTION_VALIDATED = 'INSCRIPTION_VALIDATED'
    TYPE_INSCRIPTION_REJECTED  = 'INSCRIPTION_REJECTED'
    # ── Portail public d'admission ─────────────────────────────────────────
    TYPE_CANDIDATURE_PENDING   = 'CANDIDATURE_PENDING'
    TYPE_CANDIDATURE_VALIDATED = 'CANDIDATURE_VALIDATED'
    TYPE_CANDIDATURE_REJECTED  = 'CANDIDATURE_REJECTED'
    TYPE_READY_FOR_PAYMENT     = 'READY_FOR_PAYMENT'
    TYPE_PAYMENT_PROOF_PENDING   = 'PAYMENT_PROOF_PENDING'
    TYPE_PAYMENT_PROOF_REJECTED  = 'PAYMENT_PROOF_REJECTED'
    # ── RH ──────────────────────────────────────────────────────────────
    TYPE_HR_LEAVE        = 'HR_LEAVE'
    TYPE_HR_DISCIPLINE   = 'HR_DISCIPLINE'
    TYPE_HR_EVALUATION   = 'HR_EVALUATION'
    TYPE_HR_MISSION      = 'HR_MISSION'
    TYPE_HR_INTERIM      = 'HR_INTERIM'
    TYPE_HR_HANDOVER     = 'HR_HANDOVER'
    TYPE_HR_INTERNSHIP   = 'HR_INTERNSHIP'
    TYPE_HR_ONBOARDING   = 'HR_ONBOARDING'
    TYPE_HR_RECRUITMENT  = 'HR_RECRUITMENT'
    TYPE_HR_DOCUMENT     = 'HR_DOCUMENT'
    TYPE_CHOICES = [
        (TYPE_NEW_GRADE, _('Nouvelle note')),
        (TYPE_ABSENCE, _('Absence enregistrée')),
        (TYPE_COURSE_CANCELLED, _('Cours annulé/reporté')),
        (TYPE_TIMETABLE_CHANGE, _('Modification emploi du temps')),
        (TYPE_SHEET_VALIDATED, _('Émargement validé')),
        (TYPE_EVAL_DEVOIR, _('Programmer un devoir')),
        (TYPE_EVAL_EXAMEN, _('Programmer un examen')),
        (TYPE_VOLUME_COMPLETE, _('Volume horaire atteint')),
        (TYPE_EXTRA_REQUEST, _('Demande séances supplémentaires')),
        (TYPE_EXTRA_APPROVED, _('Demande approuvée')),
        (TYPE_EXTRA_REJECTED, _('Demande rejetée')),
        (TYPE_GENERAL, _('Notification générale')),
        (TYPE_COURSE_SUPPORT, _('Support de cours partagé')),
        (TYPE_INSCRIPTION_PENDING,   _('Demande d\'inscription en attente')),
        (TYPE_INSCRIPTION_VALIDATED, _('Inscription validée')),
        (TYPE_INSCRIPTION_REJECTED,  _('Inscription rejetée')),
        (TYPE_CANDIDATURE_PENDING,   _('Candidature en attente')),
        (TYPE_CANDIDATURE_VALIDATED, _('Candidature validée')),
        (TYPE_CANDIDATURE_REJECTED,  _('Candidature rejetée')),
        (TYPE_READY_FOR_PAYMENT,     _('Frais fixés — paiement attendu')),
        (TYPE_PAYMENT_PROOF_PENDING, _('Preuve de paiement en attente')),
        (TYPE_PAYMENT_PROOF_REJECTED, _('Preuve de paiement rejetée')),
        (TYPE_HR_LEAVE,       _('Congé — décision')),
        (TYPE_HR_DISCIPLINE,  _('Dossier disciplinaire')),
        (TYPE_HR_EVALUATION,  _('Évaluation')),
        (TYPE_HR_MISSION,     _('Mission')),
        (TYPE_HR_INTERIM,     _('Intérim')),
        (TYPE_HR_HANDOVER,    _('Passation de service')),
        (TYPE_HR_INTERNSHIP,  _('Stage')),
        (TYPE_HR_ONBOARDING,  _('Intégration')),
        (TYPE_HR_RECRUITMENT, _('Recrutement')),
        (TYPE_HR_DOCUMENT,    _('Document RH')),
    ]

    PRIORITY_LOW = 'LOW'
    PRIORITY_MEDIUM = 'MEDIUM'
    PRIORITY_HIGH = 'HIGH'
    PRIORITY_CHOICES = [
        (PRIORITY_LOW, _('Faible')),
        (PRIORITY_MEDIUM, _('Moyenne')),
        (PRIORITY_HIGH, _('Haute')),
    ]

    recipient = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='notifications'
    )
    notification_type = models.CharField(max_length=25, choices=TYPE_CHOICES)
    title = models.CharField(max_length=200)
    message = models.TextField()
    priority = models.CharField(
        max_length=10, choices=PRIORITY_CHOICES, default=PRIORITY_MEDIUM
    )
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    link = models.CharField(max_length=500, blank=True, help_text=_('URL interne liée'))
    email_sent = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'notifications'
        verbose_name = _('Notification')
        verbose_name_plural = _('Notifications')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', 'is_read']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"{self.recipient} | {self.title} | {'Lu' if self.is_read else 'Non lu'}"
