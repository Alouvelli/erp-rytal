from django.urls import path
from . import views

app_name = 'admissions'

urlpatterns = [
    # ── Chef de département (authentifié) — avant le préfixe institut_code
    # générique ci-dessous pour éviter toute ambiguïté de résolution ────────
    path('candidatures/', views.candidature_list_view, name='candidature_list'),
    path('candidatures/<int:pk>/', views.candidature_detail_view, name='candidature_detail'),
    path('mes-filieres/', views.mes_filieres_list_view, name='mes_filieres_list'),
    path('mes-filieres/<int:pk>/', views.filiere_content_edit_view, name='filiere_content_edit'),
    path('mon-departement/presentation/', views.department_presentation_edit_view, name='department_presentation_edit'),
    path('candidats/', views.candidat_accounts_list_view, name='candidat_accounts_list'),
    path('candidats/<int:user_pk>/modifier/', views.candidat_account_edit_view, name='candidat_account_edit'),
    path('candidats/<int:user_pk>/supprimer/', views.candidat_account_delete_view, name='candidat_account_delete'),
    path('candidats/<int:user_pk>/rappel/', views.candidat_account_resend_view, name='candidat_account_resend'),
    path('inscriptions-dates/', views.department_admissions_dates_list_view, name='department_admissions_dates_list'),
    path('inscriptions-dates/<int:pk>/', views.department_admissions_dates_edit_view, name='department_admissions_dates_edit'),
    path('inscriptions-dates/<int:pk>/supprimer/', views.department_admissions_dates_clear_view, name='department_admissions_dates_clear'),

    # ── Accès sans code institut (lien incomplet) — le portail public par
    # institut vit désormais à /admission-<code_institut>/, voir portal_urls.py
    # et config/urls.py ────────────────────────────────────────────────────
    path('', views.admission_landing_view, name='admission_landing'),
]
