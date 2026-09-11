"""
Logique métier du Pilotage et Suivi Budgétaire — machine à états des
engagements budgétaires (réservation/libération de montant_engage sur la
ligne) et workflow de validation des budgets rectificatifs.

Miroir de apps/budget/services.py du projet de référence appSuiviBudgetaire,
adapté aux modèles de ce projet (LigneBudgetaire.montant_engage/montant_revise
au lieu d'un module DRF séparé).
"""
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import BudgetRectificatif, DemandeDepense, EngagementBudgetaire


class TransitionWorkflowInvalideError(Exception):
    """Transition d'état non autorisée pour un engagement ou un rectificatif."""


class BudgetInsuffisantError(Exception):
    """Le montant de l'engagement dépasse le montant disponible de la ligne."""


def _notify(recipient, title, message, link=''):
    """Notification best-effort — n'échoue jamais le workflow appelant."""
    if not recipient:
        return
    try:
        from academic_core.apps.notifications.utils import notify_users
        from academic_core.apps.notifications.models import Notification
        notify_users([recipient], Notification.TYPE_GENERAL, title, message, link=link)
    except Exception:
        pass


def recompute_montant_execute(ligne_budgetaire):
    """
    Recalcule LigneBudgetaire.montant_execute à partir des DemandeDepense
    décaissées qui lui sont rattachées. Appelé explicitement (pas de signal,
    conforme à la convention du reste de l'app) depuis
    accounting.views.demande_depense_decaisser juste après le décaissement.
    """
    if ligne_budgetaire is None:
        return
    total = DemandeDepense.objects.filter(
        ligne_budgetaire=ligne_budgetaire, statut=DemandeDepense.STATUT_DECAISSEE,
    ).aggregate(total=Sum('montant'))['total'] or 0
    ligne_budgetaire.montant_execute = total
    ligne_budgetaire.save(update_fields=['montant_execute'])


class EngagementService:
    TRANSITIONS = {
        EngagementBudgetaire.STATUT_BROUILLON: {EngagementBudgetaire.STATUT_SOUMIS, EngagementBudgetaire.STATUT_ANNULE},
        EngagementBudgetaire.STATUT_SOUMIS:    {EngagementBudgetaire.STATUT_VALIDE, EngagementBudgetaire.STATUT_REJETE, EngagementBudgetaire.STATUT_ANNULE},
        EngagementBudgetaire.STATUT_VALIDE:    {EngagementBudgetaire.STATUT_ANNULE},
        EngagementBudgetaire.STATUT_REJETE:    set(),
        EngagementBudgetaire.STATUT_ANNULE:    set(),
    }

    @classmethod
    def _check_transition(cls, engagement, cible):
        autorises = cls.TRANSITIONS.get(engagement.statut, set())
        if cible not in autorises:
            raise TransitionWorkflowInvalideError(
                f"Transition {engagement.statut} → {cible} non autorisée pour l'engagement {engagement.reference}."
            )

    @classmethod
    @transaction.atomic
    def soumettre(cls, engagement, user):
        cls._check_transition(engagement, EngagementBudgetaire.STATUT_SOUMIS)
        engagement.statut = EngagementBudgetaire.STATUT_SOUMIS
        engagement.save(update_fields=['statut'])
        return engagement

    @classmethod
    @transaction.atomic
    def valider(cls, engagement, user):
        cls._check_transition(engagement, EngagementBudgetaire.STATUT_VALIDE)
        ligne = engagement.ligne_budgetaire
        if engagement.montant > ligne.montant_disponible:
            raise BudgetInsuffisantError(
                f"Montant demandé ({engagement.montant}) supérieur au montant disponible "
                f"({ligne.montant_disponible}) sur la ligne « {ligne} »."
            )
        engagement.statut = EngagementBudgetaire.STATUT_VALIDE
        engagement.valide_par = user
        engagement.date_validation = timezone.now()
        engagement.save(update_fields=['statut', 'valide_par', 'date_validation'])

        ligne.montant_engage = ligne.montant_engage + engagement.montant
        ligne.save(update_fields=['montant_engage'])
        _notify(
            engagement.demandeur, f"Engagement {engagement.reference} validé",
            f"Votre engagement budgétaire « {engagement.objet} » ({engagement.montant} FCFA) a été validé.",
            link='/accounting/budget/engagements/',
        )
        return engagement

    @classmethod
    @transaction.atomic
    def rejeter(cls, engagement, user, reason=''):
        cls._check_transition(engagement, EngagementBudgetaire.STATUT_REJETE)
        engagement.statut = EngagementBudgetaire.STATUT_REJETE
        engagement.valide_par = user
        engagement.date_validation = timezone.now()
        engagement.rejection_reason = reason
        engagement.save(update_fields=['statut', 'valide_par', 'date_validation', 'rejection_reason'])
        _notify(
            engagement.demandeur, f"Engagement {engagement.reference} rejeté",
            f"Votre engagement budgétaire « {engagement.objet} » a été rejeté. Motif : {reason or 'non précisé'}.",
            link='/accounting/budget/engagements/',
        )
        return engagement

    @classmethod
    @transaction.atomic
    def annuler(cls, engagement, user):
        cls._check_transition(engagement, EngagementBudgetaire.STATUT_ANNULE)
        etait_valide = engagement.statut == EngagementBudgetaire.STATUT_VALIDE
        engagement.statut = EngagementBudgetaire.STATUT_ANNULE
        engagement.save(update_fields=['statut'])

        if etait_valide:
            ligne = engagement.ligne_budgetaire
            ligne.montant_engage = ligne.montant_engage - engagement.montant
            ligne.save(update_fields=['montant_engage'])
        return engagement


