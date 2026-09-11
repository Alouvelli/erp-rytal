from django.db import models
from django.utils.translation import gettext_lazy as _


class CommunityServiceActivity(models.Model):
    """Activité du Service à la Communauté — permet au responsable de ce
    service de consigner les actions menées (sensibilisation, formations,
    dons, partenariats, bénévolat…) et d'en tirer un rapport d'activités
    (voir community_service/report_views.py)."""

    CAT_SENSIBILISATION = 'SENSIBILISATION'
    CAT_FORMATION        = 'FORMATION'
    CAT_SOLIDARITE        = 'SOLIDARITE'
    CAT_PARTENARIAT       = 'PARTENARIAT'
    CAT_BENEVOLAT         = 'BENEVOLAT'
    CAT_AUTRE             = 'AUTRE'
    CATEGORIE_CHOICES = [
        (CAT_SENSIBILISATION, _('Sensibilisation')),
        (CAT_FORMATION,        _('Formation / Atelier')),
        (CAT_SOLIDARITE,        _('Don / Solidarité')),
        (CAT_PARTENARIAT,       _('Partenariat communautaire')),
        (CAT_BENEVOLAT,         _('Bénévolat')),
        (CAT_AUTRE,             _('Autre')),
    ]

    STATUT_PLANIFIEE = 'PLANIFIEE'
    STATUT_REALISEE  = 'REALISEE'
    STATUT_ANNULEE   = 'ANNULEE'
    STATUT_CHOICES = [
        (STATUT_PLANIFIEE, _('Planifiée')),
        (STATUT_REALISEE,  _('Réalisée')),
        (STATUT_ANNULEE,   _('Annulée')),
    ]

    titre          = models.CharField(max_length=200, verbose_name=_('Titre'))
    categorie      = models.CharField(
        max_length=20, choices=CATEGORIE_CHOICES, default=CAT_AUTRE,
        verbose_name=_('Catégorie'),
    )
    description    = models.TextField(blank=True, verbose_name=_('Description'))
    date_debut     = models.DateField(verbose_name=_('Date de début'))
    date_fin       = models.DateField(null=True, blank=True, verbose_name=_('Date de fin'))
    lieu           = models.CharField(max_length=200, blank=True, verbose_name=_('Lieu'))
    beneficiaires  = models.CharField(max_length=255, blank=True, verbose_name=_('Bénéficiaires'))
    nombre_participants = models.PositiveIntegerField(
        null=True, blank=True, verbose_name=_('Nombre de participants'),
    )
    partenaires    = models.CharField(max_length=255, blank=True, verbose_name=_('Partenaires associés'))
    statut         = models.CharField(
        max_length=15, choices=STATUT_CHOICES, default=STATUT_PLANIFIEE,
        verbose_name=_('Statut'),
    )
    resultats      = models.TextField(blank=True, verbose_name=_('Résultats / Bilan'))
    responsable    = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='activites_communautaires', verbose_name=_('Responsable de l\'activité'),
    )
    created_by     = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='activites_communautaires_creees', db_constraint=False,
        verbose_name=_('Créé par'),
    )
    created_at     = models.DateTimeField(auto_now_add=True)
    updated_at     = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'community_service_activity'
        verbose_name = _('Activité de service à la communauté')
        verbose_name_plural = _('Activités de service à la communauté')
        ordering = ['-date_debut']
        indexes = [
            models.Index(fields=['-date_debut']),
            models.Index(fields=['categorie']),
            models.Index(fields=['statut']),
        ]

    def __str__(self):
        return f"{self.titre} ({self.date_debut})"

    @property
    def statut_color(self):
        return {
            self.STATUT_PLANIFIEE: 'warning',
            self.STATUT_REALISEE:  'success',
            self.STATUT_ANNULEE:   'secondary',
        }.get(self.statut, 'secondary')
