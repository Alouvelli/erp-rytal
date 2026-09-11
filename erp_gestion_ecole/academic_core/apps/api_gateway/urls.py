from django.urls import path
from . import views

app_name = 'api_gateway'

urlpatterns = [
    path('', views.catalog_list, name='catalog_list'),
    path('accorder/<int:resource_id>/', views.grant_create, name='grant_create'),
    path('acces-accordes/', views.grants_list, name='grants_list'),
    path('acces-accordes/<int:grant_id>/revoquer/', views.grant_revoke, name='grant_revoke'),
    path('demandes/', views.access_requests_list, name='access_requests_list'),
    path('demandes/<int:request_id>/traiter/', views.access_request_process, name='access_request_process'),
    path('demander/', views.my_access_request_create, name='my_access_request_create'),
    path('mes-demandes/', views.my_access_requests, name='my_access_requests'),
]
