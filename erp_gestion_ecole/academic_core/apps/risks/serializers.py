from rest_framework import serializers
from .models import Risque


class RisqueSerializer(serializers.ModelSerializer):
    categorie_display = serializers.CharField(source='get_categorie_display', read_only=True)
    statut_display      = serializers.CharField(source='get_statut_display', read_only=True)
    responsable_name     = serializers.CharField(source='responsable.get_full_name', read_only=True, default=None)
    score                  = serializers.IntegerField(read_only=True)
    niveau                  = serializers.CharField(read_only=True)

    class Meta:
        model  = Risque
        fields = [
            'id', 'code', 'libelle', 'description', 'categorie', 'categorie_display',
            'gravite', 'probabilite', 'score', 'niveau', 'responsable', 'responsable_name',
            'plan_mitigation', 'statut', 'statut_display', 'date_identification', 'created_at',
        ]
