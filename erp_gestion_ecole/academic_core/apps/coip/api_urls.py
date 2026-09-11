from rest_framework.routers import DefaultRouter
from .api_views import PartnerViewSet, InternshipViewSet, ActivityViewSet, AlumniViewSet

router = DefaultRouter()
router.register(r'partners', PartnerViewSet, basename='coip-partner')
router.register(r'internships', InternshipViewSet, basename='coip-internship')
router.register(r'activities', ActivityViewSet, basename='coip-activity')
router.register(r'alumni', AlumniViewSet, basename='coip-alumni')

urlpatterns = router.urls
