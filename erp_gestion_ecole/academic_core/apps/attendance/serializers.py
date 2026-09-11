from rest_framework import serializers
from .models import AttendanceSheet, StudentAttendance


class StudentAttendanceSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source='student.full_name', read_only=True)
    status_label = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model  = StudentAttendance
        fields = [
            'id', 'attendance_sheet', 'student', 'student_name',
            'status', 'status_label', 'comment',
        ]


class AttendanceSheetSerializer(serializers.ModelSerializer):
    subject_title   = serializers.CharField(
        source='timetable_entry.subject.title', read_only=True
    )
    teacher_name    = serializers.CharField(
        source='timetable_entry.teacher.full_name', read_only=True
    )
    class_name      = serializers.CharField(
        source='timetable_entry.class_group.name', read_only=True
    )
    status_label    = serializers.CharField(source='get_status_display', read_only=True)
    student_attendances = StudentAttendanceSerializer(many=True, read_only=True)

    class Meta:
        model  = AttendanceSheet
        fields = [
            'id', 'timetable_entry', 'subject_title', 'teacher_name',
            'class_name', 'session_date', 'status', 'status_label',
            'teacher_signature_at', 'teacher_comment',
            'validated_by', 'validated_at',
            'student_attendances', 'created_at',
        ]
        read_only_fields = ['created_at', 'teacher_signature_at', 'validated_at']
