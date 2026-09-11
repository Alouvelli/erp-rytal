from rest_framework import serializers
from .models import Department, Program, Class


class DepartmentSerializer(serializers.ModelSerializer):
    faculty_name = serializers.CharField(source='faculty.name', read_only=True)

    class Meta:
        model  = Department
        fields = [
            'id', 'code', 'name', 'faculty', 'faculty_name',
            'head', 'description', 'is_active', 'created_at',
        ]


class ProgramSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source='department.name', read_only=True)

    class Meta:
        model  = Program
        fields = [
            'id', 'code', 'name', 'department', 'department_name',
            'level', 'duration_years', 'places_disponibles',
            'ouvert_admissions', 'created_at',
        ]


class ClassSerializer(serializers.ModelSerializer):
    program_name       = serializers.CharField(source='program.name', read_only=True)
    level_name         = serializers.CharField(source='level.name', read_only=True)
    academic_year_name = serializers.CharField(source='academic_year.label', read_only=True)
    student_count      = serializers.IntegerField(read_only=True)

    class Meta:
        model  = Class
        fields = [
            'id', 'code', 'name', 'program', 'program_name',
            'level', 'level_name', 'academic_year', 'academic_year_name',
            'domaine', 'mention', 'capacity', 'student_count', 'created_at',
        ]
