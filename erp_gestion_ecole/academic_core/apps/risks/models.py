"""
Risques — Pilotage et Suivi Budgétaire.

Module standalone (aucun couplage avec le budget) : cartographie des risques
avec matrice gravité x probabilité, lien optionnel générique vers un élément
du Plan Stratégique de Développement (jamais vers le budget).

Miroir de apps/risks/models.py du projet de référence appSuiviBudgetaire.
"""
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.translation import gettext_lazy as _


class Risque(models.Model):
    CATEGORIE_FINANCIER = 'financier'
    CATEGORIE_OPERATIONNEL = 'operationnel'
    CATEGORIE_REPUTATIONNEL = 'reputationnel'
    CATEGORIE_CONFORMITE = 'conformite'
    CATEGORIE_STRATEGIQUE = 'strategique'
    CATEGORIE_CHOICES = [
        (CATEGORIE_FINANCIER, _('Financier')),
        (CATEGORIE_OPERATIONNEL, _('Opérationnel')),
        (CATEGORIE_REPUTATIONNEL, _('Réputationnel')),
        (CATEGORIE_CONFORMITE, _('Conformité')),
        (CATEGORIE_STRATEGIQUE, _('Stratégique')),
    ]

    STATUT_IDENTIFIE = 'identifie'
    STATUT_EN_TRAITEMENT = 'en_traitement'
    STATUT_MAITRISE = 'maitrise'
    STATUT_CLOS = 'clos'
    STATUT_CHOICES = [
        (STATUT_IDENTIFIE, _('Identifié')),
        (STATUT_EN_TRAITEMENT, _('En traitement')),
        (STATUT_MAITRISE, _('Maîtrisé')),
        (STATUT_CLOS, _('Clos')),
    ]

    code = models.SlugField(max_length=30, unique=True, verbose_name=_('Code'))
    libelle = models.CharField(max_length=250, verbose_name=_('Libellé'))
    description = models.TextField(blank=True, verbose_name=_('Description'))
    categorie = models.CharField(max_length=20, choices=CATEGORIE_CHOICES, verbose_name=_('Catégorie'))
    gravite = models.PositiveSmallIntegerField(verbose_name=_('Gravité (1-5)'))
    probabilite = models.PositiveSmallIntegerField(verbose_name=_('Probabilité (1-5)'))
    responsable = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='risques', db_constraint=False, verbose_name=_('Responsable'),
    )
    plan_mitigation = models.TextField(blank=True, verbose_name=_('Plan de mitigation'))
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default=STATUT_IDENTIFIE, verbose_name=_('Statut'))
    date_identification = models.DateField(verbose_name=_("Date d'identification"))

    content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False)
    object_id = models.PositiveIntegerField(null=True, blank=True)
    objet_lie = GenericForeignKey('content_type', 'object_id')

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'risks_risques'
        verbose_name = _('Risque')
        verbose_name_plural = _('Risques')
        ordering = ['-gravite', '-probabilite']
        indexes = [models.Index(fields=['content_type', 'object_id'])]

    def __str__(self):
        return f"{self.code} — {self.libelle}"

    @property
    def score(self):
        return self.gravite * self.probabilite

    @property
    def niveau(self):
        s = self.score
        if s >= 16:
            return 'critique'
        if s >= 10:
            return 'eleve'
        if s >= 5:
            return 'modere'
        return 'faible'


class SuiviRisque(models.Model):
    risque = models.ForeignKey(Risque, on_delete=models.CASCADE, related_name='suivis', verbose_name=_('Risque'))
    date_suivi = models.DateField(verbose_name=_('Date de suivi'))
    commentaire = models.TextField(blank=True, verbose_name=_('Commentaire'))
    nouveau_statut = models.CharField(max_length=20, choices=Risque.STATUT_CHOICES, blank=True, verbose_name=_('Nouveau statut'))
    suivi_par = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='suivis_risques', db_constraint=False, verbose_name=_('Suivi par'),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'risks_suivis'
        verbose_name = _('Suivi de risque')
        verbose_name_plural = _('Suivis de risque')
        ordering = ['-date_suivi']

    def __str__(self):
        return f"{self.risque.code} — {self.date_suivi}"
