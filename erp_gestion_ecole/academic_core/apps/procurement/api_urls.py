from rest_framework.routers import DefaultRouter
from .api_views import DemandeAchatViewSet, CommandeAchatViewSet, FactureAchatViewSet

router = DefaultRouter()
router.register(r'demandes', DemandeAchatViewSet, basename='demande-achat')
router.register(r'commandes', CommandeAchatViewSet, basename='commande-achat')
router.register(r'factures', FactureAchatViewSet, basename='facture-achat')

urlpatterns = router.urls
