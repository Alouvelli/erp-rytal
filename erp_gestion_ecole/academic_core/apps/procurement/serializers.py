from rest_framework import serializers
from .models import DemandeAchat, CommandeAchat, FactureAchat


class DemandeAchatSerializer(serializers.ModelSerializer):
    centre_cout_name = serializers.CharField(source='centre_cout.name', read_only=True)
    demandeur_name     = serializers.CharField(source='demandeur.get_full_name', read_only=True)
    statut_display      = serializers.CharField(source='get_statut_display', read_only=True)
    type_depense_display = serializers.CharField(source='get_type_depense_display', read_only=True)

    class Meta:
        model  = DemandeAchat
        fields = [
            'id', 'reference', 'objet', 'centre_cout', 'centre_cout_name',
            'type_depense', 'type_depense_display', 'demandeur', 'demandeur_name',
            'date_demande', 'montant_estime', 'statut', 'statut_display',
            'date_validation',
        ]


class CommandeAchatSerializer(serializers.ModelSerializer):
    fournisseur_name = serializers.CharField(source='fournisseur.nom', read_only=True)
    statut_display     = serializers.CharField(source='get_statut_display', read_only=True)

    class Meta:
        model  = CommandeAchat
        fields = [
            'id', 'reference', 'demande_achat', 'fournisseur', 'fournisseur_name',
            'montant', 'date_commande', 'date_livraison_prevue', 'statut', 'statut_display',
        ]


class FactureAchatSerializer(serializers.ModelSerializer):
    commande_reference = serializers.CharField(source='commande.reference', read_only=True)
    statut_display        = serializers.CharField(source='get_statut_display', read_only=True)

    class Meta:
        model  = FactureAchat
        fields = [
            'id', 'commande', 'commande_reference', 'numero_facture',
            'montant', 'statut', 'statut_display', 'created_at',
        ]
