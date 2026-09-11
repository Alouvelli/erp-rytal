from rest_framework import serializers
from .models import Subject


class SubjectSerializer(serializers.ModelSerializer):
    program_name  = serializers.CharField(source='program.name', read_only=True)
    semester_name = serializers.CharField(source='semester.name', read_only=True)
    teacher_name  = serializers.CharField(source='responsible_teacher.full_name', read_only=True, default=None)

    class Meta:
        model  = Subject
        fields = [
            'id', 'code', 'title', 'program', 'program_name',
            'semester', 'semester_name', 'subject_type', 'coefficient',
            'credits', 'volume_cm', 'volume_td', 'volume_tp', 'volume_tpe',
            'volume_hours', 'volume_total_ue', 'responsible_teacher',
            'teacher_name', 'created_at',
        ]
