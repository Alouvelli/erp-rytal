from rest_framework.routers import DefaultRouter
from .api_views import CandidatureViewSet

router = DefaultRouter()
router.register(r'', CandidatureViewSet, basename='candidature')

urlpatterns = router.urls
