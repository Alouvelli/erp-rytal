from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, UpdateView

from .forms import ArchiveForm, ArchiveVersionForm
from .models import Archive
from .permissions import CoipStaffRequiredMixin, coip_staff_required


@coip_staff_required
def archive_list(request):
    qs = Archive.objects.select_related('depose_par').order_by('-created_at')
    q = request.GET.get('q')
    categorie = request.GET.get('categorie')
    if q:
        qs = qs.filter(Q(titre__icontains=q) | Q(tags__icontains=q))
    if categorie:
        qs = qs.filter(categorie=categorie)
    return render(request, 'coip/archive_list.html', {
        'archives': qs,
        'categorie_choices': Archive.CATEGORIE_CHOICES,
        'selected_categorie': categorie or '',
    })


@coip_staff_required
def archive_detail(request, pk):
    archive = get_object_or_404(Archive, pk=pk)
    if request.method == 'POST':
        form = ArchiveVersionForm(request.POST, request.FILES)
        if form.is_valid():
            version = form.save(commit=False)
            version.archive = archive
            version.uploaded_by = request.user
            version.save()
            archive.version = version.version
            archive.fichier = version.fichier
            archive.save(update_fields=['version', 'fichier', 'updated_at'])
            messages.success(request, "Nouvelle version déposée.")
            return redirect('coip:archive_detail', pk=archive.pk)
        else:
            messages.error(request, "Formulaire invalide.")
    else:
        form = ArchiveVersionForm(initial={'version': archive.version})
    return render(request, 'coip/archive_detail.html', {
        'archive': archive,
        'versions': archive.versions.select_related('uploaded_by').all(),
        'form': form,
    })


class ArchiveCreateView(CoipStaffRequiredMixin, CreateView):
    model = Archive
    form_class = ArchiveForm
    template_name = 'coip/archive_form.html'
    success_url = reverse_lazy('coip:archive_list')

    def form_valid(self, form):
        form.instance.depose_par = self.request.user
        messages.success(self.request, "Document archivé.")
        return super().form_valid(form)


class ArchiveUpdateView(CoipStaffRequiredMixin, UpdateView):
    model = Archive
    form_class = ArchiveForm
    template_name = 'coip/archive_form.html'
    success_url = reverse_lazy('coip:archive_list')

    def form_valid(self, form):
        messages.success(self.request, "Archive mise à jour.")
        return super().form_valid(form)


class ArchiveDeleteView(CoipStaffRequiredMixin, DeleteView):
    model = Archive
    template_name = 'coip/archive_confirm_delete.html'
    success_url = reverse_lazy('coip:archive_list')

    def form_valid(self, form):
        messages.success(self.request, "Archive supprimée.")
        return super().form_valid(form)
