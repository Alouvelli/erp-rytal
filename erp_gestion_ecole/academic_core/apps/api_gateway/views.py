from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from .models import APIResource, APIAccessRequest, APIAccessGrant


def _require_api_gateway_view_access(user):
    """
    Onglet « API de Consommation » : consultation du catalogue + possibilité
    de demander un accès — ouvert aux administrateurs (au sens large,
    is_admin()) et aux chefs de département / assistantes (is_responsable()).
    """
    return user.is_admin() or user.is_responsable()


def _require_api_gateway_manage_access(user):
    """
    Traitement des demandes, octroi direct d'un accès, révocation — réservé à
    l'administrateur d'institut ou au contrôleur interne (rôles INST_ADMIN /
    CONTROLEUR), + Super Admin en visite d'un institut. Demande explicite de
    l'utilisateur : ce sont eux qui « fournissent » l'accès, les autres
    rôles admin/chef de département ne font que consulter et demander.
    """
    role_name = user.role.name if user.role else ''
    return role_name in ('INST_ADMIN', 'CONTROLEUR') or user.is_super_admin()


def _build_grant_link(request, resource, raw_key):
    return request.build_absolute_uri(resource.endpoint_path) + f"?api_key={raw_key}"


def _notify_institut_admins(new_request):
    from academic_core.apps.accounts.models import User
    from academic_core.apps.notifications.utils import notify_users

    admins = [
        u for u in User.objects.filter(is_active=True).select_related('role')
        if _require_api_gateway_manage_access(u)
    ]
    if not admins:
        return
    notify_users(
        recipients=admins,
        notification_type='ABSENCE',  # type générique existant, réutilisé (pas de type dédié requis)
        title=f"Nouvelle demande d'accès API — {new_request.requested_by.get_full_name()}",
        message=(
            f"{new_request.requested_by.get_full_name()} a exprimé un besoin d'accès API : "
            f"« {new_request.description[:200]} »"
        ),
        priority='MEDIUM',
        link='/api-consommation/demandes/',
    )


# ---------------------------------------------------------------------------
# Catalogue (administrateurs + chefs de département) et administration
# (administrateur d'institut / contrôleur interne uniquement pour le
# traitement des demandes et l'octroi direct)
# ---------------------------------------------------------------------------

@login_required
def catalog_list(request):
    if not _require_api_gateway_view_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    can_manage = _require_api_gateway_manage_access(request.user)

    resources = APIResource.objects.filter(is_active=True)
    grouped = {}
    for r in resources:
        grouped.setdefault(r.get_functionality_display(), []).append(r)

    users = []
    if can_manage:
        from academic_core.apps.accounts.models import User
        users = User.objects.filter(is_active=True).exclude(pk=request.user.pk).select_related('role').order_by(
            'first_name', 'last_name'
        )

    return render(request, 'api_gateway/catalog_list.html', {
        'grouped_resources': grouped,
        'users': users,
        'can_manage': can_manage,
    })


@login_required
def grant_create(request, resource_id):
    if not _require_api_gateway_manage_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    resource = get_object_or_404(APIResource, pk=resource_id)

    if request.method != 'POST':
        return redirect('api_gateway:catalog_list')

    from academic_core.apps.accounts.models import User
    from academic_core.db_router import get_current_db

    target_user_id = request.POST.get('user_id')
    target_user = get_object_or_404(User, pk=target_user_id)
    expires_raw = request.POST.get('expires_at', '').strip()
    expires_at = None
    if expires_raw:
        from django.utils.dateparse import parse_date
        d = parse_date(expires_raw)
        if d:
            expires_at = timezone.make_aware(timezone.datetime.combine(d, timezone.datetime.max.time()))

    grant, raw_key = APIAccessGrant.issue(
        user=target_user, resource=resource, db_alias=get_current_db(),
        granted_by=request.user, expires_at=expires_at,
    )
    link = _build_grant_link(request, resource, raw_key)
    _email_grant_to_user(grant, link)

    messages.success(request, f"Accès API accordé à {target_user.get_full_name()} sur « {resource.name} ».")
    return render(request, 'api_gateway/grant_created.html', {
        'grant': grant,
        'link': link,
        'target_user': target_user,
    })


def _email_grant_to_user(grant, link):
    from academic_core.apps.notifications.utils import notify_users

    if not grant.user.email:
        return
    notify_users(
        recipients=[grant.user],
        notification_type='ABSENCE',
        title="Un accès API vous a été accordé",
        message=f"Vous avez désormais accès à la ressource API « {grant.resource.name} ».",
        priority='MEDIUM',
        send_email=True,
        email_heading="Un accès API vous a été accordé",
        email_paragraphs=[
            f"Vous avez désormais accès à la ressource API « {grant.resource.name} ».",
            f"Lien d'accès (à conserver, il ne sera plus affiché ensuite) :\n{link}",
            "Cet accès est en lecture seule (GET) et peut être révoqué à tout moment par "
            "l'administrateur de votre institut.",
        ],
    )


