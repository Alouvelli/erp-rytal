from rest_framework.routers import DefaultRouter
from .api_views import AttendanceSheetViewSet, StudentAttendanceViewSet

router = DefaultRouter()
router.register(r'sheets',  AttendanceSheetViewSet,   basename='attendance-sheet')
router.register(r'records', StudentAttendanceViewSet, basename='student-attendance')

urlpatterns = router.urls
