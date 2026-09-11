from rest_framework import serializers
from .models import CommunityServiceActivity


class CommunityServiceActivitySerializer(serializers.ModelSerializer):
    categorie_display = serializers.CharField(source='get_categorie_display', read_only=True)
    statut_display     = serializers.CharField(source='get_statut_display', read_only=True)
    responsable_name    = serializers.CharField(source='responsable.get_full_name', read_only=True, default=None)

    class Meta:
        model  = CommunityServiceActivity
        fields = [
            'id', 'titre', 'categorie', 'categorie_display', 'description',
            'date_debut', 'date_fin', 'lieu', 'beneficiaires', 'nombre_participants',
            'partenaires', 'statut', 'statut_display', 'resultats',
            'responsable', 'responsable_name', 'created_at',
        ]
