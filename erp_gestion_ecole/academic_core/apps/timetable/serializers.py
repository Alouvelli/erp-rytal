from rest_framework import serializers
from .models import TimetableEntry
from academic_core.apps.subjects.models import Subject
from academic_core.apps.teachers.models import Teacher
from academic_core.apps.rooms.models import Room
from academic_core.apps.academic_structure.models import Class, Semester


class TimetableEntrySerializer(serializers.ModelSerializer):
    subject_title   = serializers.CharField(source='subject.title', read_only=True)
    teacher_name    = serializers.CharField(source='teacher.full_name', read_only=True)
    room_code       = serializers.CharField(source='room.code', read_only=True)
    class_name      = serializers.CharField(source='class_group.name', read_only=True)
    semester_label  = serializers.CharField(source='semester.label', read_only=True)
    duration_hours  = serializers.DecimalField(
        max_digits=4, decimal_places=2, read_only=True
    )
    day_label       = serializers.CharField(source='get_day_of_week_display', read_only=True)

    class Meta:
        model  = TimetableEntry
        fields = [
            'id', 'semester', 'semester_label', 'class_group', 'class_name',
            'subject', 'subject_title', 'teacher', 'teacher_name',
            'room', 'room_code', 'day_of_week', 'day_label',
            'start_time', 'end_time', 'duration_hours',
            'recurrence', 'color', 'is_active', 'created_at',
        ]
        read_only_fields = ['created_at']

    def validate(self, data):
        start = data.get('start_time')
        end   = data.get('end_time')
        if start and end and start >= end:
            raise serializers.ValidationError(
                "L'heure de début doit être avant l'heure de fin."
            )
        return data


class TimetableEntryCalendarSerializer(serializers.ModelSerializer):
    """Format FullCalendar."""
    title = serializers.SerializerMethodField()
    start = serializers.SerializerMethodField()
    end   = serializers.SerializerMethodField()
    extendedProps = serializers.SerializerMethodField()

    class Meta:
        model  = TimetableEntry
        fields = ['id', 'title', 'start', 'end', 'color', 'extendedProps']

    def get_title(self, obj):
        return f"{obj.subject.code} — {obj.class_group.code}"

    def _get_date(self, obj):
        from datetime import date, timedelta
        today  = date.today()
        monday = today - timedelta(days=today.weekday())
        return monday + timedelta(days=obj.day_of_week - 1)

    def get_start(self, obj):
        return f"{self._get_date(obj)}T{obj.start_time}"

    def get_end(self, obj):
        return f"{self._get_date(obj)}T{obj.end_time}"

    def get_extendedProps(self, obj):
        return {
            'teacher': obj.teacher.full_name,
            'room':    str(obj.room) if obj.room else '—',
            'subject': obj.subject.title,
            'class':   str(obj.class_group),
        }
