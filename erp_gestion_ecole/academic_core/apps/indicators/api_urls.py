from rest_framework.routers import DefaultRouter
from .api_views import IndicateurViewSet

router = DefaultRouter()
router.register(r'', IndicateurViewSet, basename='indicateur')

urlpatterns = router.urls
