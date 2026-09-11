"""Documents & Attestations RH.

Workflow demande : SOUMISE -> EN_TRAITEMENT -> SIGNEE -> DISPONIBLE (ou
REJETEE depuis SOUMISE/EN_TRAITEMENT). À l'étape "signer", le PDF de
l'attestation est généré automatiquement et rattaché à la demande.
Auto-service : tout agent peut demander une attestation ; le traitement
est réservé aux gestionnaires RH (cf. _HR_MANAGERS).
"""
import io

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.core.files.base import ContentFile

from .models import DocumentRequest, Document, IllegalTransition, transition, log_hr_event
from .views import _hr_required, _staff_required, _HR_MANAGERS
from .pdf_hr_docs import generate_document_request_pdf
from academic_core.apps.notifications.utils import notify_users
from academic_core.apps.notifications.models import Notification

DOCUMENT_TRANSITIONS = {
    ('SOUMISE', 'prendre_en_charge'):        'EN_TRAITEMENT',
    ('EN_TRAITEMENT', 'signer'):             'SIGNEE',
    ('SIGNEE', 'publier'):                   'DISPONIBLE',
    ('SOUMISE', 'rejeter'):                  'REJETEE',
    ('EN_TRAITEMENT', 'rejeter'):            'REJETEE',
}
NEXT_ACTION = {
    'SOUMISE':       ('prendre_en_charge', 'Prendre en charge'),
    'EN_TRAITEMENT': ('signer', 'Signer'),
    'SIGNEE':        ('publier', 'Publier'),
}


def _is_manager(request):
    return bool(request.user.role and request.user.role.name in _HR_MANAGERS)


# ── Auto-service ─────────────────────────────────────────────────────────────

@login_required
@_staff_required
def mes_attestations(request):
    if request.method == 'POST':
        # Le Super Admin n'est le personnel d'aucun institut en particulier —
        # DocumentRequest a une FK vers User dans la base tenant active, où sa
        # ligne User n'existe jamais localement (voir hr.views.ma_carte_personnel
        # pour le même garde-fou) : sans ceci, IntegrityError: FOREIGN KEY.
        if request.user.is_super_admin():
            messages.error(request, "Cette fonctionnalité n'est pas disponible pour le Super Administrateur.")
            return redirect('hr:mes_attestations')
        doc_request = DocumentRequest.objects.create(
            user=request.user,
            type_document=request.POST.get('type_document'),
        )
        log_hr_event('document_request', doc_request.pk, request.user, 'soumission', to_statut=doc_request.statut)
        messages.success(request, "Demande envoyée au service RH.")
        return redirect('hr:mes_attestations')
    requests_qs = DocumentRequest.objects.filter(user=request.user).select_related('document').order_by('-created_at')
    return render(request, 'hr/mes_attestations.html', {'requests': requests_qs})


# ── File RH ──────────────────────────────────────────────────────────────────

@login_required
@_hr_required
def document_request_list(request):
    if not _is_manager(request):
        messages.error(request, "Accès réservé aux gestionnaires RH.")
        return redirect('hr:dashboard')
    requests_qs = DocumentRequest.objects.select_related('user', 'assigned_to', 'document').order_by('-created_at')
    return render(request, 'hr/document_request_list.html', {
        'requests': requests_qs, 'NEXT_ACTION': NEXT_ACTION,
    })


@login_required
@_hr_required
def document_request_action(request, pk):
    doc_request = get_object_or_404(DocumentRequest.objects.select_related('user'), pk=pk)
    if not _is_manager(request):
        messages.error(request, "Accès réservé aux gestionnaires RH.")
        return redirect('hr:document_request_list')
    if request.method != 'POST':
        return redirect('hr:document_request_list')

    action = request.POST.get('action', '')
    from_statut = doc_request.statut
    try:
        new_statut = transition(DOCUMENT_TRANSITIONS, doc_request.statut, action)
    except IllegalTransition as exc:
        messages.error(request, str(exc))
        return redirect('hr:document_request_list')

    if action == 'signer':
        pdf_response = generate_document_request_pdf(request, doc_request)
        doc = Document.objects.create(
            user=doc_request.user,
            categorie=doc_request.get_type_document_display(),
            uploaded_by=request.user,
        )
        doc.fichier.save(f"{doc_request.type_document.lower()}_{doc_request.user.pk}.pdf", ContentFile(pdf_response.content))
        doc_request.document = doc
    doc_request.assigned_to = request.user
    doc_request.statut = new_statut
    doc_request.save()
    log_hr_event('document_request', doc_request.pk, request.user, action, from_statut=from_statut, to_statut=new_statut)

    if new_statut == DocumentRequest.STATUT_DISPONIBLE:
        notify_users([doc_request.user], Notification.TYPE_HR_DOCUMENT, "Document disponible",
                     f"Votre {doc_request.get_type_document_display().lower()} est disponible au téléchargement.",
                     link='/hr/mes-attestations/')
    elif new_statut == DocumentRequest.STATUT_REJETEE:
        notify_users([doc_request.user], Notification.TYPE_HR_DOCUMENT, "Demande rejetée",
                     f"Votre demande de {doc_request.get_type_document_display().lower()} a été rejetée.",
                     priority='HIGH', link='/hr/mes-attestations/')
    else:
        notify_users([doc_request.user], Notification.TYPE_HR_DOCUMENT, "Demande en cours de traitement",
                     f"Votre demande de {doc_request.get_type_document_display().lower()} est « {doc_request.get_statut_display()} ».",
                     link='/hr/mes-attestations/')

    messages.success(request, "Demande mise à jour.")
    return redirect('hr:document_request_list')


@login_required
@_hr_required
def document_request_delete(request, pk):
    doc_request = get_object_or_404(DocumentRequest, pk=pk)
    if not _is_manager(request):
        messages.error(request, "Accès réservé aux gestionnaires RH.")
        return redirect('hr:document_request_list')
    if request.method == 'POST':
        doc_request.delete()
        messages.success(request, "Demande supprimée.")
    return redirect('hr:document_request_list')


@login_required
@_staff_required
def document_download(request, pk):
    document = get_object_or_404(Document, pk=pk)
    is_manager = _is_manager(request)
    if not (is_manager or document.user_id == request.user.pk):
        messages.error(request, "Accès refusé.")
        return redirect('hr:dashboard')
    return FileResponse(document.fichier.open('rb'), as_attachment=True, filename=document.fichier.name.split('/')[-1])
