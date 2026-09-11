from django.urls import path
from . import views

app_name = 'indicators'

urlpatterns = [
    path('', views.indicateur_list, name='indicateur_list'),
    path('creer/', views.indicateur_create, name='indicateur_create'),
    path('import/', views.indicateur_import, name='indicateur_import'),
    path('pdf/', views.indicateur_pdf, name='indicateur_pdf'),
    path('<int:pk>/', views.indicateur_detail, name='indicateur_detail'),
    path('<int:pk>/modifier/', views.indicateur_edit, name='indicateur_edit'),
    path('<int:pk>/supprimer/', views.indicateur_delete, name='indicateur_delete'),
    path('mesures/ajouter/', views.valeur_create, name='valeur_create'),
]
