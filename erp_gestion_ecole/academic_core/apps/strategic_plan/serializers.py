from rest_framework import serializers
from .models import Projet, PlanTravailAnnuel


class ProjetSerializer(serializers.ModelSerializer):
    programme_name  = serializers.CharField(source='programme.libelle', read_only=True)
    responsable_name = serializers.CharField(source='responsable.get_full_name', read_only=True, default=None)
    statut_display    = serializers.CharField(source='get_statut_display', read_only=True)

    class Meta:
        model  = Projet
        fields = [
            'id', 'programme', 'programme_name', 'code', 'libelle',
            'responsable', 'responsable_name', 'budget_total',
            'date_debut', 'date_fin', 'statut', 'statut_display',
            'taux_avancement', 'created_at',
        ]


class PlanTravailAnnuelSerializer(serializers.ModelSerializer):
    academic_year_label = serializers.CharField(source='academic_year.label', read_only=True)
    titulaire_name        = serializers.CharField(source='titulaire.get_full_name', read_only=True)
    direction_name         = serializers.CharField(source='direction.name', read_only=True, default=None)

    class Meta:
        model  = PlanTravailAnnuel
        fields = [
            'id', 'academic_year', 'academic_year_label', 'titulaire', 'titulaire_name',
            'direction', 'direction_name', 'created_at',
        ]
