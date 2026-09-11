from rest_framework.routers import DefaultRouter
from .api_views import CaisseMovementViewSet, DemandeDepenseViewSet, LigneBudgetaireViewSet

router = DefaultRouter()
router.register(r'caisse-movements', CaisseMovementViewSet, basename='caisse-movement')
router.register(r'demandes-depense', DemandeDepenseViewSet, basename='demande-depense')
router.register(r'lignes-budgetaires', LigneBudgetaireViewSet, basename='ligne-budgetaire')

urlpatterns = router.urls
