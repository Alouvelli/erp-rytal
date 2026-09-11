from rest_framework.routers import DefaultRouter
from .api_views import BuildingViewSet, RoomViewSet

router = DefaultRouter()
router.register(r'buildings', BuildingViewSet, basename='building')
router.register(r'rooms', RoomViewSet, basename='room')

urlpatterns = router.urls
