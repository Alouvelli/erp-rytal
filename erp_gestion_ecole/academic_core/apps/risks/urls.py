from django.urls import path
from . import views

app_name = 'risks'

urlpatterns = [
    path('matrice/', views.matrice_risques, name='matrice'),
    path('', views.risque_list, name='risque_list'),
    path('creer/', views.risque_create, name='risque_create'),
    path('<int:pk>/modifier/', views.risque_edit, name='risque_edit'),
    path('<int:pk>/supprimer/', views.risque_delete, name='risque_delete'),
    path('suivis/ajouter/', views.suivi_create, name='suivi_create'),
]
