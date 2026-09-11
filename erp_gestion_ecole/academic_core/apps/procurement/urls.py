from django.urls import path
from . import views

app_name = 'procurement'

urlpatterns = [
    path('fournisseurs/', views.fournisseur_list, name='fournisseur_list'),
    path('fournisseurs/creer/', views.fournisseur_create, name='fournisseur_create'),
    path('fournisseurs/<int:pk>/modifier/', views.fournisseur_edit, name='fournisseur_edit'),
    path('fournisseurs/<int:pk>/supprimer/', views.fournisseur_delete, name='fournisseur_delete'),

    path('demandes/', views.demande_list, name='demande_list'),
    path('demandes/creer/', views.demande_create, name='demande_create'),
    path('demandes/<int:pk>/soumettre/', views.demande_soumettre, name='demande_soumettre'),
    path('demandes/<int:pk>/valider/', views.demande_valider, name='demande_valider'),
    path('demandes/<int:pk>/rejeter/', views.demande_rejeter, name='demande_rejeter'),
    path('demandes/<int:pk>/annuler/', views.demande_annuler, name='demande_annuler'),

    path('appels-offres/', views.appel_offres_list, name='appel_offres_list'),
    path('appels-offres/creer/', views.appel_offres_create, name='appel_offres_create'),
    path('offres/ajouter/', views.offre_create, name='offre_create'),
    path('offres/<int:pk>/retenir/', views.offre_retenir, name='offre_retenir'),

    path('commandes/', views.commande_list, name='commande_list'),
    path('commandes/creer/', views.commande_create, name='commande_create'),
    path('commandes/<int:pk>/livrer/', views.commande_livrer, name='commande_livrer'),
    path('receptions/ajouter/', views.reception_create, name='reception_create'),

    path('factures/', views.facture_list, name='facture_list'),
    path('factures/creer/', views.facture_create, name='facture_create'),
    path('factures/<int:pk>/valider/', views.facture_valider, name='facture_valider'),
    path('paiements/ajouter/', views.paiement_create, name='paiement_create'),
    path('paiements/<int:pk>/effectuer/', views.paiement_effectuer, name='paiement_effectuer'),
    path('paiements/<int:pk>/annuler/', views.paiement_annuler, name='paiement_annuler'),
]
