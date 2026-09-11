from rest_framework.permissions import BasePermission


class IsAdminOrResponsable(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.can_manage_dept()


class IsTeacherOwner(BasePermission):
    """Autorise un enseignant à agir sur ses propres ressources."""
    def has_object_permission(self, request, view, obj):
        if request.user.can_manage_dept():
            return True
        teacher = getattr(request.user, 'teacher_profile', None)
        if not teacher:
            return False
        # obj peut être AttendanceSheet
        if hasattr(obj, 'timetable_entry'):
            return obj.timetable_entry.teacher == teacher
        return False
