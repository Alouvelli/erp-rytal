from rest_framework import serializers
from .models import CritereQualite, PlanAmelioration


class CritereQualiteSerializer(serializers.ModelSerializer):
    referentiel_display = serializers.CharField(source='get_referentiel_display', read_only=True)

    class Meta:
        model  = CritereQualite
        fields = [
            'id', 'referentiel', 'referentiel_display', 'code', 'libelle',
            'categorie', 'description', 'ponderation', 'created_at',
        ]


class PlanAmeliorationSerializer(serializers.ModelSerializer):
    critere_code    = serializers.CharField(source='critere.code', read_only=True)
    responsable_name = serializers.CharField(source='responsable.get_full_name', read_only=True, default=None)
    statut_display     = serializers.CharField(source='get_statut_display', read_only=True)

    class Meta:
        model  = PlanAmelioration
        fields = [
            'id', 'critere', 'critere_code', 'action', 'description',
            'responsable', 'responsable_name', 'date_echeance',
            'statut', 'statut_display', 'taux_avancement', 'created_at',
        ]
