from rest_framework.routers import DefaultRouter
from .api_views import TimetableEntryViewSet

router = DefaultRouter()
router.register(r'entries', TimetableEntryViewSet, basename='timetable-entry')

urlpatterns = router.urls
