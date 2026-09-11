from rest_framework.routers import DefaultRouter
from .api_views import DepartmentViewSet, ProgramViewSet, ClassViewSet

router = DefaultRouter()
router.register(r'departments', DepartmentViewSet, basename='department')
router.register(r'programs', ProgramViewSet, basename='program')
router.register(r'classes', ClassViewSet, basename='class')

urlpatterns = router.urls
