from rest_framework import serializers
from .models import Student, Enrollment


class StudentSerializer(serializers.ModelSerializer):
    full_name   = serializers.CharField(read_only=True)
    email       = serializers.EmailField(source='user.email', read_only=True)
    class_name  = serializers.SerializerMethodField()

    class Meta:
        model  = Student
        fields = [
            'id', 'matricule', 'full_name', 'email',
            'date_of_birth', 'gender', 'address',
            'guardian_name', 'guardian_phone',
            'class_name', 'created_at',
        ]
        read_only_fields = ['created_at']

    def get_class_name(self, obj):
        enrollment = obj.current_enrollment()
        return enrollment.class_group.name if enrollment else None


class EnrollmentSerializer(serializers.ModelSerializer):
    student_name   = serializers.CharField(source='student.full_name', read_only=True)
    class_name     = serializers.CharField(source='class_group.name', read_only=True)
    academic_year  = serializers.CharField(source='academic_year.label', read_only=True)

    class Meta:
        model  = Enrollment
        fields = [
            'id', 'student', 'student_name',
            'class_group', 'class_name',
            'academic_year', 'enrollment_date', 'is_active',
        ]
