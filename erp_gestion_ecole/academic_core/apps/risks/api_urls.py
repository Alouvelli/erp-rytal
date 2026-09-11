from rest_framework.routers import DefaultRouter
from .api_views import RisqueViewSet

router = DefaultRouter()
router.register(r'', RisqueViewSet, basename='risque')

urlpatterns = router.urls
