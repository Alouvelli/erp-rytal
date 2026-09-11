from django.urls import path
from . import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.dashboard_index, name='index'),
    path('select-institute/', views.select_institute, name='select_institute'),
]
