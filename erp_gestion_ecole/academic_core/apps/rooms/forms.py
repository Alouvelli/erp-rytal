from django import forms
from .models import Room


class RoomForm(forms.ModelForm):
    class Meta:
        model = Room
        fields = ['code', 'name', 'building', 'room_type', 'capacity', 'has_projector', 'has_ac', 'is_available']
        widgets = {
            'code':      forms.TextInput(attrs={'class': 'form-control'}),
            'name':      forms.TextInput(attrs={'class': 'form-control'}),
            'building':  forms.Select(attrs={'class': 'form-select'}),
            'room_type': forms.Select(attrs={'class': 'form-select'}),
            'capacity':  forms.NumberInput(attrs={'class': 'form-control'}),
        }
