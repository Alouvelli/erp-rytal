from rest_framework.routers import DefaultRouter
from .api_views import FichePersonnelViewSet, ContractViewSet, DemandeCongeViewSet

router = DefaultRouter()
router.register(r'fiches-personnel', FichePersonnelViewSet, basename='fiche-personnel')
router.register(r'contracts', ContractViewSet, basename='contract')
router.register(r'demandes-conge', DemandeCongeViewSet, basename='demande-conge')

urlpatterns = router.urls
