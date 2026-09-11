from rest_framework import serializers
from .models import Candidature


class CandidatureSerializer(serializers.ModelSerializer):
    candidat_name  = serializers.CharField(source='user.get_full_name', read_only=True)
    program_name     = serializers.CharField(source='program.name', read_only=True)
    status_display    = serializers.CharField(source='get_status_display', read_only=True)
    niveau_entree_display = serializers.CharField(source='get_niveau_entree_display', read_only=True)
    documents_completes    = serializers.BooleanField(read_only=True)

    class Meta:
        model  = Candidature
        fields = [
            'id', 'candidat_name', 'program', 'program_name',
            'niveau_entree', 'niveau_entree_display', 'submitted_at',
            'status', 'status_display', 'documents_completes',
            'reviewed_at',
        ]
