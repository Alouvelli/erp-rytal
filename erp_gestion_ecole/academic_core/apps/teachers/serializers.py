from rest_framework import serializers
from .models import Teacher, Grade


class GradeSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Grade
        fields = ['id', 'code', 'label', 'order']


class TeacherSerializer(serializers.ModelSerializer):
    full_name         = serializers.CharField(read_only=True)
    email             = serializers.EmailField(source='user.email', read_only=True)
    grade_label       = serializers.CharField(source='grade.label', read_only=True)
    statut_label      = serializers.CharField(source='get_statut_display', read_only=True)

    class Meta:
        model  = Teacher
        fields = [
            'id', 'matricule', 'full_name', 'email',
            'grade', 'grade_label', 'specialty',
            'statut', 'statut_label',
            'contractual_hours', 'hire_date', 'created_at',
        ]
        read_only_fields = ['created_at']
