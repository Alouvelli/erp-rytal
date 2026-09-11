from rest_framework import serializers
from .models import Evaluation, Grade, SubjectAverage, SemesterAverage


class GradeSerializer(serializers.ModelSerializer):
    student_name    = serializers.CharField(source='student.full_name', read_only=True)
    evaluation_title = serializers.CharField(source='evaluation.title', read_only=True)
    subject_title   = serializers.CharField(source='evaluation.subject.title', read_only=True)
    max_score       = serializers.DecimalField(
        source='evaluation.max_score', max_digits=5, decimal_places=2, read_only=True
    )

    class Meta:
        model  = Grade
        fields = [
            'id', 'student', 'student_name', 'evaluation', 'evaluation_title',
            'subject_title', 'score', 'max_score', 'comment', 'entered_at',
        ]
        read_only_fields = ['entered_at']

    def validate_score(self, value):
        evaluation = self.initial_data.get('evaluation')
        if evaluation:
            from .models import Evaluation
            try:
                ev = Evaluation.objects.get(pk=evaluation)
                if value > ev.max_score:
                    raise serializers.ValidationError(
                        f"La note ne peut pas dépasser {ev.max_score}."
                    )
            except Evaluation.DoesNotExist:
                pass
        return value


class EvaluationSerializer(serializers.ModelSerializer):
    type_label     = serializers.CharField(source='evaluation_type.label', read_only=True)
    subject_title  = serializers.CharField(source='subject.title', read_only=True)
    teacher_name   = serializers.CharField(source='teacher.full_name', read_only=True)
    grades_count   = serializers.SerializerMethodField()

    class Meta:
        model  = Evaluation
        fields = [
            'id', 'subject', 'subject_title', 'semester', 'evaluation_type',
            'type_label', 'teacher', 'teacher_name', 'title', 'date',
            'max_score', 'is_locked', 'locked_at', 'grades_count', 'created_at',
        ]
        read_only_fields = ['created_at', 'locked_at']

    def get_grades_count(self, obj):
        return obj.grades.count()


class SemesterAverageSerializer(serializers.ModelSerializer):
    student_name   = serializers.CharField(source='student.full_name', read_only=True)
    semester_label = serializers.CharField(source='semester.label', read_only=True)

    class Meta:
        model  = SemesterAverage
        fields = [
            'id', 'student', 'student_name', 'semester', 'semester_label',
            'average', 'rank', 'total_students', 'mention', 'computed_at',
        ]
