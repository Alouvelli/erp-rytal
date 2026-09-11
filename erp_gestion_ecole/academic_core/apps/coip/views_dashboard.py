from django.shortcuts import render

from .permissions import coip_staff_required
from .services import get_coip_dashboard_stats


@coip_staff_required
def index(request):
    return render(request, 'coip/index.html', get_coip_dashboard_stats())
