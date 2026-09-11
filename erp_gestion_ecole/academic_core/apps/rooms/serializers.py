from rest_framework import serializers
from .models import Building, Room


class BuildingSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Building
        fields = ['id', 'code', 'name', 'faculty']


class RoomSerializer(serializers.ModelSerializer):
    building_name = serializers.CharField(source='building.name', read_only=True)
    room_type_display = serializers.CharField(source='get_room_type_display', read_only=True)

    class Meta:
        model  = Room
        fields = [
            'id', 'code', 'name', 'building', 'building_name',
            'room_type', 'room_type_display', 'capacity',
            'has_projector', 'has_ac', 'is_available', 'created_at',
        ]
