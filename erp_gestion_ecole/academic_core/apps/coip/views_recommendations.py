from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import RecommendationRequestForm, RecommendationStatusForm
from .models import RecommendationRequest, RecommendationWorkflow
from .pdf_recommendation import generate_recommendation_pdf
from .permissions import coip_staff_required, get_student_for_user


@coip_staff_required
def recommendation_list(request):
    qs = RecommendationRequest.objects.select_related('student__user', 'assigned_to').order_by('-date_demande')
    status = request.GET.get('status')
    if status:
        qs = qs.filter(status=status)
    return render(request, 'coip/recommendation_list.html', {
        'requests': qs,
        'status_choices': RecommendationRequest.STATUT_CHOICES,
        'selected_status': status or '',
    })


@coip_staff_required
def recommendation_detail(request, pk):
    reco = get_object_or_404(RecommendationRequest.objects.select_related('student__user', 'assigned_to'), pk=pk)
    if request.method == 'POST':
        form = RecommendationStatusForm(request.POST)
        if form.is_valid():
            new_status = form.cleaned_data['status']
            comment = form.cleaned_data['comment']
            assigned_to = form.cleaned_data['assigned_to']
            if new_status == RecommendationRequest.STATUT_REJETEE and not comment:
                messages.error(request, "Un motif de rejet est requis (champ commentaire).")
            else:
                reco.status = new_status
                if assigned_to:
                    reco.assigned_to = assigned_to
                if new_status == RecommendationRequest.STATUT_REJETEE:
                    reco.motif_rejet = comment
                if new_status == RecommendationRequest.STATUT_LIVREE and not reco.date_livraison:
                    reco.date_livraison = timezone.now()
                reco.save()
                RecommendationWorkflow.objects.create(
                    recommendation=reco, status=new_status, comment=comment, changed_by=request.user,
                )
                messages.success(request, "Statut mis à jour.")
                return redirect('coip:recommendation_detail', pk=reco.pk)
        else:
            messages.error(request, "Formulaire invalide.")
    else:
        form = RecommendationStatusForm(initial={'status': reco.status, 'assigned_to': reco.assigned_to_id})
    return render(request, 'coip/recommendation_detail.html', {
        'reco': reco,
        'form': form,
        'history': reco.workflow_history.select_related('changed_by').all(),
    })


@coip_staff_required
def recommendation_pdf_generate(request, pk):
    reco = get_object_or_404(RecommendationRequest.objects.select_related('student__user', 'assigned_to'), pk=pk)
    buffer = generate_recommendation_pdf(request, reco)
    filename = f"recommandation_{reco.student.matricule}_{reco.pk}.pdf"
    reco.lettre_pdf.save(filename, ContentFile(buffer.getvalue()), save=True)
    messages.success(request, "Lettre PDF générée et attachée à la demande.")
    return redirect('coip:recommendation_detail', pk=reco.pk)


@login_required
def my_recommendations(request):
    student = get_student_for_user(request.user)
    if student is None:
        messages.error(request, "Cette page est réservée aux étudiants.")
        return redirect('dashboard:index')
    if request.method == 'POST':
        form = RecommendationRequestForm(request.POST)
        if form.is_valid():
            reco = form.save(commit=False)
            reco.student = student
            reco.save()
            messages.success(request, "Votre demande de recommandation a été soumise.")
            return redirect('coip:my_recommendations')
        else:
            messages.error(request, "Formulaire invalide.")
    else:
        form = RecommendationRequestForm()
    requests_qs = RecommendationRequest.objects.filter(student=student).order_by('-date_demande')
    return render(request, 'coip/my_recommendations.html', {'form': form, 'requests': requests_qs})
