from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import redirect, render, get_object_or_404
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy
from django.db.models import Q
from .models import Room, Building
from .forms import RoomForm


class _AdminResponsableMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return self.request.user.can_manage_dept()


# ── Bâtiments ─────────────────────────────────────────────────────────────────
class BuildingListView(_AdminResponsableMixin, ListView):
    model = Building
    template_name = 'rooms/buildings.html'
    context_object_name = 'buildings'

    def get_queryset(self):
        qs = Building.objects.prefetch_related('rooms').order_by('code')
        faculty = getattr(self.request, 'active_faculty', None)

        # Fallback pour INST_ADMIN sans département sélectionné
        if not faculty and self.request.user.is_inst_admin():
            config = getattr(self.request.user, 'institut_config', None)
            faculty = getattr(config, 'faculty', None) if config else None

        if faculty:
            qs = qs.filter(faculty=faculty)
        return qs

    def post(self, request, *args, **kwargs):
        action = request.POST.get('action')
        if action == 'create':
            code = request.POST.get('code', '').strip().upper()
            name = request.POST.get('name', '').strip()
            if not code or not name:
                messages.error(request, "Code et nom sont obligatoires.")
            elif Building.objects.filter(code=code).exists():
                messages.error(request, f"Le code « {code} » existe déjà.")
            else:
                faculty = getattr(request, 'active_faculty', None)
                Building.objects.create(code=code, name=name, faculty=faculty)
                messages.success(request, f"Bâtiment « {name} » créé.")
        elif action == 'edit':
            b = get_object_or_404(Building, pk=request.POST.get('pk'))
            b.code = request.POST.get('code', b.code).strip().upper()
            b.name = request.POST.get('name', b.name).strip()
            b.save()
            messages.success(request, f"Bâtiment « {b.name} » modifié.")
        elif action == 'delete':
            b = get_object_or_404(Building, pk=request.POST.get('pk'))
            name = b.name
            b.delete()
            messages.success(request, f"Bâtiment « {name} » supprimé.")
        return redirect('rooms:buildings')


# ── Salles ────────────────────────────────────────────────────────────────────
class RoomListView(_AdminResponsableMixin, ListView):
    model = Room
    template_name = 'rooms/list.html'
    context_object_name = 'rooms'

    def get_queryset(self):
        qs = Room.objects.select_related('building').order_by('building__code', 'code')
        faculty = getattr(self.request, 'active_faculty', None)

        # Fallback pour INST_ADMIN sans département sélectionné
        if not faculty and self.request.user.is_inst_admin():
            config = getattr(self.request.user, 'institut_config', None)
            faculty = getattr(config, 'faculty', None) if config else None

        if faculty:
            qs = qs.filter(building__faculty=faculty)
        elif not self.request.user.is_super_admin():
            qs = qs.none()
        return qs


class RoomCreateView(_AdminResponsableMixin, CreateView):
    model = Room
    form_class = RoomForm
    template_name = 'rooms/form.html'
    success_url = reverse_lazy('rooms:list')

    def form_valid(self, form):
        room = form.save(commit=False)
        # Auto-génère le code si vide
        if not room.code:
            base = room.name.upper().replace(' ', '')[:15]
            code = base
            n = 1
            while Room.objects.filter(code=code).exists():
                code = f"{base}-{n}"
                n += 1
            room.code = code
        room.save()
        messages.success(self.request, f"Salle « {room.name} » créée.")
        return redirect(self.success_url)

    def form_invalid(self, form):
        # Si seul `code` est vide, on re-essaie avec auto-génération
        if 'code' in form.errors and len(form.errors) == 1:
            data = form.data.copy()
            data['code'] = data.get('name', 'SALLE').upper().replace(' ', '')[:15]
            form = RoomForm(data)
            if form.is_valid():
                return self.form_valid(form)
        return super().form_invalid(form)


class RoomUpdateView(_AdminResponsableMixin, UpdateView):
    model = Room
    form_class = RoomForm
    template_name = 'rooms/form.html'
    success_url = reverse_lazy('rooms:list')


class RoomDeleteView(_AdminResponsableMixin, DeleteView):
    model = Room
    template_name = 'rooms/confirm_delete.html'
    success_url = reverse_lazy('rooms:list')

    def delete(self, request, *args, **kwargs):
        room = self.get_object()
        messages.success(request, f"Salle « {room.name} » supprimée.")
        return super().delete(request, *args, **kwargs)
