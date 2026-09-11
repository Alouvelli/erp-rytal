"""
Qualité — Pilotage et Suivi Budgétaire.

Module standalone (aucun couplage avec le budget) : auto-évaluation par
référentiel qualité (CAMES / ANAQ-Sup) et plans d'amélioration associés.

Miroir de apps/quality/models.py du projet de référence appSuiviBudgetaire.
"""
from django.db import models
from django.utils.translation import gettext_lazy as _


class CritereQualite(models.Model):
    REFERENTIEL_CAMES = 'cames'
    REFERENTIEL_ANAQ_SUP = 'anaq_sup'
    REFERENTIEL_CHOICES = [
        (REFERENTIEL_CAMES, _('CAMES')),
        (REFERENTIEL_ANAQ_SUP, _('ANAQ-Sup')),
    ]

    referentiel = models.CharField(max_length=20, choices=REFERENTIEL_CHOICES, verbose_name=_('Référentiel'))
    code = models.CharField(max_length=20, verbose_name=_('Code'))
    libelle = models.CharField(max_length=250, verbose_name=_('Libellé'))
    categorie = models.CharField(max_length=100, blank=True, verbose_name=_('Catégorie'))
    description = models.TextField(blank=True, verbose_name=_('Description'))
    ponderation = models.PositiveSmallIntegerField(default=1, verbose_name=_('Pondération'))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'quality_criteres'
        verbose_name = _('Critère qualité')
        verbose_name_plural = _('Critères qualité')
        ordering = ['referentiel', 'code']
        unique_together = ('referentiel', 'code')

    def __str__(self):
        return f"[{self.get_referentiel_display()}] {self.code} — {self.libelle}"


class AutoEvaluation(models.Model):
    critere = models.ForeignKey(CritereQualite, on_delete=models.CASCADE, related_name='auto_evaluations', verbose_name=_('Critère'))
    campagne = models.CharField(max_length=50, verbose_name=_('Campagne'), help_text=_("Ex : 2025-2026"))
    note = models.DecimalField(max_digits=4, decimal_places=2, verbose_name=_('Note'))
    note_max = models.DecimalField(max_digits=4, decimal_places=2, default=4, verbose_name=_('Note maximale'))
    commentaire = models.TextField(blank=True, verbose_name=_('Commentaire'))
    evalue_par = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='auto_evaluations_qualite', db_constraint=False, verbose_name=_('Évalué par'),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'quality_auto_evaluations'
        verbose_name = _('Auto-évaluation')
        verbose_name_plural = _('Auto-évaluations')
        ordering = ['-campagne', 'critere__code']
        unique_together = ('critere', 'campagne')

    def __str__(self):
        return f"{self.critere.code} ({self.campagne}) : {self.note}/{self.note_max}"

    @property
    def taux_reussite(self):
        if not self.note_max:
            return 0
        return self.note / self.note_max

    @property
    def etat(self):
        taux = self.taux_reussite
        if taux < 0.5:
            return 'rouge'
        if taux < 0.75:
            return 'orange'
        return 'vert'


class PlanAmelioration(models.Model):
    STATUT_PLANIFIEE = 'planifiee'
    STATUT_EN_COURS = 'en_cours'
    STATUT_REALISEE = 'realisee'
    STATUT_RETARDEE = 'retardee'
    STATUT_CHOICES = [
        (STATUT_PLANIFIEE, _('Planifiée')),
        (STATUT_EN_COURS, _('En cours')),
        (STATUT_REALISEE, _('Réalisée')),
        (STATUT_RETARDEE, _('Retardée')),
    ]

    critere = models.ForeignKey(CritereQualite, on_delete=models.CASCADE, related_name='plans_amelioration', verbose_name=_('Critère'))
    action = models.CharField(max_length=255, verbose_name=_('Action'))
    description = models.TextField(blank=True, verbose_name=_('Description'))
    responsable = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='plans_amelioration_qualite', db_constraint=False, verbose_name=_('Responsable'),
    )
    date_echeance = models.DateField(null=True, blank=True, verbose_name=_("Date d'échéance"))
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default=STATUT_PLANIFIEE, verbose_name=_('Statut'))
    taux_avancement = models.PositiveSmallIntegerField(default=0, verbose_name=_("Taux d'avancement (%)"))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'quality_plans_amelioration'
        verbose_name = _("Plan d'amélioration")
        verbose_name_plural = _("Plans d'amélioration")
        ordering = ['date_echeance']

    def __str__(self):
        return f"{self.action} ({self.critere.code})"
