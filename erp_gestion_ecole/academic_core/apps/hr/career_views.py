"""Carrière & Contrats — historique contractuel et affectations d'un employé.

S'intègre comme actions supplémentaires sur la fiche personnel existante
(hr:employe_fiche) plutôt que comme une page dédiée, à l'image de la
référence (onglets Contrats/Carrière sur EmployeDetailPage).
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

from .models import Contract, ContractAmendment, Assignment
from .views import _hr_required, _HR_MANAGERS, _get_staff_queryset


def _is_manager(request):
    return bool(request.user.role and request.user.role.name in _HR_MANAGERS)


@login_required
@_hr_required
def contract_create(request, user_pk):
    if not _is_manager(request):
        messages.error(request, "Accès réservé aux gestionnaires RH.")
        return redirect('hr:employe_fiche', pk=user_pk)
    employe = get_object_or_404(_get_staff_queryset(request), pk=user_pk)
    if request.method == 'POST':
        Contract.objects.create(
            user=employe,
            type_contrat=request.POST.get('type_contrat', Contract.TYPE_CDI),
            date_debut=request.POST.get('date_debut') or None,
            date_fin=request.POST.get('date_fin') or None,
            salaire_brut=request.POST.get('salaire_brut') or None,
            signe_le=request.POST.get('signe_le') or None,
            created_by=request.user,
        )
        messages.success(request, f"Contrat ajouté pour {employe.get_full_name()}.")
    return redirect('hr:employe_fiche', pk=user_pk)


@login_required
@_hr_required
def contract_amendment_create(request, pk):
    contract = get_object_or_404(Contract, pk=pk)
    if not _is_manager(request):
        messages.error(request, "Accès réservé aux gestionnaires RH.")
        return redirect('hr:employe_fiche', pk=contract.user_id)
    if request.method == 'POST':
        ContractAmendment.objects.create(
            contract=contract,
            date_effet=request.POST.get('date_effet') or None,
            objet=request.POST.get('objet', '').strip(),
            details=request.POST.get('details', '').strip(),
            created_by=request.user,
        )
        messages.success(request, "Avenant ajouté.")
    return redirect('hr:employe_fiche', pk=contract.user_id)


@login_required
@_hr_required
def assignment_create(request, user_pk):
    if not _is_manager(request):
        messages.error(request, "Accès réservé aux gestionnaires RH.")
        return redirect('hr:employe_fiche', pk=user_pk)
    employe = get_object_or_404(_get_staff_queryset(request), pk=user_pk)
    if request.method == 'POST':
        from academic_core.apps.academic_structure.models import Department
        dept_id = request.POST.get('department') or None
        dept = Department.objects.filter(pk=dept_id).first() if dept_id else None
        Assignment.objects.create(
            user=employe,
            department=dept,
            poste=request.POST.get('poste', '').strip(),
            date_effet=request.POST.get('date_effet') or None,
            type_affectation=request.POST.get('type_affectation', Assignment.TYPE_MOBILITE),
            note=request.POST.get('note', '').strip(),
            created_by=request.user,
        )
        messages.success(request, f"Affectation enregistrée pour {employe.get_full_name()}.")
    return redirect('hr:employe_fiche', pk=user_pk)
