from django.db import models
from django.utils.translation import gettext_lazy as _


class Building(models.Model):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    faculty = models.ForeignKey(
        'academic_structure.Faculty',
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='buildings', verbose_name=_('Institut'),
    )

    class Meta:
        db_table = 'buildings'
        verbose_name = _('Bâtiment')
        verbose_name_plural = _('Bâtiments')

    def __str__(self):
        return f"{self.code} - {self.name}"


class Room(models.Model):
    TYPE_AMPHITHEATER = 'AMPHI'
    TYPE_CLASSROOM = 'SALLE'
    TYPE_LAB = 'LABO'
    TYPE_TD = 'TD'
    TYPE_CHOICES = [
        (TYPE_AMPHITHEATER, _('Amphithéâtre')),
        (TYPE_CLASSROOM, _('Salle de cours')),
        (TYPE_LAB, _('Laboratoire')),
        (TYPE_TD, _('Salle de TD')),
    ]

    code = models.CharField(max_length=20, unique=True, verbose_name=_('Code'))
    name = models.CharField(max_length=100, verbose_name=_('Nom'))
    building = models.ForeignKey(
        Building, on_delete=models.CASCADE, related_name='rooms',
        verbose_name=_('Bâtiment')
    )
    room_type = models.CharField(
        max_length=10, choices=TYPE_CHOICES, default=TYPE_CLASSROOM,
        verbose_name=_('Type')
    )
    capacity = models.PositiveSmallIntegerField(verbose_name=_('Capacité'))
    has_projector = models.BooleanField(default=False, verbose_name=_('Projecteur'))
    has_ac = models.BooleanField(default=False, verbose_name=_('Climatisation'))
    is_available = models.BooleanField(default=True, verbose_name=_('Disponible'))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'rooms'
        verbose_name = _('Salle')
        verbose_name_plural = _('Salles')
        ordering = ['building', 'code']

    def __str__(self):
        return f"{self.code} - {self.name} ({self.capacity} places)"
