from rest_framework import serializers
from .models import FichePersonnel, Contract, DemandeConge


class FichePersonnelSerializer(serializers.ModelSerializer):
    employee_name       = serializers.CharField(source='user.get_full_name', read_only=True)
    type_contrat_display = serializers.CharField(source='get_type_contrat_display', read_only=True)
    anciennete           = serializers.SerializerMethodField()

    class Meta:
        model  = FichePersonnel
        fields = [
            'id', 'user', 'employee_name', 'poste', 'type_contrat', 'type_contrat_display',
            'date_embauche', 'date_fin_contrat', 'anciennete', 'created_at',
        ]

    def get_anciennete(self, obj):
        return obj.anciennete()


class ContractSerializer(serializers.ModelSerializer):
    employee_name        = serializers.CharField(source='user.get_full_name', read_only=True)
    type_contrat_display = serializers.CharField(source='get_type_contrat_display', read_only=True)
    statut_display        = serializers.CharField(source='get_statut_display', read_only=True)

    class Meta:
        model  = Contract
        fields = [
            'id', 'user', 'employee_name', 'type_contrat', 'type_contrat_display',
            'date_debut', 'date_fin', 'salaire_brut', 'statut', 'statut_display',
            'signe_le', 'created_at',
        ]


class DemandeCongeSerializer(serializers.ModelSerializer):
    employee_name       = serializers.CharField(source='user.get_full_name', read_only=True)
    type_conge_display   = serializers.CharField(source='get_type_conge_display', read_only=True)
    statut_display        = serializers.CharField(source='get_statut_display', read_only=True)
    nombre_jours          = serializers.IntegerField(read_only=True)

    class Meta:
        model  = DemandeConge
        fields = [
            'id', 'user', 'employee_name', 'type_conge', 'type_conge_display',
            'date_debut', 'date_fin', 'nombre_jours', 'motif', 'statut', 'statut_display',
            'valide_le', 'created_at',
        ]
