from django.db import models
from django.utils.translation import gettext_lazy as _
from academic_core.apps.timetable.models import TimetableEntry
from academic_core.apps.accounts.models import User


class CourseCancellation(models.Model):
    TYPE_CANCELLATION = 'CANCEL'
    TYPE_POSTPONEMENT = 'POSTPONE'
    TYPE_CHOICES = [
        (TYPE_CANCELLATION, _('Annulation')),
        (TYPE_POSTPONEMENT, _('Report')),
    ]

    STATUS_PENDING = 'PENDING'
    STATUS_APPROVED = 'APPROVED'
    STATUS_REJECTED = 'REJECTED'
    STATUS_CHOICES = [
        (STATUS_PENDING, _('En attente')),
        (STATUS_APPROVED, _('Approuvé')),
        (STATUS_REJECTED, _('Rejeté')),
    ]

    timetable_entry = models.ForeignKey(
        TimetableEntry, on_delete=models.CASCADE, related_name='cancellations'
    )
    session_date = models.DateField(verbose_name=_('Date de la séance concernée'))
    request_type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    reason = models.TextField(verbose_name=_('Motif'))
    requested_by = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='cancellation_requests'
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING
    )
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reviewed_cancellations'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_comment = models.TextField(blank=True)
    # Pour les reports : nouvelle date/heure proposée
    rescheduled_date = models.DateField(null=True, blank=True, verbose_name=_('Nouvelle date'))
    rescheduled_start = models.TimeField(null=True, blank=True)
    rescheduled_end = models.TimeField(null=True, blank=True)
    rescheduled_room = models.ForeignKey(
        'rooms.Room', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='rescheduled_cancellations'
    )

    class Meta:
        db_table = 'course_cancellations'
        verbose_name = _('Annulation/Report de cours')
        verbose_name_plural = _('Annulations/Reports de cours')
        ordering = ['-requested_at']
        indexes = [
            models.Index(fields=['status', 'request_type']),
            models.Index(fields=['timetable_entry', 'session_date']),
        ]

    def __str__(self):
        return (
            f"{self.get_request_type_display()} | "
            f"{self.timetable_entry} | {self.session_date}"
        )