@login_required
def grants_list(request):
    if not _require_api_gateway_manage_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    grants = APIAccessGrant.objects.select_related('user', 'resource', 'granted_by').order_by('-created_at')
    return render(request, 'api_gateway/grants_list.html', {'grants': grants})


@login_required
def grant_revoke(request, grant_id):
    if not _require_api_gateway_manage_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    grant = get_object_or_404(APIAccessGrant, pk=grant_id)
    if request.method == 'POST':
        grant.revoked = True
        grant.revoked_at = timezone.now()
        grant.revoked_by = request.user
        grant.save(update_fields=['revoked', 'revoked_at', 'revoked_by'])
        messages.success(request, "Accès révoqué.")
    return redirect('api_gateway:grants_list')


@login_required
def access_requests_list(request):
    if not _require_api_gateway_manage_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    requests_qs = (
        APIAccessRequest.objects
        .select_related('requested_by', 'suggested_resource')
        .filter(status=APIAccessRequest.STATUS_PENDING)
        .order_by('created_at')
    )
    resources = APIResource.objects.filter(is_active=True)
    return render(request, 'api_gateway/access_requests_list.html', {
        'requests': requests_qs,
        'resources': resources,
    })


@login_required
def access_request_process(request, request_id):
    if not _require_api_gateway_manage_access(request.user):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard:index')

    access_request = get_object_or_404(APIAccessRequest, pk=request_id)
    if access_request.status != APIAccessRequest.STATUS_PENDING:
        messages.warning(request, "Cette demande a déjà été traitée.")
        return redirect('api_gateway:access_requests_list')

    if request.method != 'POST':
        return redirect('api_gateway:access_requests_list')

    from academic_core.apps.notifications.utils import notify_users
    from academic_core.db_router import get_current_db

    action = request.POST.get('action')
    access_request.processed_by = request.user
    access_request.processed_at = timezone.now()

    if action == 'approve':
        resource_id = request.POST.get('resource_id')
        resource = get_object_or_404(APIResource, pk=resource_id)
        access_request.status = APIAccessRequest.STATUS_APPROVED
        access_request.save(update_fields=['status', 'processed_by', 'processed_at'])

        grant, raw_key = APIAccessGrant.issue(
            user=access_request.requested_by, resource=resource, db_alias=get_current_db(),
            granted_by=request.user, request=access_request,
        )
        link = _build_grant_link(request, resource, raw_key)
        _email_grant_to_user(grant, link)
        messages.success(request, "Demande approuvée — l'accès API a été généré et envoyé à l'utilisateur.")
        return render(request, 'api_gateway/grant_created.html', {
            'grant': grant, 'link': link, 'target_user': access_request.requested_by,
        })

    elif action == 'reject':
        access_request.status = APIAccessRequest.STATUS_REJECTED
        access_request.admin_note = request.POST.get('admin_note', '').strip()
        access_request.save(update_fields=['status', 'admin_note', 'processed_by', 'processed_at'])
        if access_request.requested_by.email:
            notify_users(
                recipients=[access_request.requested_by],
                notification_type='ABSENCE',
                title="Votre demande d'accès API a été rejetée",
                message=(
                    "Votre demande d'accès API a été rejetée."
                    + (f" Motif : {access_request.admin_note}" if access_request.admin_note else "")
                ),
                priority='MEDIUM',
            )
        messages.warning(request, "Demande rejetée.")

    return redirect('api_gateway:access_requests_list')


# ---------------------------------------------------------------------------
# Espace utilisateur (tout utilisateur authentifié)
# ---------------------------------------------------------------------------

@login_required
def my_access_request_create(request):
    if request.method == 'POST':
        description = request.POST.get('description', '').strip()
        if not description:
            messages.error(request, "Veuillez décrire le besoin.")
        else:
            suggested_id = request.POST.get('suggested_resource') or None
            new_request = APIAccessRequest.objects.create(
                requested_by=request.user,
                description=description,
                suggested_resource_id=suggested_id,
            )
            _notify_institut_admins(new_request)
            messages.success(
                request,
                "Votre demande d'accès API a été envoyée à l'administrateur de l'institut."
            )
            return redirect('api_gateway:my_access_requests')

    resources = APIResource.objects.filter(is_active=True)
    preselected_id = request.GET.get('resource')
    preselected_id = int(preselected_id) if preselected_id and preselected_id.isdigit() else None
    return render(request, 'api_gateway/my_access_request_form.html', {
        'resources': resources,
        'preselected_id': preselected_id,
    })


@login_required
def my_access_requests(request):
    requests_qs = (
        APIAccessRequest.objects
        .filter(requested_by=request.user)
        .select_related('suggested_resource')
        .prefetch_related('grants__resource')
        .order_by('-created_at')
    )
    return render(request, 'api_gateway/my_access_requests.html', {'requests': requests_qs})
