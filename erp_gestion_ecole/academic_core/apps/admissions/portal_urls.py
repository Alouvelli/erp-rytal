from django.urls import path
from . import views

app_name = 'admission_portal'

# Portail public d'admission, un institut par adresse : /admission-<code_institut>/...
# (voir config/urls.py — le préfixe 'admission-<str:institut_code>/' capture le code
# et le transmet à chaque vue ci-dessous via le kwarg `institut_code`).
urlpatterns = [
    path('', views.portail_view, name='portail'),
    path('filiere/<str:program_code>/', views.filiere_detail_view, name='filiere_detail'),
    path('creer-compte/', views.signup_view, name='creer_compte'),
    path('verifier-email/<str:token>/', views.verify_email_view, name='verifier_email'),
    path('paiement/webhook/wave/', views.wave_webhook_view, name='wave_webhook'),
    path('paiement/webhook/orange-money/', views.orange_money_webhook_view, name='orange_money_webhook'),
]
