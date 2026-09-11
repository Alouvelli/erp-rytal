from django.urls import path
from . import views

app_name = 'quality'

urlpatterns = [
    path('', views.quality_dashboard, name='quality_dashboard'),
    path('criteres/', views.critere_list, name='critere_list'),
    path('criteres/creer/', views.critere_create, name='critere_create'),
    path('criteres/<int:pk>/modifier/', views.critere_edit, name='critere_edit'),
    path('criteres/<int:pk>/supprimer/', views.critere_delete, name='critere_delete'),
    path('evaluations/ajouter/', views.evaluation_create, name='evaluation_create'),
    path('plans/', views.plan_list, name='plan_list'),
    path('plans/creer/', views.plan_create, name='plan_create'),
    path('plans/<int:pk>/modifier/', views.plan_edit, name='plan_edit'),
    path('plans/<int:pk>/supprimer/', views.plan_delete, name='plan_delete'),
]
