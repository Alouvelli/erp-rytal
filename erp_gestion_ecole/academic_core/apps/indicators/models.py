"""
Indicateurs KPI — Pilotage et Suivi Budgétaire.

Indicateur peut s'attacher à n'importe quel objet du plan stratégique (Axe,
Objectif, Programme, Projet) via une GenericForeignKey — seule exception au
principe "pas de FK générique" du reste du projet, car c'est ainsi que la
référence (apps/indicators) rattache un KPI à un élément du PSD et alimente
le Balanced Scorecard.

Miroir de apps/indicators/models.py du projet de référence appSuiviBudgetaire.
"""
from decimal import Decimal

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.translation import gettext_lazy as _


class Indicateur(models.Model):
    PERIODICITE_MENSUELLE = 'mensuelle'
    PERIODICITE_TRIMESTRIELLE = 'trimestrielle'
    PERIODICITE_SEMESTRIELLE = 'semestrielle'
    PERIODICITE_ANNUELLE = 'annuelle'
    PERIODICITE_CHOICES = [
        (PERIODICITE_MENSUELLE, _('Mensuelle')),
        (PERIODICITE_TRIMESTRIELLE, _('Trimestrielle')),
        (PERIODICITE_SEMESTRIELLE, _('Semestrielle')),
        (PERIODICITE_ANNUELLE, _('Annuelle')),
    ]

    SENS_HAUSSE_SOUHAITEE = 'hausse_souhaitee'
    SENS_BAISSE_SOUHAITEE = 'baisse_souhaitee'
    SENS_CHOICES = [
        (SENS_HAUSSE_SOUHAITEE, _('Hausse souhaitée')),
        (SENS_BAISSE_SOUHAITEE, _('Baisse souhaitée')),
    ]

    code = models.SlugField(max_length=50, unique=True, verbose_name=_('Code'))
    libelle = models.CharField(max_length=250, verbose_name=_('Libellé'))
    formule = models.TextField(blank=True, verbose_name=_('Formule de calcul'))
    source = models.CharField(max_length=255, blank=True, verbose_name=_('Source de la donnée'))
    responsable = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='indicateurs', db_constraint=False, verbose_name=_('Responsable'),
    )
    periodicite = models.CharField(max_length=20, choices=PERIODICITE_CHOICES, default=PERIODICITE_TRIMESTRIELLE, verbose_name=_('Périodicité'))
    unite = models.CharField(max_length=30, blank=True, verbose_name=_('Unité'), help_text=_('Ex : %, FCFA, nombre.'))
    sens_amelioration = models.CharField(max_length=20, choices=SENS_CHOICES, default=SENS_HAUSSE_SOUHAITEE, verbose_name=_("Sens d'amélioration"))
    valeur_cible = models.DecimalField(max_digits=16, decimal_places=2, verbose_name=_('Valeur cible'))
    valeur_actuelle = models.DecimalField(
        max_digits=16, decimal_places=2, default=0, editable=False, verbose_name=_('Valeur actuelle'),
        help_text=_('Recalculée automatiquement depuis la dernière mesure.'),
    )
    seuil_orange = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal('0.80'), verbose_name=_('Seuil orange (taux de réalisation)'))
    seuil_rouge = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal('0.60'), verbose_name=_('Seuil rouge (taux de réalisation)'))

    content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False)
    object_id = models.PositiveIntegerField(null=True, blank=True)
    objet_lie = GenericForeignKey('content_type', 'object_id')

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'kpi_indicateurs'
        verbose_name = _('Indicateur')
        verbose_name_plural = _('Indicateurs')
        ordering = ['code']
        indexes = [models.Index(fields=['content_type', 'object_id'])]

    def __str__(self):
        return f"{self.code} — {self.libelle}"

    @property
    def taux_realisation(self):
        """Ratio de réalisation indépendant du sens (hausse/baisse souhaitée)."""
        if self.sens_amelioration == self.SENS_BAISSE_SOUHAITEE:
            if not self.valeur_actuelle:
                return Decimal('2')
            return min(self.valeur_cible / self.valeur_actuelle, Decimal('2'))
        if not self.valeur_cible:
            return Decimal('0')
        return self.valeur_actuelle / self.valeur_cible

    @property
    def etat(self):
        """'vert' / 'orange' / 'rouge' selon le taux de réalisation et les seuils."""
        taux = self.taux_realisation
        if taux < self.seuil_rouge:
            return 'rouge'
        if taux < self.seuil_orange:
            return 'orange'
        return 'vert'


class ValeurIndicateur(models.Model):
    """Historique des mesures d'un indicateur."""
    indicateur = models.ForeignKey(Indicateur, on_delete=models.CASCADE, related_name='historique', verbose_name=_('Indicateur'))
    date_mesure = models.DateField(verbose_name=_('Date de mesure'))
    valeur = models.DecimalField(max_digits=16, decimal_places=2, verbose_name=_('Valeur mesurée'))
    commentaire = models.TextField(blank=True, verbose_name=_('Commentaire'))
    saisi_par = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='mesures_indicateurs', db_constraint=False, verbose_name=_('Saisi par'),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'kpi_valeurs'
        verbose_name = _('Valeur mesurée')
        verbose_name_plural = _('Valeurs mesurées')
        ordering = ['-date_mesure']

    def __str__(self):
        return f"{self.indicateur.code} — {self.date_mesure} : {self.valeur}"
