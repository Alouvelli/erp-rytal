from rest_framework.routers import DefaultRouter
from .api_views import CourseCancellationViewSet

router = DefaultRouter()
router.register(r'', CourseCancellationViewSet, basename='cancellation')

urlpatterns = router.urls
