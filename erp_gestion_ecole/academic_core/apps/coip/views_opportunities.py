from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, DeleteView, UpdateView

from .forms import JobApplicationForm, JobApplicationStatusForm, OpportunityForm
from .models import JobApplication, Opportunity
from .permissions import CoipStaffRequiredMixin, coip_staff_required, get_student_for_user


@coip_staff_required
def opportunity_list(request):
    qs = Opportunity.objects.select_related('partner', 'filiere_cible', 'niveau_cible').order_by('-created_at')
    q = request.GET.get('q')
    status = request.GET.get('status')
    if q:
        qs = qs.filter(Q(titre__icontains=q))
    if status:
        qs = qs.filter(status=status)
    return render(request, 'coip/opportunity_list.html', {
        'opportunities': qs,
        'status_choices': Opportunity.STATUT_CHOICES,
        'selected_status': status or '',
    })


@coip_staff_required
def opportunity_detail(request, pk):
    opp = get_object_or_404(Opportunity.objects.select_related('partner'), pk=pk)
    applications = opp.applications.select_related('student__user').order_by('-submitted_at')
    return render(request, 'coip/opportunity_detail.html', {'opp': opp, 'applications': applications})


@coip_staff_required
def job_application_update_status(request, pk):
    application = get_object_or_404(JobApplication, pk=pk)
    if request.method == 'POST':
        form = JobApplicationStatusForm(request.POST, instance=application)
        if form.is_valid():
            form.save()
            messages.success(request, "Statut de la candidature mis à jour.")
        else:
            messages.error(request, "Formulaire invalide.")
    return redirect('coip:opportunity_detail', pk=application.opportunity_id)


class OpportunityCreateView(CoipStaffRequiredMixin, CreateView):
    model = Opportunity
    form_class = OpportunityForm
    template_name = 'coip/opportunity_form.html'
    success_url = reverse_lazy('coip:opportunity_list')

    def form_valid(self, form):
        form.instance.publie_par = self.request.user
        messages.success(self.request, "Opportunité publiée.")
        return super().form_valid(form)


class OpportunityUpdateView(CoipStaffRequiredMixin, UpdateView):
    model = Opportunity
    form_class = OpportunityForm
    template_name = 'coip/opportunity_form.html'
    success_url = reverse_lazy('coip:opportunity_list')

    def form_valid(self, form):
        messages.success(self.request, "Opportunité mise à jour.")
        return super().form_valid(form)


class OpportunityDeleteView(CoipStaffRequiredMixin, DeleteView):
    model = Opportunity
    template_name = 'coip/opportunity_confirm_delete.html'
    success_url = reverse_lazy('coip:opportunity_list')

    def form_valid(self, form):
        messages.success(self.request, "Opportunité supprimée.")
        return super().form_valid(form)


# ── Espace étudiant ───────────────────────────────────────────────────────────

@login_required
def opportunities_browse(request):
    student = get_student_for_user(request.user)
    if student is None:
        messages.error(request, "Cette page est réservée aux étudiants.")
        return redirect('dashboard:index')
    today = timezone.localdate()
    qs = Opportunity.objects.filter(status=Opportunity.STATUT_PUBLIE).filter(
        Q(date_limite__isnull=True) | Q(date_limite__gte=today)
    ).select_related('partner', 'filiere_cible', 'niveau_cible').order_by('-created_at')
    applied_ids = set(JobApplication.objects.filter(student=student).values_list('opportunity_id', flat=True))
    return render(request, 'coip/opportunities_browse.html', {
        'opportunities': qs, 'applied_ids': applied_ids,
    })


@login_required
def opportunity_apply(request, pk):
    student = get_student_for_user(request.user)
    if student is None:
        messages.error(request, "Cette page est réservée aux étudiants.")
        return redirect('dashboard:index')
    opp = get_object_or_404(Opportunity, pk=pk, status=Opportunity.STATUT_PUBLIE)
    existing = JobApplication.objects.filter(opportunity=opp, student=student).first()
    if existing:
        messages.info(request, "Vous avez déjà postulé à cette opportunité.")
        return redirect('coip:opportunities_browse')
    if request.method == 'POST':
        form = JobApplicationForm(request.POST, request.FILES)
        if form.is_valid():
            application = form.save(commit=False)
            application.opportunity = opp
            application.student = student
            application.save()
            messages.success(request, "Candidature envoyée.")
            return redirect('coip:my_applications')
        else:
            messages.error(request, "Formulaire invalide.")
    else:
        form = JobApplicationForm()
    return render(request, 'coip/opportunity_apply.html', {'opp': opp, 'form': form})


@login_required
def my_applications(request):
    student = get_student_for_user(request.user)
    if student is None:
        messages.error(request, "Cette page est réservée aux étudiants.")
        return redirect('dashboard:index')
    applications = JobApplication.objects.filter(student=student).select_related('opportunity').order_by('-submitted_at')
    return render(request, 'coip/my_applications.html', {'applications': applications})
