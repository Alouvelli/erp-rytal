from rest_framework import viewsets, filters
from django_filters.rest_framework import DjangoFilterBackend
from .models import Building, Room
from .serializers import BuildingSerializer, RoomSerializer


class BuildingViewSet(viewsets.ReadOnlyModelViewSet):
    """Bâtiments de l'institut — lecture seule."""
    queryset = Building.objects.order_by('name')
    serializer_class = BuildingSerializer
    filter_backends  = [filters.SearchFilter]
    search_fields    = ['code', 'name']


class RoomViewSet(viewsets.ReadOnlyModelViewSet):
    """Salles de l'institut (capacité, équipements, disponibilité) — lecture seule."""
    queryset = Room.objects.select_related('building').order_by('building', 'code')
    serializer_class = RoomSerializer
    filter_backends  = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['building', 'room_type', 'is_available']
    search_fields    = ['code', 'name']
