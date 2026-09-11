from rest_framework.routers import DefaultRouter
from .api_views import NotificationViewSet

router = DefaultRouter()
router.register(r'', NotificationViewSet, basename='notification')

urlpatterns = router.urls
