from rest_framework.routers import DefaultRouter
from .api_views import ProjetViewSet, PlanTravailAnnuelViewSet

router = DefaultRouter()
router.register(r'projets', ProjetViewSet, basename='projet')
router.register(r'pta', PlanTravailAnnuelViewSet, basename='pta')

urlpatterns = router.urls
