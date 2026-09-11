from rest_framework.routers import DefaultRouter
from .api_views import CommunityServiceActivityViewSet

router = DefaultRouter()
router.register(r'', CommunityServiceActivityViewSet, basename='community-activity')

urlpatterns = router.urls
