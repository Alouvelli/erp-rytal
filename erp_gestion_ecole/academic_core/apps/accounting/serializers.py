from rest_framework import serializers
from .models import CaisseMovement, DemandeDepense, LigneBudgetaire


class CaisseMovementSerializer(serializers.ModelSerializer):
    movement_type_display = serializers.CharField(source='get_movement_type_display', read_only=True)
    categorie_display     = serializers.CharField(source='get_categorie_display', read_only=True)
    direction_name        = serializers.CharField(source='direction.name', read_only=True, default=None)

    class Meta:
        model  = CaisseMovement
        fields = [
            'id', 'movement_type', 'movement_type_display', 'amount', 'movement_date',
            'motif', 'beneficiaire', 'direction', 'direction_name',
            'categorie', 'categorie_display', 'is_executed', 'executed_at', 'created_at',
        ]


class DemandeDepenseSerializer(serializers.ModelSerializer):
    direction_name = serializers.CharField(source='direction.name', read_only=True)
    statut_display = serializers.CharField(source='get_statut_display', read_only=True)

    class Meta:
        model  = DemandeDepense
        fields = [
            'id', 'reference', 'direction', 'direction_name', 'objet', 'categorie',
            'montant', 'fournisseur', 'beneficiaire', 'statut', 'statut_display',
            'requested_at', 'validated_at', 'decaisse_at', 'ligne_budgetaire',
        ]


class LigneBudgetaireSerializer(serializers.ModelSerializer):
    direction_name        = serializers.CharField(source='direction.name', read_only=True)
    compte_comptable_name = serializers.CharField(source='compte_comptable.libelle', read_only=True, default=None)
    academic_year_label    = serializers.CharField(source='academic_year.label', read_only=True)
    montant_disponible     = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    taux_execution          = serializers.DecimalField(max_digits=6, decimal_places=4, read_only=True)

    class Meta:
        model  = LigneBudgetaire
        fields = [
            'id', 'academic_year', 'academic_year_label', 'direction', 'direction_name',
            'compte_comptable', 'compte_comptable_name', 'nature',
            'montant_initial', 'montant_revise', 'montant_engage', 'montant_execute',
            'montant_disponible', 'taux_execution',
        ]
