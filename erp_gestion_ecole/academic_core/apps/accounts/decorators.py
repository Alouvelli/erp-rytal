from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages


def role_required(*roles):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('accounts:login')
            if request.user.role and request.user.role.name in roles:
                return view_func(request, *args, **kwargs)
            messages.error(request, "Accès refusé : permissions insuffisantes.")
            return redirect('dashboard:index')
        return wrapper
    return decorator


def admin_required(view_func):
    return role_required('ADMIN', 'CIAQ', 'CONTROLEUR')(view_func)


def responsable_required(view_func):
    return role_required('ADMIN', 'CIAQ', 'CONTROLEUR', 'RESPONSABLE', 'ASSISTANTE')(view_func)


def enseignant_required(view_func):
    return role_required('ADMIN', 'CIAQ', 'CONTROLEUR', 'RESPONSABLE', 'ASSISTANTE', 'ENSEIGNANT')(view_func)
