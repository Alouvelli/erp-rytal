from django.urls import path
from . import views

app_name = 'candidat'

urlpatterns = [
    path('candidature/', views.candidature_view, name='candidature'),
    path('statut/', views.candidat_dashboard_view, name='candidat_dashboard'),
    path('documents/', views.candidat_documents_view, name='candidat_documents'),
    path('inscription/', views.candidat_inscription_view, name='candidat_inscription'),
    path('paiement/', views.candidat_paiement_view, name='candidat_paiement'),
    path('paiement/en-ligne/', views.candidat_paiement_en_ligne_view, name='candidat_paiement_en_ligne'),
    path('paiement/retour/', views.candidat_paiement_retour_view, name='candidat_paiement_retour'),
]
