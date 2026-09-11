from rest_framework import serializers
from .models import Indicateur, ValeurIndicateur


class IndicateurSerializer(serializers.ModelSerializer):
    responsable_name = serializers.CharField(source='responsable.get_full_name', read_only=True, default=None)
    periodicite_display = serializers.CharField(source='get_periodicite_display', read_only=True)
    taux_realisation      = serializers.DecimalField(max_digits=8, decimal_places=4, read_only=True)
    etat                    = serializers.CharField(read_only=True)

    class Meta:
        model  = Indicateur
        fields = [
            'id', 'code', 'libelle', 'formule', 'source', 'responsable', 'responsable_name',
            'periodicite', 'periodicite_display', 'unite', 'sens_amelioration',
            'valeur_cible', 'valeur_actuelle', 'taux_realisation', 'etat', 'created_at',
        ]


class ValeurIndicateurSerializer(serializers.ModelSerializer):
    indicateur_code = serializers.CharField(source='indicateur.code', read_only=True)

    class Meta:
        model  = ValeurIndicateur
        fields = ['id', 'indicateur', 'indicateur_code', 'date_mesure', 'valeur', 'commentaire', 'created_at']
