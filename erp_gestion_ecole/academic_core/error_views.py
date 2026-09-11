"""
Gestionnaires d'erreurs HTTP personnalisés (voir `handler404` dans
config/urls.py). Actifs uniquement quand DEBUG=False — Django affiche
toujours sa page technique de débogage tant que DEBUG=True, quel que soit
le handler enregistré ici.
"""
from django.shortcuts import render


def custom_404_view(request, exception=None):
    """
    Page 404 conviviale : plutôt qu'une erreur technique, indique clairement
    à l'utilisateur que le lien qu'il a saisi/suivi n'est pas le bon —
    avec une indication spécifique du format attendu quand l'adresse
    ressemble à une tentative d'accès au portail d'admission
    (/admission/<code_institut>/).
    """
    path = request.path.strip('/')
    is_admission_like = path.startswith('admission')
    return render(request, 'errors/404.html', {
        'is_admission_like': is_admission_like,
        'attempted_path': request.path,
    }, status=404)