class RectificatifService:
    @classmethod
    @transaction.atomic
    def valider(cls, rectificatif, user):
        if rectificatif.statut != BudgetRectificatif.STATUT_DEMANDE:
            raise TransitionWorkflowInvalideError(
                f"Seul un rectificatif « Demandé » peut être validé (statut actuel : {rectificatif.statut})."
            )
        ligne = rectificatif.ligne_budgetaire
        ligne.montant_revise = ligne.montant_revise + rectificatif.montant_ajustement
        ligne.save(update_fields=['montant_revise'])

        rectificatif.statut = BudgetRectificatif.STATUT_VALIDE
        rectificatif.valide_par = user
        rectificatif.date_validation = timezone.now()
        rectificatif.save(update_fields=['statut', 'valide_par', 'date_validation'])
        _notify(
            rectificatif.demande_par, "Rectificatif budgétaire validé",
            f"Votre demande de rectificatif ({rectificatif.montant_ajustement:+} FCFA) sur la ligne « {ligne} » a été validée.",
            link='/accounting/budget/rectificatifs/',
        )
        return rectificatif

    @classmethod
    @transaction.atomic
    def rejeter(cls, rectificatif, user, reason=''):
        if rectificatif.statut != BudgetRectificatif.STATUT_DEMANDE:
            raise TransitionWorkflowInvalideError(
                f"Seul un rectificatif « Demandé » peut être rejeté (statut actuel : {rectificatif.statut})."
            )
        rectificatif.statut = BudgetRectificatif.STATUT_REJETE
        rectificatif.valide_par = user
        rectificatif.date_validation = timezone.now()
        rectificatif.rejection_reason = reason
        rectificatif.save(update_fields=['statut', 'valide_par', 'date_validation', 'rejection_reason'])
        _notify(
            rectificatif.demande_par, "Rectificatif budgétaire rejeté",
            f"Votre demande de rectificatif sur la ligne « {rectificatif.ligne_budgetaire} » a été rejetée. "
            f"Motif : {reason or 'non précisé'}.",
            link='/accounting/budget/rectificatifs/',
        )
        return rectificatif
