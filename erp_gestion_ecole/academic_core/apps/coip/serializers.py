from rest_framework import serializers
from .models import Partner, Internship, Activity, Alumni


class PartnerSerializer(serializers.ModelSerializer):
    type_partenaire_display = serializers.CharField(source='get_type_partenaire_display', read_only=True)

    class Meta:
        model  = Partner
        fields = [
            'id', 'raison_sociale', 'type_partenaire', 'type_partenaire_display',
            'secteur', 'ville', 'pays', 'email', 'phone', 'site_web',
            'is_active', 'created_at',
        ]


class InternshipSerializer(serializers.ModelSerializer):
    student_name  = serializers.CharField(source='student.full_name', read_only=True)
    partner_name   = serializers.CharField(source='partner.raison_sociale', read_only=True)
    status_display  = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model  = Internship
        fields = [
            'id', 'student', 'student_name', 'partner', 'partner_name', 'titre',
            'encadreur_entreprise', 'date_debut', 'date_fin', 'status', 'status_display',
            'note', 'created_at',
        ]


class ActivitySerializer(serializers.ModelSerializer):
    type_activite_display = serializers.CharField(source='get_type_activite_display', read_only=True)
    status_display          = serializers.CharField(source='get_status_display', read_only=True)
    responsable_name         = serializers.CharField(source='responsable.get_full_name', read_only=True, default=None)

    class Meta:
        model  = Activity
        fields = [
            'id', 'titre', 'type_activite', 'type_activite_display', 'description',
            'date_debut', 'date_fin', 'lieu', 'responsable', 'responsable_name',
            'status', 'status_display', 'created_at',
        ]


class AlumniSerializer(serializers.ModelSerializer):
    full_name         = serializers.CharField(source='get_full_name', read_only=True)
    filiere_name        = serializers.CharField(source='filiere.name', read_only=True, default=None)
    secteur_activite_display = serializers.CharField(source='get_secteur_activite_display', read_only=True)

    class Meta:
        model  = Alumni
        fields = [
            'id', 'full_name', 'email', 'phone', 'promotion', 'diplome',
            'filiere', 'filiere_name', 'annee_obtention', 'entreprise_actuelle',
            'poste_occupe', 'secteur_activite', 'secteur_activite_display',
            'is_employed', 'pays', 'ville', 'created_at',
        ]
