from rest_framework.routers import DefaultRouter
from .api_views import CritereQualiteViewSet, PlanAmeliorationViewSet

router = DefaultRouter()
router.register(r'criteres', CritereQualiteViewSet, basename='critere-qualite')
router.register(r'plans-amelioration', PlanAmeliorationViewSet, basename='plan-amelioration')

urlpatterns = router.urls
