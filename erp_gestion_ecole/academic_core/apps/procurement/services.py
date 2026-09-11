"""
Logique métier Achats — vérification de la disponibilité budgétaire à la
validation d'une demande d'achat, et génération d'une DemandeDepense déjà
décaissée à l'exécution d'un paiement (réutilise
accounting.budget_services.recompute_montant_execute plutôt que dupliquer le
calcul de montant_execute).
"""
from django.db import transaction
from django.utils import timezone

from academic_core.apps.accounting.budget_services import (
    BudgetInsuffisantError,
    TransitionWorkflowInvalideError,
    recompute_montant_execute,
    _notify,
)

from .models import DemandeAchat, PaiementAchat


class DemandeAchatService:
    TRANSITIONS = {
        DemandeAchat.STATUT_BROUILLON: {DemandeAchat.STATUT_SOUMISE, DemandeAchat.STATUT_ANNULEE},
        DemandeAchat.STATUT_SOUMISE: {DemandeAchat.STATUT_VALIDEE, DemandeAchat.STATUT_REJETEE, DemandeAchat.STATUT_ANNULEE},
        DemandeAchat.STATUT_VALIDEE: {DemandeAchat.STATUT_ANNULEE},
        DemandeAchat.STATUT_REJETEE: set(),
        DemandeAchat.STATUT_ANNULEE: set(),
    }

    @classmethod
    def _check_transition(cls, demande, cible):
        autorises = cls.TRANSITIONS.get(demande.statut, set())
        if cible not in autorises:
            raise TransitionWorkflowInvalideError(
                f"Transition {demande.statut} → {cible} non autorisée pour la demande {demande.reference}."
            )

    @classmethod
    @transaction.atomic
    def soumettre(cls, demande, user):
        cls._check_transition(demande, DemandeAchat.STATUT_SOUMISE)
        demande.statut = DemandeAchat.STATUT_SOUMISE
        demande.save(update_fields=['statut'])
        return demande

    @classmethod
    @transaction.atomic
    def valider(cls, demande, user):
        cls._check_transition(demande, DemandeAchat.STATUT_VALIDEE)
        if demande.ligne_budgetaire and demande.montant_estime > demande.ligne_budgetaire.montant_disponible:
            raise BudgetInsuffisantError(
                f"Montant estimé ({demande.montant_estime}) supérieur au montant disponible "
                f"({demande.ligne_budgetaire.montant_disponible}) sur la ligne « {demande.ligne_budgetaire} »."
            )
        demande.statut = DemandeAchat.STATUT_VALIDEE
        demande.valide_par = user
        demande.date_validation = timezone.now()
        demande.save(update_fields=['statut', 'valide_par', 'date_validation'])
        _notify(
            demande.demandeur, f"Demande d'achat {demande.reference} validée",
            f"Votre demande d'achat « {demande.objet} » ({demande.montant_estime} FCFA) a été validée.",
            link='/achats/demandes/',
        )
        return demande

    @classmethod
    @transaction.atomic
    def rejeter(cls, demande, user, reason=''):
        cls._check_transition(demande, DemandeAchat.STATUT_REJETEE)
        demande.statut = DemandeAchat.STATUT_REJETEE
        demande.valide_par = user
        demande.date_validation = timezone.now()
        demande.rejection_reason = reason
        demande.save(update_fields=['statut', 'valide_par', 'date_validation', 'rejection_reason'])
        _notify(
            demande.demandeur, f"Demande d'achat {demande.reference} rejetée",
            f"Votre demande d'achat « {demande.objet} » a été rejetée. Motif : {reason or 'non précisé'}.",
            link='/achats/demandes/',
        )
        return demande

    @classmethod
    @transaction.atomic
    def annuler(cls, demande, user):
        cls._check_transition(demande, DemandeAchat.STATUT_ANNULEE)
        demande.statut = DemandeAchat.STATUT_ANNULEE
        demande.save(update_fields=['statut'])
        return demande


class PaiementService:
    @classmethod
    @transaction.atomic
    def effectuer(cls, paiement, user):
        if paiement.statut != PaiementAchat.STATUT_PLANIFIE:
            raise TransitionWorkflowInvalideError(
                f"Seul un paiement « Planifié » peut être effectué (statut actuel : {paiement.statut})."
            )
        from academic_core.apps.accounting.models import DemandeDepense

        demande_achat = paiement.facture.commande.demande_achat
        ligne = demande_achat.ligne_budgetaire

        demande_depense = DemandeDepense.objects.create(
            direction=demande_achat.centre_cout,
            objet=f"Achat — {paiement.facture.commande.reference} — {paiement.facture.numero_facture}",
            motif=f"Paiement fournisseur {paiement.facture.commande.fournisseur} (facture {paiement.facture.numero_facture})",
            montant=paiement.montant,
            statut=DemandeDepense.STATUT_DECAISSEE,
            requested_by=demande_achat.demandeur,
            validated_by=user,
            validated_at=timezone.now(),
            decaisse_by=user,
            decaisse_at=timezone.now(),
            ligne_budgetaire=ligne,
        )
        if ligne:
            recompute_montant_execute(ligne)

        paiement.statut = PaiementAchat.STATUT_EFFECTUE
        paiement.demande_depense_generee = demande_depense
        paiement.save(update_fields=['statut', 'demande_depense_generee'])

        paiement.facture.statut = paiement.facture.STATUT_PAYEE
        paiement.facture.save(update_fields=['statut'])
        _notify(
            demande_achat.demandeur, f"Facture {paiement.facture.numero_facture} payée",
            f"Le paiement de {paiement.montant} FCFA pour votre demande d'achat « {demande_achat.objet} » a été effectué.",
            link='/achats/factures/',
        )
        return paiement

    @classmethod
    @transaction.atomic
    def annuler(cls, paiement, user):
        if paiement.statut != PaiementAchat.STATUT_EFFECTUE:
            raise TransitionWorkflowInvalideError(
                f"Seul un paiement « Effectué » peut être annulé (statut actuel : {paiement.statut})."
            )
        demande_depense = paiement.demande_depense_generee
        ligne = demande_depense.ligne_budgetaire if demande_depense else None

        if demande_depense:
            demande_depense.delete()
        paiement.statut = PaiementAchat.STATUT_ANNULE
        paiement.demande_depense_generee = None
        paiement.save(update_fields=['statut', 'demande_depense_generee'])

        if ligne:
            recompute_montant_execute(ligne)
        return paiement
