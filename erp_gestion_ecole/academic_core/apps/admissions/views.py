"""
Vues du portail public d'admission :
  - Publiques (aucune connexion requise) : catalogue de filières, création de
    compte candidat, vérification d'email.
  - Candidat authentifié (Role.CANDIDAT) : soumission de candidature, tableau
    de bord de suivi, poursuite de l'inscription (filière verrouillée), dépôt
    de preuve de paiement.
  - Chef de département : validation des candidatures de son département.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import make_password
from django.db.models import Q
from django.http import Http404, HttpResponse, HttpResponseNotAllowed
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django_ratelimit.decorators import ratelimit

from .models import Candidature
from .forms import (
    CandidateSignupForm, CandidatureForm, PaymentProofForm, ProgramContentForm,
    CandidatureDocumentsForm, DepartmentAdmissionsDatesForm,
)


def admission_landing_view(request):
    """
    Atteinte quand un visiteur saisit /admission/ sans code d'institut à la
    suite (ex. copie incomplète du lien fourni par son établissement). Le
    portail public de chaque institut vit à /admission/<code_institut>/ — il
    n'existe aucune page générique multi-instituts ici, donc on affiche une
    pop-up explicative plutôt qu'un 404 muet.
    """
    return render(request, 'admissions/admission_landing.html')


# ── Résolution de l'institut pour un visiteur anonyme ───────────────────────

def resolve_public_institut(institut_code):
    """
    Résout l'InstitutConfig depuis le code public (Faculty.code) et active sa
    base tenant pour le thread courant. 404 si code invalide ou institut
    suspendu. N'écrit JAMAIS request.session['_auth_db'] — cette activation ne
    doit pas contaminer une session de connexion normale (voir
    ResetDBMiddleware, qui lit cette clé à chaque requête authentifiée).
    """
    from academic_core.apps.academic_structure.models import InstitutConfig
    from academic_core.tenant_databases import register_tenant_db
    from academic_core.db_router import set_current_db

    config = InstitutConfig.objects.using('default').select_related('faculty').filter(
        faculty__code__iexact=institut_code, actif=True,
    ).first()
    if not config or not config.db_alias:
        raise Http404("Institut introuvable ou indisponible.")

    alias = register_tenant_db(config.db_alias)
    if not alias:
        raise Http404("Institut indisponible.")
    set_current_db(alias)
    return config


# ── Catalogue public ─────────────────────────────────────────────────────────

DEPARTMENT_COLOR_PALETTE = [
    {'bg': '#eff6ff', 'accent': '#003d82'},
    {'bg': '#f0fdf4', 'accent': '#15803d'},
    {'bg': '#f5f3ff', 'accent': '#6d28d9'},
    {'bg': '#fff7ed', 'accent': '#c2410c'},
    {'bg': '#f0fdfa', 'accent': '#0f766e'},
    {'bg': '#fdf2f8', 'accent': '#be185d'},
    {'bg': '#fffbeb', 'accent': '#b45309'},
    {'bg': '#f8fafc', 'accent': '#334155'},
]


def portail_view(request, institut_code):
    config = resolve_public_institut(institut_code)
    from academic_core.apps.academic_structure.models import Program, AcademicYear

    programs = Program.objects.filter(
        ouvert_admissions=True, department__is_active=True,
    ).select_related('department').order_by('department__name', 'level', 'name')
    current_year = AcademicYear.objects.filter(is_current=True).first()

    # Regroupement par département puis par niveau : chaque département créé
    # par l'Admin Institut apparaît automatiquement sur le portail dès qu'il
    # compte au moins une filière ouverte aux admissions
    # (Program.ouvert_admissions=True par défaut à la création — aucune étape
    # de publication manuelle requise), et ses filières y sont regroupées par
    # niveau (Program.level).
    departments = {}
    for p in programs:
        dept = p.department
        entry = departments.setdefault(dept.pk, {'department': dept, 'levels': {}})
        level_key = p.level or ''
        level_progs = entry['levels'].setdefault(level_key, [])
        restantes = p.places_restantes(current_year) if current_year else None
        level_progs.append({'program': p, 'places_restantes': restantes})

    departments_data = []
    for index, entry in enumerate(sorted(departments.values(), key=lambda d: d['department'].name)):
        levels_data = [
            {'level': level_key or 'Niveau non précisé', 'programs': progs}
            for level_key, progs in sorted(entry['levels'].items(), key=lambda kv: (kv[0] == '', kv[0]))
        ]
        departments_data.append({
            'department': entry['department'],
            'levels': levels_data,
            'color': DEPARTMENT_COLOR_PALETTE[index % len(DEPARTMENT_COLOR_PALETTE)],
            'admissions_ouvertes': entry['department'].admissions_ouvertes(),
        })

    return render(request, 'admissions/portail.html', {
        'config': config, 'institut_code': institut_code, 'departments_data': departments_data,
    })


def filiere_detail_view(request, institut_code, program_code):
    config = resolve_public_institut(institut_code)
    from academic_core.apps.academic_structure.models import Program, AcademicYear

    program = get_object_or_404(Program, code__iexact=program_code, ouvert_admissions=True)
    current_year = AcademicYear.objects.filter(is_current=True).first()
    places_restantes = program.places_restantes(current_year) if current_year else None

    return render(request, 'admissions/filiere_detail.html', {
        'config': config, 'institut_code': institut_code, 'program': program,
        'places_restantes': places_restantes,
        'admissions_ouvertes': program.department.admissions_ouvertes(),
    })


# ── Création de compte candidat + vérification email ────────────────────────

def _purge_candidat_account(user, db_alias):
    """
    Supprime définitivement un compte candidat (candidature, notifications,
    tokens de vérification, copies 'default' + tenant du compte). Utilisé à
    la fois par la suppression manuelle depuis « Comptes candidats » (chef de
    département) et par une nouvelle tentative d'inscription réutilisant un
    email déjà associé à un compte non encore payé (voir
    CandidateSignupForm.clean_email et signup_view).

    Si le candidat a déjà un dossier Student/Enrollment (inscription
    finalisée, paiements enregistrés), la suppression de sa ligne `users`
    dans la base tenant entraîne, via les contraintes de clé étrangère en
    cascade réelles en base, la suppression de son Student, ses Enrollment,
    échéances (PaymentInstallment) et paiements caisse (CaissePayment) — tout
    l'historique disparaît avec le compte, sans rangée orpheline.
    """
    from django.db import connections, transaction
    from academic_core.apps.accounts.models import User
    from academic_core.apps.notifications.models import Notification

    with transaction.atomic(using=db_alias):
        Candidature.objects.filter(user=user).delete()
        Notification.objects.using(db_alias).filter(recipient=user).delete()
        with connections[db_alias].cursor() as cur:
            cur.execute('DELETE FROM users WHERE id = %s', [user.pk])
    User.objects.using('default').filter(pk=user.pk).delete()


def _open_programs_queryset(base_qs=None):
    """
    Filtre un queryset de Program pour ne garder que les filières réellement
    ouvertes à la candidature : la filière elle-même (Program.ouvert_admissions)
    ET la fenêtre de dates d'inscription de son département (voir
    Department.admissions_ouvertes) — un département hors de sa fenêtre reste
    visible sur le portail (voir portail_view/filiere_detail_view) mais ne
    doit plus accepter de nouvelle candidature.
    """
    from academic_core.apps.academic_structure.models import Program
    qs = base_qs if base_qs is not None else Program.objects.all()
    today = timezone.now().date()
    return qs.filter(ouvert_admissions=True).filter(
        Q(department__admissions_date_ouverture__isnull=True) | Q(department__admissions_date_ouverture__lte=today)
    ).filter(
        Q(department__admissions_date_fermeture__isnull=True) | Q(department__admissions_date_fermeture__gte=today)
    )


def _resolve_open_program(program_code):
    """Résout une filière ouverte aux candidatures par son code, dans
    l'institut (base tenant) actuellement actif — None si absente/invalide/
    fermée (filière fermée ou département hors de sa fenêtre d'inscription),
    pour ne jamais bloquer l'inscription sur un paramètre invalide."""
    if not program_code:
        return None
    from academic_core.apps.academic_structure.models import Program
    return _open_programs_queryset(Program.objects.filter(code__iexact=program_code)).first()


def _can_track_admissions(user):
    """
    Rôles institut (non rattachés à un seul département) autorisés à suivre
    candidatures/comptes candidats/dates d'inscription de tout l'institut :
    la Direction Communication (rôle dédié ADMIN_COM), et — comme aucun
    compte ADMIN_COM n'existe forcément dans chaque institut — l'Admin
    plateforme et l'Admin d'institut, qui gèrent déjà tout le reste de la
    plateforme. Volontairement plus restreint que is_admin() (qui couvre
    aussi des rôles opérationnels sans rapport, ex. Trésorier/Caissier).
    """
    return user.is_communication() or user.is_super_admin() or user.is_inst_admin()


def _admissions_department_scope(user):
    """
    Ensemble des `department_id` que cet utilisateur peut gérer sur le
    portail d'admission (candidatures, comptes candidats, dates
    d'ouverture/fermeture) : tous les départements de l'institut pour les
    rôles institut (voir _can_track_admissions), un seul (le sien) pour un
    chef de département. Ensemble vide si l'utilisateur n'a accès à aucun
    département — chaque vue appelante reste responsable de son propre
    contrôle d'accès global.
    """
    if _can_track_admissions(user):
        from academic_core.apps.academic_structure.models import Department
        return set(Department.objects.values_list('pk', flat=True))
    if user.department_id:
        return {user.department_id}
    return set()


@ratelimit(key='ip', rate='5/h', method='POST', block=True)
def signup_view(request, institut_code):
    config = resolve_public_institut(institut_code)
    from academic_core.apps.accounts.models import User, Role
    from academic_core.apps.accounts.db_utils import sync_user_to_institute_db

    if request.method == 'POST':
        form = CandidateSignupForm(request.POST)
        preselected_program = _resolve_open_program(request.POST.get('program_code'))
        if form.is_valid():
            cd = form.cleaned_data

            from django.db.models import Q
            existing = User.objects.using('default').filter(
                Q(email__iexact=cd['email']) | Q(username__iexact=cd['email'])
            ).first()
            if existing:
                # clean_email() n'a laissé passer que les comptes n'ayant pas
                # encore finalisé de paiement — on les remplace silencieusement.
                # Best-effort : un échec de purge ne doit jamais bloquer la
                # création du nouveau compte.
                try:
                    _purge_candidat_account(existing, config.db_alias)
                except Exception:
                    pass

            role = Role.objects.using('default').filter(name=Role.CANDIDAT).first()
            user = User.objects.using('default').create(
                first_name=cd['first_name'],
                last_name=cd['last_name'],
                email=cd['email'],
                username=cd['email'],
                phone=cd.get('phone', ''),
                password=make_password(cd['password']),
                role=role,
                is_active=False,
            )
            sync_user_to_institute_db(user, config.db_alias)

            # Filière choisie sur le portail (bouton « Inscrivez-vous
            # maintenant » de filiere_detail.html, relayée par le champ caché
            # program_code) : la candidature est créée dès l'inscription,
            # pour que le candidat n'ait pas à la re-choisir après connexion
            # (voir candidature_view, qui redirige déjà vers le tableau de
            # bord dès qu'une Candidature existe). Le chef de département
            # n'est notifié qu'à la vérification de l'email (voir
            # verify_email_view) — pas avant, tant que le compte n'est pas
            # confirmé réel.
            if preselected_program:
                Candidature.objects.create(user=user, program=preselected_program)

            from academic_core.apps.accounts.models import EmailVerificationToken
            from academic_core.apps.notifications.utils import send_branded_email
            _token_obj, raw_token = EmailVerificationToken.issue(user)
            verify_url = request.build_absolute_uri(
                reverse('admission_portal:verifier_email', kwargs={'institut_code': institut_code, 'token': raw_token})
            )
            filiere_txt = f" pour la filière « {preselected_program.name} »" if preselected_program else ''
            send_branded_email(
                to_email=user.email,
                subject="Vérifiez votre adresse email",
                heading="Bienvenue — confirmez votre adresse email",
                paragraphs=[
                    f"Bonjour {user.get_full_name()},",
                    f"Merci de votre inscription sur le portail d'admission de {config.nom or config.sigle}{filiere_txt}.",
                    "Veuillez confirmer votre adresse email en cliquant sur le bouton ci-dessous. Ce lien expire dans 48 heures.",
                ],
                cta_url=verify_url,
                cta_label="Vérifier mon adresse email",
                fallback_text=(
                    f"Bonjour {user.get_full_name()},\n\n"
                    f"Merci de votre inscription sur le portail d'admission de {config.nom or config.sigle}{filiere_txt}.\n"
                    f"Veuillez confirmer votre adresse email en cliquant sur ce lien :\n{verify_url}\n\n"
                    f"Ce lien expire dans 48 heures.\n"
                ),
            )
            return render(request, 'admissions/signup_done.html', {
                'config': config, 'institut_code': institut_code, 'current_step': 1,
            })
    else:
        form = CandidateSignupForm()
        preselected_program = _resolve_open_program(request.GET.get('filiere'))

    return render(request, 'admissions/signup.html', {
        'form': form, 'config': config, 'institut_code': institut_code,
        'preselected_program': preselected_program, 'current_step': 1,
    })


def verify_email_view(request, institut_code, token):
    config = resolve_public_institut(institut_code)
    from academic_core.apps.accounts.models import EmailVerificationToken
    from django.db import connections

    token_obj = EmailVerificationToken.objects.using('default').filter(token=token).first()
    if not token_obj or not token_obj.is_valid():
        messages.error(request, "Ce lien de vérification est invalide ou a expiré.")
        return redirect('admission_portal:portail', institut_code=institut_code)

    user = token_obj.user
    user.is_active = True
    user.save(using='default', update_fields=['is_active'])

    try:
        with connections[config.db_alias].cursor() as cur:
            cur.execute('UPDATE users SET is_active = TRUE WHERE id = %s', [user.pk])
    except Exception:
        pass

    token_obj.used = True
    token_obj.save(using='default', update_fields=['used'])

    # Si une candidature a été créée dès l'inscription (filière choisie sur
    # le portail — voir signup_view), le chef de département n'est notifié
    # qu'à présent, une fois le compte confirmé réel.
    candidature = getattr(user, 'candidature', None)
    if candidature:
        from academic_core.apps.notifications.utils import notify_candidature_pending
        notify_candidature_pending(candidature, request=request)

    messages.success(request, "Votre compte a été vérifié avec succès. Connectez-vous pour continuer.")
    return redirect('accounts:login')


def _get_usable_payment_config(institut_code):
    """Retourne (config_institut, payment_config) ou lève Http404."""
    config = resolve_public_institut(institut_code)
    from academic_core.apps.academic_structure.models import InstitutPaymentConfig
    payment_config = InstitutPaymentConfig.objects.using('default').filter(institut_config=config).first()
    return config, payment_config


@csrf_exempt
def wave_webhook_view(request, institut_code):
    """
    Point d'entrée public appelé par Wave (checkout.session.completed — voir
    candidat_paiement_en_ligne_view) pour signaler qu'une session de paiement
    a été complétée. Ne fait JAMAIS confiance au contenu de cette requête
    pour valider le paiement : on ré-interroge Wave (confirm_wave_checkout)
    pour obtenir le statut authentique avant toute finalisation — seule cette
    confirmation authentifiée déclenche finalize_enrollment_payment.
    """
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    try:
        _config, payment_config = _get_usable_payment_config(institut_code)
    except Http404:
        return HttpResponse(status=404)

    from academic_core.apps.accounting.models import OnlinePaymentTransaction
    from academic_core.apps.accounting.payment_gateway import confirm_wave_checkout, PaymentGatewayError
    import json

    if not payment_config or not payment_config.wave_usable():
        return HttpResponse(status=400)

    try:
        payload = json.loads(request.body.decode('utf-8', errors='ignore') or '{}')
    except ValueError:
        payload = {}
    session_id = (payload.get('data') or {}).get('id') or payload.get('id')
    if not session_id:
        return HttpResponse(status=400)

    txn = OnlinePaymentTransaction.objects.filter(invoice_token=session_id).select_related('enrollment').first()
    if not txn or txn.status == OnlinePaymentTransaction.STATUS_COMPLETED:
        # Transaction inconnue ou déjà traitée — répondre 200 pour éviter les
        # relances agressives de Wave, sans rien refaire.
        return HttpResponse(status=200)

    try:
        confirmed = confirm_wave_checkout(payment_config, session_id)
    except PaymentGatewayError:
        return HttpResponse(status=502)

    txn.raw_response = json.dumps(confirmed)[:9000]

    if confirmed.get('payment_status') == 'succeeded':
        txn.status = OnlinePaymentTransaction.STATUS_COMPLETED
        txn.confirmed_at = timezone.now()
        txn.save()

        from academic_core.apps.accounting.services import finalize_enrollment_payment
        finalize_enrollment_payment(
            txn.enrollment, payment_date=timezone.now().date(), validated_by=None,
            notes=f"Payé en ligne via {txn.get_provider_display()} — réf. {session_id}",
            request=request,
        )
    else:
        txn.status = OnlinePaymentTransaction.STATUS_FAILED
        txn.save()

    return HttpResponse(status=200)


@csrf_exempt
def orange_money_webhook_view(request, institut_code):
    """
    Point d'entrée public appelé par Orange Money (notif_url — voir
    candidat_paiement_en_ligne_view) pour signaler qu'un paiement a été
    complété. Ne fait JAMAIS confiance au contenu de cette requête pour
    valider le paiement : on ré-interroge Orange Money
    (confirm_orange_money_payment) pour obtenir le statut authentique avant
    toute finalisation — seule cette confirmation authentifiée déclenche
    finalize_enrollment_payment.

    Orange Money appelle notif_url avec les paramètres en query string
    (GET) ou en corps de requête (POST) selon la configuration du compte
    marchand — on accepte les deux.
    """
    try:
        _config, payment_config = _get_usable_payment_config(institut_code)
    except Http404:
        return HttpResponse(status=404)

    from academic_core.apps.accounting.models import OnlinePaymentTransaction
    from academic_core.apps.accounting.payment_gateway import confirm_orange_money_payment, PaymentGatewayError
    import json

    if not payment_config or not payment_config.orange_money_usable():
        return HttpResponse(status=400)

    params = request.POST if request.method == 'POST' else request.GET
    pay_token = params.get('pay_token') or params.get('payToken')
    order_id = params.get('order_id') or params.get('orderId')
    amount = params.get('amount')
    if not pay_token or not order_id:
        return HttpResponse(status=400)

    txn = OnlinePaymentTransaction.objects.filter(invoice_token=pay_token).select_related('enrollment').first()
    if not txn or txn.status == OnlinePaymentTransaction.STATUS_COMPLETED:
        # Transaction inconnue ou déjà traitée — répondre 200 pour éviter les
        # relances agressives d'Orange Money, sans rien refaire.
        return HttpResponse(status=200)

    try:
        confirmed = confirm_orange_money_payment(
            payment_config, pay_token=pay_token, order_id=order_id,
            amount=amount or txn.amount,
        )
    except PaymentGatewayError:
        return HttpResponse(status=502)

    txn.raw_response = json.dumps(confirmed)[:9000]

    if (confirmed.get('status') or '').upper() == 'SUCCESS':
        txn.status = OnlinePaymentTransaction.STATUS_COMPLETED
        txn.confirmed_at = timezone.now()
        txn.save()

        from academic_core.apps.accounting.services import finalize_enrollment_payment
        finalize_enrollment_payment(
            txn.enrollment, payment_date=timezone.now().date(), validated_by=None,
            notes=f"Payé en ligne via {txn.get_provider_display()} — réf. {pay_token}",
            request=request,
        )
    else:
        txn.status = OnlinePaymentTransaction.STATUS_FAILED
        txn.save()

    return HttpResponse(status=200)


# ── Candidat authentifié ─────────────────────────────────────────────────────

@login_required
def candidature_view(request):
    if not request.user.is_candidat():
        return redirect('dashboard:index')
    if hasattr(request.user, 'candidature'):
        return redirect('candidat:candidat_dashboard')

    from academic_core.apps.academic_structure.models import Program
    programs = _open_programs_queryset(Program.objects.all()).select_related('department')

    if request.method == 'POST':
        form = CandidatureForm(request.POST, programs_queryset=programs)
        if form.is_valid():
            candidature = Candidature.objects.create(
                user=request.user,
                program=form.cleaned_data['program'],
                motivation=form.cleaned_data.get('motivation', ''),
            )
            # Rattachement automatique au département de la filière choisie —
            # uniquement sur la copie tenant (celle résolue en priorité au
            # login par MultiDBAuthBackend, voir accounts/backends.py) : le
            # département n'existe réellement que dans cette base, écrire
            # aussi sur 'default' violerait sa contrainte de clé étrangère
            # (departments n'y est pas fiablement répliqué, contrairement à
            # InstitutConfig/Faculty).
            request.user.department = candidature.program.department
            request.user.save(update_fields=['department'])

            from academic_core.apps.notifications.utils import notify_candidature_pending
            notify_candidature_pending(candidature, request=request)
            messages.success(request, "Votre candidature a été soumise avec succès.")
            return redirect('candidat:candidat_dashboard')
    else:
        form = CandidatureForm(programs_queryset=programs)

    return render(request, 'admissions/candidature_form.html', {'form': form, 'current_step': 2})


@login_required
def candidat_dashboard_view(request):
    """
    « Mon Dossier de Candidature » — page unique du candidat, faisant office
    de suivi étape par étape : candidature → pièces justificatives →
    validation du département → inscription → paiement → dossier finalisé
    (voir base.html, sidebar réduite à ce seul onglet pour Role.CANDIDAT).
    """
    if not request.user.is_candidat():
        return redirect('dashboard:index')

    candidature = getattr(request.user, 'candidature', None)
    if not candidature:
        return redirect('candidat:candidature')

    enrollment = None
    payment_proof = None
    student = getattr(request.user, 'student_profile', None)
    if student:
        enrollment = student.enrollments.order_by('-enrollment_date').first()
        if enrollment:
            payment_proof = enrollment.payment_proofs.order_by('-submitted_at').first()

    documents_completes = candidature.documents_completes()
    montant_a_regler = None
    if enrollment:
        montant_a_regler = enrollment.remaining_amount or enrollment.total_fees or enrollment.frais_generaux

    return render(request, 'admissions/candidat_dashboard.html', {
        'candidature': candidature, 'enrollment': enrollment, 'payment_proof': payment_proof,
        'documents_completes': documents_completes, 'montant_a_regler': montant_a_regler,
    })


@login_required
def candidat_documents_view(request):
    """
    Dépôt des pièces justificatives de validation de la candidature — CNI/
    diplôme du BAC pour tous, + relevé du BAC/2 photos pour les 1ère année,
    + bulletins des semestres antérieurs (multi-fichiers, gérés hors du Form)
    pour les 2ième à 5ième année. Chaque soumission des champs à instance
    unique (CNI, diplôme, relevé, photos) REMPLACE le fichier précédent ;
    les bulletins s'accumulent au fil des dépôts.
    """
    if not request.user.is_candidat():
        return redirect('dashboard:index')

    candidature = getattr(request.user, 'candidature', None)
    if not candidature:
        return redirect('candidat:candidature')

    from .models import CandidatureDocument

    if request.method == 'POST':
        form = CandidatureDocumentsForm(request.POST, request.FILES)
        bulletins = request.FILES.getlist('bulletins')
        if form.is_valid():
            cd = form.cleaned_data
            candidature.niveau_entree = cd['niveau_entree']
            candidature.save(update_fields=['niveau_entree'])

            single_slot_map = {
                CandidatureDocument.TYPE_CNI_PASSEPORT: cd.get('cni_passeport'),
                CandidatureDocument.TYPE_DIPLOME_BAC: cd.get('diplome_bac'),
                CandidatureDocument.TYPE_RELEVE_BAC: cd.get('releve_bac'),
            }
            for doc_type, fichier in single_slot_map.items():
                if fichier:
                    CandidatureDocument.objects.filter(candidature=candidature, document_type=doc_type).delete()
                    CandidatureDocument.objects.create(candidature=candidature, document_type=doc_type, fichier=fichier)

            photos = [cd.get('photo_identite_1'), cd.get('photo_identite_2')]
            if any(photos):
                CandidatureDocument.objects.filter(
                    candidature=candidature, document_type=CandidatureDocument.TYPE_PHOTO_IDENTITE,
                ).delete()
                for photo in photos:
                    if photo:
                        CandidatureDocument.objects.create(
                            candidature=candidature, document_type=CandidatureDocument.TYPE_PHOTO_IDENTITE,
                            fichier=photo,
                        )

            from .forms import _validate_document_file
            from django.core.exceptions import ValidationError
            for bulletin in bulletins:
                try:
                    _validate_document_file(bulletin)
                except ValidationError:
                    messages.error(request, f"« {bulletin.name} » n'a pas été accepté (format ou taille invalide).")
                    continue
                CandidatureDocument.objects.create(
                    candidature=candidature, document_type=CandidatureDocument.TYPE_BULLETIN,
                    libelle=bulletin.name, fichier=bulletin,
                )

            messages.success(request, "Vos pièces justificatives ont été enregistrées.")
            return redirect('candidat:candidat_dashboard')
    else:
        form = CandidatureDocumentsForm(initial={'niveau_entree': candidature.niveau_entree})

    existing_docs = candidature.documents.all()
    return render(request, 'admissions/candidat_documents.html', {
        'form': form, 'candidature': candidature, 'existing_docs': existing_docs,
        'current_step': 3,
    })


@login_required
def candidat_inscription_view(request):
    """
    Poursuite de l'inscription après validation de la candidature — réutilise
    StudentUserForm (students/forms.py), sans le champ target_institut (déjà
    résolu via la session) et avec les classes restreintes à la filière
    choisie lors de la candidature (jamais les autres filières du département
    ni de l'institut).
    """
    if not request.user.is_candidat():
        return redirect('dashboard:index')

    candidature = getattr(request.user, 'candidature', None)
    if not candidature or not candidature.is_validated:
        return redirect('candidat:candidat_dashboard')

    student = getattr(request.user, 'student_profile', None)
    if student:
        return redirect('candidat:candidat_dashboard')

    from academic_core.apps.academic_structure.models import Class, AcademicYear, Level
    from academic_core.apps.students.forms import StudentUserForm
    from academic_core.apps.students.services import create_student_enrollment, generate_matricule
    from academic_core.db_router import get_current_db
    from .models import Candidature

    current_year = AcademicYear.objects.filter(is_current=True).first()
    classes = Class.objects.filter(program=candidature.program)
    if current_year:
        classes = classes.filter(academic_year=current_year)

    # Restreint (quand possible) aux classes du niveau LMD correspondant à
    # l'année d'entrée déclarée par le candidat à l'étape « Pièces
    # justificatives » (voir Candidature.niveau_entree) : 1ère année → L1,
    # 2ième → L2, 3ième → L3, 4ième → M1, 5ième → M2 — matché via
    # Class.level (Level.order), jamais par correspondance de nom/texte
    # (le libellé des classes n'est pas fiable, ex. fautes de frappe).
    # Si aucune classe du niveau attendu n'existe, on retombe sans filtrer
    # (comportement inchangé) plutôt que de bloquer le candidat.
    NIVEAU_TO_LEVEL_ORDER = {
        Candidature.NIVEAU_L1: 1,
        Candidature.NIVEAU_L2: 2,
        Candidature.NIVEAU_L3: 3,
        Candidature.NIVEAU_L4: 4,
        Candidature.NIVEAU_L5: 5,
    }
    matched_class = None
    target_order = NIVEAU_TO_LEVEL_ORDER.get(candidature.niveau_entree)
    if target_order:
        matched_level = Level.objects.filter(order=target_order).first()
        if matched_level:
            level_classes = classes.filter(level=matched_level)
            if level_classes.exists():
                classes = level_classes
                if classes.count() == 1:
                    matched_class = classes.first()

    class _LockedForm(StudentUserForm):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            del self.fields['target_institut']
            # Bourse : décision administrative, hors périmètre du candidat
            # qui s'inscrit lui-même — gérée plus tard par le personnel
            # (formulaire de gestion des étudiants), pas ici.
            del self.fields['is_boursier']
            del self.fields['partenaire_bourse']
            self.fields['class_group'].choices = (
                [('', '— Sélectionner une classe —')] + [(c.pk, c.name) for c in classes]
            )
            self.fields['academic_year'].choices = (
                [(current_year.pk, str(current_year))] if current_year else []
            )
            # Générés/déjà connus automatiquement (voir prefill ci-dessous) —
            # affichés en lecture seule pour rester cohérents avec le
            # principe du formulaire d'inscription du personnel (matricule
            # auto-généré si non fourni), tout en restant soumis avec le
            # formulaire (readonly, pas disabled).
            self.fields['matricule'].widget.attrs['readonly'] = True
            self.fields['username'].widget.attrs['readonly'] = True
            self.fields['username'].help_text = "Votre identifiant de connexion reste votre adresse email."
            self.fields['matricule'].help_text = "Généré automatiquement."

    # Le matricule est pré-généré ici (pas seulement en secours côté
    # create_student_enrollment) pour qu'il soit visible et STABLE tout au
    # long du remplissage du formulaire : la valeur affichée est celle
    # réellement soumise (champ readonly, pas disabled), reprise telle
    # quelle par create_student_enrollment plutôt que régénérée.
    matricule_ref_class = matched_class or classes.first()
    generated_matricule = (
        generate_matricule(matricule_ref_class, current_year) if matricule_ref_class else ''
    )

    prefill = {
        'user_pk': request.user.pk,
        'class_group': matched_class.pk if matched_class else None,
        'first_name': request.user.first_name,
        'last_name': request.user.last_name,
        'email': request.user.email,
        # L'identifiant de connexion de l'étudiant est désormais son email
        # (déjà son identifiant de connexion candidat depuis l'inscription
        # au portail — voir signup_view) plutôt qu'un identifiant à saisir.
        'username': request.user.email,
        'phone': request.user.phone,
        'matricule': generated_matricule,
    }

    # Photo d'identité déjà déposée à l'étape « Pièces justificatives » (voir
    # CandidatureDocument.TYPE_PHOTO_IDENTITE) — montrée en aperçu direct
    # dans ce formulaire (voir candidat_inscription.html) et réutilisée
    # automatiquement à la soumission si le candidat n'en importe pas une
    # nouvelle, pour ne jamais la lui redemander une troisième fois.
    from .models import CandidatureDocument
    identity_doc = candidature.documents.filter(
        document_type=CandidatureDocument.TYPE_PHOTO_IDENTITE,
    ).order_by('uploaded_at').first()

    if request.method == 'POST':
        form = _LockedForm(request.POST, request.FILES, initial=prefill)
        if form.is_valid():
            cd = form.cleaned_data
            class_group = classes.filter(pk=cd['class_group']).first()
            if not class_group:
                messages.error(request, "Classe invalide pour cette filière.")
                return render(request, 'admissions/candidat_inscription.html', {
                    'form': form, 'candidature': candidature, 'identity_doc': identity_doc,
                    'current_step': 4,
                })

            places = candidature.program.places_restantes(current_year) if current_year else None
            if places is not None and places <= 0:
                messages.error(request, "Cette filière n'a plus de places disponibles.")
                return render(request, 'admissions/candidat_inscription.html', {
                    'form': form, 'candidature': candidature, 'identity_doc': identity_doc,
                    'current_step': 4,
                })

            if not cd.get('photo') and identity_doc and identity_doc.fichier:
                from django.core.files.base import ContentFile
                filename = identity_doc.fichier.name.rsplit('/', 1)[-1]
                cd['photo'] = ContentFile(identity_doc.fichier.read(), name=filename)

            db_alias = get_current_db()
            _user, _student, enrollment, _matricule, _pw = create_student_enrollment(
                db_alias=db_alias, cd=cd, class_group=class_group,
                academic_year=current_year, user=request.user,
            )
            from academic_core.apps.notifications.utils import notify_inscription_pending
            notify_inscription_pending(enrollment, request=request)
            messages.success(request, "Votre dossier d'inscription a été soumis — en attente de traitement.")
            return redirect('candidat:candidat_dashboard')
    else:
        form = _LockedForm(initial=prefill)

    return render(request, 'admissions/candidat_inscription.html', {
        'form': form, 'candidature': candidature, 'identity_doc': identity_doc,
        'current_step': 4,
    })


@login_required
def candidat_paiement_view(request):
    if not request.user.is_candidat():
        return redirect('dashboard:index')

    student = getattr(request.user, 'student_profile', None)
    if not student:
        return redirect('candidat:candidat_dashboard')

    from academic_core.apps.students.models import Enrollment
    enrollment = student.enrollments.filter(status=Enrollment.STATUS_PENDING_CAISSE).order_by('-enrollment_date').first()
    if not enrollment:
        return redirect('candidat:candidat_dashboard')

    if request.method == 'POST':
        form = PaymentProofForm(request.POST, request.FILES)
        if form.is_valid():
            from academic_core.apps.accounting.models import PaymentProof
            cd = form.cleaned_data
            proof = PaymentProof.objects.create(
                enrollment=enrollment,
                moyen_paiement=cd['moyen_paiement'],
                montant_declare=cd['montant_declare'],
                reference_paiement=cd.get('reference_paiement', ''),
                piece_justificative=cd['piece_justificative'],
            )
            from academic_core.apps.notifications.utils import notify_payment_proof_pending
            notify_payment_proof_pending(proof, request=request)
            messages.success(request, "Votre preuve de paiement a été transmise — en attente de validation.")
            return redirect('candidat:candidat_dashboard')
    else:
        form = PaymentProofForm()

    from academic_core.apps.academic_structure.models import InstitutConfig, InstitutPaymentConfig
    faculty = getattr(getattr(enrollment.class_group, 'program', None), 'department', None)
    faculty = getattr(faculty, 'faculty', None)
    infos_paiement = ''
    payment_config = None
    if faculty:
        cfg = InstitutConfig.objects.using('default').filter(faculty=faculty).first()
        if cfg:
            infos_paiement = cfg.informations_paiement or ''
            payment_config = InstitutPaymentConfig.objects.using('default').filter(institut_config=cfg).first()

    montant_a_regler = enrollment.remaining_amount or enrollment.total_fees or enrollment.frais_generaux

    return render(request, 'admissions/candidat_paiement.html', {
        'form': form, 'enrollment': enrollment, 'infos_paiement': infos_paiement,
        'montant_a_regler': montant_a_regler,
        'current_step': 5,
        'wave_usable': bool(payment_config and payment_config.wave_usable()),
        'orange_money_usable': bool(payment_config and payment_config.orange_money_usable()),
        'virement_config': payment_config if (payment_config and payment_config.virement_usable()) else None,
    })


@login_required
def candidat_paiement_en_ligne_view(request):
    """
    Initie un paiement en ligne (Wave ou Orange Money, selon `provider` reçu
    en POST) — crée la session/transaction chez le fournisseur et redirige
    vers sa page de paiement hébergée. La confirmation effective vient
    exclusivement du webhook du fournisseur (wave_webhook_view /
    orange_money_webhook_view ci-dessus), jamais de ce retour navigateur.
    """
    if not request.user.is_candidat() or request.method != 'POST':
        return redirect('dashboard:index')

    provider = request.POST.get('provider')
    from academic_core.apps.accounting.models import OnlinePaymentTransaction
    if provider not in (OnlinePaymentTransaction.PROVIDER_WAVE, OnlinePaymentTransaction.PROVIDER_ORANGE_MONEY):
        messages.error(request, "Moyen de paiement en ligne invalide.")
        return redirect('candidat:candidat_paiement')

    student = getattr(request.user, 'student_profile', None)
    if not student:
        return redirect('candidat:candidat_dashboard')

    from academic_core.apps.students.models import Enrollment
    enrollment = student.enrollments.filter(status=Enrollment.STATUS_PENDING_CAISSE).order_by('-enrollment_date').first()
    if not enrollment:
        return redirect('candidat:candidat_dashboard')

    from academic_core.apps.academic_structure.models import InstitutConfig, InstitutPaymentConfig
    faculty = getattr(getattr(enrollment.class_group, 'program', None), 'department', None)
    faculty = getattr(faculty, 'faculty', None)
    config = InstitutConfig.objects.using('default').filter(faculty=faculty).first() if faculty else None
    payment_config = InstitutPaymentConfig.objects.using('default').filter(institut_config=config).first() if config else None

    if not payment_config:
        messages.error(request, "Le paiement en ligne n'est pas disponible pour cet institut.")
        return redirect('candidat:candidat_paiement')

    amount = enrollment.remaining_amount or enrollment.total_fees or enrollment.frais_generaux
    if not amount:
        messages.error(request, "Le montant à payer n'est pas encore défini — contactez le Trésorier Général.")
        return redirect('candidat:candidat_paiement')

    from academic_core.apps.accounting.payment_gateway import (
        create_wave_checkout, create_orange_money_payment, PaymentGatewayError,
    )

    return_url = request.build_absolute_uri(reverse('candidat:candidat_paiement_retour'))
    cancel_url = request.build_absolute_uri(reverse('candidat:candidat_paiement'))

    if provider == OnlinePaymentTransaction.PROVIDER_WAVE:
        if not payment_config.wave_usable():
            messages.error(request, "Wave n'est pas disponible pour cet institut.")
            return redirect('candidat:candidat_paiement')
        try:
            token, checkout_url = create_wave_checkout(
                payment_config, amount=amount,
                success_url=return_url, error_url=cancel_url,
                client_reference=f"enrollment-{enrollment.pk}",
            )
        except PaymentGatewayError as exc:
            messages.error(request, f"Impossible d'initier le paiement Wave : {exc}")
            return redirect('candidat:candidat_paiement')

    else:  # PROVIDER_ORANGE_MONEY
        if not payment_config.orange_money_usable():
            messages.error(request, "Orange Money n'est pas disponible pour cet institut.")
            return redirect('candidat:candidat_paiement')
        notif_url = request.build_absolute_uri(
            reverse('admission_portal:orange_money_webhook', kwargs={'institut_code': config.faculty.code})
        )
        try:
            token, checkout_url = create_orange_money_payment(
                payment_config, amount=amount, order_id=f"enrollment-{enrollment.pk}",
                return_url=return_url, cancel_url=cancel_url, notif_url=notif_url,
                reference=f"Frais d'inscription — {enrollment.class_group}",
            )
        except PaymentGatewayError as exc:
            messages.error(request, f"Impossible d'initier le paiement Orange Money : {exc}")
            return redirect('candidat:candidat_paiement')

    OnlinePaymentTransaction.objects.create(
        enrollment=enrollment, provider=provider, invoice_token=token, amount=amount,
    )
    return redirect(checkout_url)


@login_required
def candidat_paiement_retour_view(request):
    """
    Page d'atterrissage après le paiement chez Wave/Orange Money — informative
    uniquement. La validation effective de l'inscription vient du webhook
    (wave_webhook_view / orange_money_webhook_view), jamais de ce retour
    navigateur (que le candidat pourrait rejouer ou falsifier).
    """
    messages.info(
        request,
        "Paiement transmis — sa confirmation peut prendre quelques instants. "
        "Vous recevrez un email dès que votre inscription sera validée.",
    )
    return redirect('candidat:candidat_dashboard')


# ── Validation des candidatures (chef de département) ───────────────────────

@login_required
def candidature_list_view(request):
    if not (request.user.is_responsable() or _can_track_admissions(request.user)):
        messages.error(request, "Accès réservé au chef de département ou à la Direction Communication.")
        return redirect('dashboard:index')

    scope = _admissions_department_scope(request.user)
    candidatures = Candidature.objects.filter(
        program__department_id__in=scope, status=Candidature.STATUS_PENDING,
    ).select_related('user', 'program').order_by('submitted_at')

    return render(request, 'admissions/candidature_list.html', {'candidatures': candidatures})


@login_required
def candidature_detail_view(request, pk):
    if not (request.user.is_responsable() or _can_track_admissions(request.user)):
        messages.error(request, "Accès réservé au chef de département ou à la Direction Communication.")
        return redirect('dashboard:index')

    candidature = get_object_or_404(
        Candidature.objects.select_related('user', 'program__department'), pk=pk,
    )
    if candidature.program.department_id not in _admissions_department_scope(request.user):
        messages.error(request, "Cette candidature ne relève pas de votre département.")
        return redirect('admissions:candidature_list')

    if request.method == 'POST':
        # La Direction Communication suit les candidatures de tout l'institut
        # (voir _admissions_department_scope) mais ne peut pas se substituer
        # au chef de département pour la décision d'admission — seul le
        # visionnage (GET) lui reste ouvert.
        if not request.user.is_responsable():
            messages.error(request, "Seul le chef de département peut valider ou rejeter une candidature.")
            return redirect('admissions:candidature_detail', pk=pk)

        action = request.POST.get('action')
        from academic_core.apps.notifications.utils import notify_candidature_validated, notify_candidature_rejected

        if action == 'validate':
            candidature.status = Candidature.STATUS_VALIDATED
            candidature.reviewed_by = request.user
            candidature.reviewed_at = timezone.now()
            candidature.save()
            notify_candidature_validated(candidature, request=request)
            messages.success(request, "Candidature validée.")
        elif action == 'reject':
            candidature.status = Candidature.STATUS_REJECTED
            candidature.reviewed_by = request.user
            candidature.reviewed_at = timezone.now()
            candidature.motif_rejet = request.POST.get('motif_rejet', '').strip()
            candidature.save()
            notify_candidature_rejected(candidature)
            messages.success(request, "Candidature rejetée.")
        return redirect('admissions:candidature_list')

    return render(request, 'admissions/candidature_detail.html', {'candidature': candidature})


# ── Contenu portail des filières (chef de département) ──────────────────────

@login_required
def mes_filieres_list_view(request):
    """Liste des filières du département du chef connecté, avec l'état de
    leur contenu portail (objectifs/compétences/débouchés/modalités)."""
    if not request.user.is_responsable():
        messages.error(request, "Accès réservé au chef de département.")
        return redirect('dashboard:index')
    if not request.user.department_id:
        messages.error(request, "Votre compte n'est associé à aucun département.")
        return redirect('dashboard:index')

    from academic_core.apps.academic_structure.models import Program
    programs = Program.objects.filter(department_id=request.user.department_id).order_by('name')

    return render(request, 'admissions/mes_filieres_list.html', {'programs': programs})


@login_required
def filiere_content_edit_view(request, pk):
    """Édition du contenu portail d'une filière — réservée au chef du
    département auquel elle appartient."""
    if not request.user.is_responsable():
        messages.error(request, "Accès réservé au chef de département.")
        return redirect('dashboard:index')

    from academic_core.apps.academic_structure.models import Program
    program = get_object_or_404(Program, pk=pk)
    if program.department_id != request.user.department_id:
        messages.error(request, "Cette filière ne relève pas de votre département.")
        return redirect('admissions:mes_filieres_list')

    from .forms import plaintext_to_rich_html
    initial = {
        'level': program.level,
        # Convertit le contenu texte brut hérité (une idée par ligne, saisi
        # avant l'éditeur à puces) en HTML affichable dans l'éditeur — sans
        # effet sur le contenu déjà migré (voir plaintext_to_rich_html).
        'objectifs': plaintext_to_rich_html(program.objectifs),
        'competences': plaintext_to_rich_html(program.competences),
        'debouches': plaintext_to_rich_html(program.debouches),
        'modalites_admission': plaintext_to_rich_html(program.modalites_admission),
        'places_disponibles': program.places_disponibles,
        'ouvert_admissions': program.ouvert_admissions,
        'presentation_image': program.presentation_image,
        'presentation_video': program.presentation_video,
    }

    if request.method == 'POST':
        form = ProgramContentForm(request.POST, request.FILES, initial=initial)
        if form.is_valid():
            cd = form.cleaned_data
            program.level = cd['level']
            program.objectifs = cd['objectifs']
            program.competences = cd['competences']
            program.debouches = cd['debouches']
            program.modalites_admission = cd['modalites_admission']
            program.places_disponibles = cd['places_disponibles']
            program.ouvert_admissions = cd['ouvert_admissions']
            if cd['presentation_image'] is False:
                program.presentation_image = None
            elif cd['presentation_image']:
                program.presentation_image = cd['presentation_image']
            if cd['presentation_video'] is False:
                program.presentation_video = None
            elif cd['presentation_video']:
                program.presentation_video = cd['presentation_video']
            program.save()
            messages.success(request, f"Contenu portail de « {program.name} » mis à jour.")
            return redirect('admissions:mes_filieres_list')
    else:
        form = ProgramContentForm(initial=initial)

    return render(request, 'admissions/filiere_content_edit.html', {'form': form, 'program': program})


@login_required
def department_presentation_edit_view(request):
    """Image/vidéo de présentation du département du chef connecté,
    affichée sur le portail public — voir DepartmentPresentationForm."""
    if not request.user.is_responsable():
        messages.error(request, "Accès réservé au chef de département.")
        return redirect('dashboard:index')
    if not request.user.department_id:
        messages.error(request, "Votre compte n'est associé à aucun département.")
        return redirect('dashboard:index')

    from academic_core.apps.academic_structure.models import Department
    from .forms import DepartmentPresentationForm

    department = get_object_or_404(Department, pk=request.user.department_id)
    initial = {
        'presentation_image': department.presentation_image,
        'presentation_video': department.presentation_video,
        'description': department.description,
    }

    if request.method == 'POST':
        form = DepartmentPresentationForm(request.POST, request.FILES, initial=initial)
        if form.is_valid():
            cd = form.cleaned_data
            if cd['presentation_image'] is False:
                department.presentation_image = None
            elif cd['presentation_image']:
                department.presentation_image = cd['presentation_image']
            if cd['presentation_video'] is False:
                department.presentation_video = None
            elif cd['presentation_video']:
                department.presentation_video = cd['presentation_video']
            department.description = cd['description']
            department.save()
            messages.success(request, "Présentation du département mise à jour.")
            return redirect('admissions:mes_filieres_list')
    else:
        form = DepartmentPresentationForm(initial=initial)

    return render(request, 'admissions/department_presentation_edit.html', {
        'form': form, 'department': department,
    })


# ── Dates d'ouverture/fermeture des inscriptions (chef de département +
#    Direction Communication) ────────────────────────────────────────────────

@login_required
def department_admissions_dates_list_view(request):
    """
    Chef de département : redirigé directement vers l'édition de son propre
    département (un seul à gérer). Direction Communication : liste de tous
    les départements de l'institut, chacun avec son statut d'ouverture
    courant (voir Department.admissions_ouvertes) et un lien d'édition.
    """
    if not (request.user.is_responsable() or _can_track_admissions(request.user)):
        messages.error(request, "Accès réservé au chef de département ou à la Direction Communication.")
        return redirect('dashboard:index')

    if _can_track_admissions(request.user):
        from academic_core.apps.academic_structure.models import Department
        departments = Department.objects.filter(is_active=True).order_by('name')
        return render(request, 'admissions/department_admissions_dates_list.html', {
            'departments': departments,
        })

    if not request.user.department_id:
        messages.error(request, "Votre compte n'est associé à aucun département.")
        return redirect('dashboard:index')
    return redirect('admissions:department_admissions_dates_edit', pk=request.user.department_id)


def _get_manageable_department_or_redirect(request, pk):
    """
    Récupère le Department `pk` si l'utilisateur connecté peut en gérer les
    dates d'inscription (son propre département pour un chef, tout
    département de l'institut pour la Direction Communication). Retourne
    (department, None) si ok, sinon (None, HttpResponseRedirect).
    """
    if not (request.user.is_responsable() or _can_track_admissions(request.user)):
        messages.error(request, "Accès réservé au chef de département ou à la Direction Communication.")
        return None, redirect('dashboard:index')

    from academic_core.apps.academic_structure.models import Department
    department = get_object_or_404(Department, pk=pk)
    if not _can_track_admissions(request.user) and department.pk != request.user.department_id:
        messages.error(request, "Ce département ne relève pas de votre gestion.")
        return None, redirect('admissions:department_admissions_dates_list')
    return department, None


@login_required
def department_admissions_dates_edit_view(request, pk):
    """Édition des dates d'ouverture/fermeture des inscriptions d'un
    département — réservée au chef de ce département et à la Direction
    Communication (tout département de l'institut)."""
    department, err = _get_manageable_department_or_redirect(request, pk)
    if err:
        return err

    initial = {
        'admissions_date_ouverture': department.admissions_date_ouverture,
        'admissions_date_fermeture': department.admissions_date_fermeture,
    }

    if request.method == 'POST':
        form = DepartmentAdmissionsDatesForm(request.POST, initial=initial)
        if form.is_valid():
            cd = form.cleaned_data
            department.admissions_date_ouverture = cd['admissions_date_ouverture']
            department.admissions_date_fermeture = cd['admissions_date_fermeture']
            department.save(update_fields=['admissions_date_ouverture', 'admissions_date_fermeture'])
            messages.success(request, f"Dates d'inscription mises à jour pour « {department.name} ».")
            return redirect('admissions:department_admissions_dates_list')
    else:
        form = DepartmentAdmissionsDatesForm(initial=initial)

    return render(request, 'admissions/department_admissions_dates_edit.html', {
        'form': form, 'department': department,
    })


@login_required
def department_admissions_dates_clear_view(request, pk):
    """Supprime en un clic les dates d'ouverture/fermeture d'un département
    (retour à « toujours ouvert », le comportement historique) — mêmes droits
    que l'édition."""
    if request.method != 'POST':
        return redirect('admissions:department_admissions_dates_list')

    department, err = _get_manageable_department_or_redirect(request, pk)
    if err:
        return err

    department.admissions_date_ouverture = None
    department.admissions_date_fermeture = None
    department.save(update_fields=['admissions_date_ouverture', 'admissions_date_fermeture'])
    messages.success(request, f"Dates d'inscription supprimées pour « {department.name} » — portail toujours ouvert.")
    return redirect('admissions:department_admissions_dates_list')


# ── Comptes candidats (chef de département) ─────────────────────────────────
# Un candidat apparaît ici dès que son compte est vérifié (clic sur le lien
# de confirmation — voir verify_email_view), même avant d'avoir choisi une
# filière : tant qu'il n'a soumis aucune candidature, il n'est rattaché à
# aucun département (voir candidature_view) et reste donc « non revendiqué »
# — visible et gérable par n'importe quel chef de département de l'institut,
# pour pouvoir le relancer ou nettoyer son compte s'il reste sans suite. Dès
# qu'il postule, il devient scopé au département de la filière choisie,
# comme candidature_list_view/filiere_content_edit_view ci-dessus.

def _candidature_stage(candidature):
    """
    Retourne (code, libellé, enrollment_ou_None) décrivant l'étape actuelle
    du parcours du candidat — utilisé pour l'affichage et pour déterminer
    quel rappel envoyer (voir _resend_candidat_reminder).
    """
    user = candidature.user
    if not user.is_active:
        return 'non_verifie', "Compte non vérifié", None
    if candidature.status == Candidature.STATUS_REJECTED:
        return 'rejetee', "Candidature rejetée", None
    if candidature.status == Candidature.STATUS_PENDING:
        return 'candidature_pending', "Candidature en attente d'examen", None

    student = getattr(user, 'student_profile', None)
    if not student:
        return 'a_completer', "Dossier d'inscription à compléter", None

    from academic_core.apps.students.models import Enrollment
    enrollment = student.enrollments.order_by('-enrollment_date').first()
    if not enrollment:
        return 'a_completer', "Dossier d'inscription à compléter", None
    if enrollment.status == Enrollment.STATUS_PENDING:
        return 'dossier_pending', "Dossier en attente de traitement", enrollment
    if enrollment.status == Enrollment.STATUS_PENDING_CAISSE:
        return 'attente_paiement', "En attente de paiement", enrollment
    if enrollment.status == Enrollment.STATUS_VALIDATED:
        return 'finalise', "Inscription finalisée", enrollment
    return 'autre', enrollment.get_status_display(), enrollment


def _can_resend_reminder(stage_code):
    return stage_code not in ('rejetee', 'finalise')


def _resend_candidat_reminder(request, user, candidature, stage_code, enrollment):
    if stage_code == 'non_verifie':
        from academic_core.apps.accounts.models import EmailVerificationToken
        from academic_core.apps.notifications.utils import send_branded_email
        _tok, raw_token = EmailVerificationToken.issue(user)
        institut_code = candidature.program.department.faculty.code
        verify_url = request.build_absolute_uri(
            reverse('admission_portal:verifier_email', kwargs={'institut_code': institut_code, 'token': raw_token})
        )
        send_branded_email(
            to_email=user.email,
            subject="Rappel — Vérifiez votre adresse email",
            heading="Rappel — confirmez votre adresse email",
            paragraphs=[
                f"Bonjour {user.get_full_name()},",
                f"Vous n'avez pas encore confirmé votre adresse email pour poursuivre votre "
                f"candidature pour la filière « {candidature.program.name} ».",
                "Veuillez cliquer sur le bouton ci-dessous. Ce lien expire dans 48 heures.",
            ],
            cta_url=verify_url,
            cta_label="Vérifier mon adresse email",
            fallback_text=(
                f"Bonjour {user.get_full_name()},\n\n"
                f"Vous n'avez pas encore confirmé votre adresse email pour poursuivre votre "
                f"candidature. Veuillez cliquer sur ce lien :\n{verify_url}\n\n"
                f"Ce lien expire dans 48 heures.\n"
            ),
        )
        return

    from academic_core.apps.notifications.utils import notify_users, notify_candidature_validated, notify_ready_for_payment
    from academic_core.apps.notifications.models import Notification

    if stage_code == 'sans_candidature':
        login_url = request.build_absolute_uri(reverse('accounts:login'))
        notify_users(
            recipients=[user], notification_type=Notification.TYPE_GENERAL,
            title="Rappel — Finalisez votre candidature",
            message=(
                f"Vous avez créé un compte candidat mais n'avez pas encore soumis de "
                f"candidature. Connectez-vous pour choisir votre filière et compléter "
                f"votre dossier : {login_url}"
            ),
            send_email=True,
        )
    elif stage_code == 'candidature_pending':
        notify_users(
            recipients=[user], notification_type=Notification.TYPE_GENERAL,
            title="Rappel — Votre candidature est en cours d'examen",
            message=(
                f"Votre candidature pour la filière « {candidature.program} » est toujours en "
                f"cours d'examen. Vous serez notifié(e) dès qu'une décision sera prise."
            ),
            send_email=True,
        )
    elif stage_code == 'a_completer':
        notify_candidature_validated(candidature, request=request)
    elif stage_code == 'dossier_pending' and enrollment:
        notify_users(
            recipients=[user], notification_type=Notification.TYPE_GENERAL,
            title="Rappel — Votre dossier d'inscription est en cours de traitement",
            message=(
                f"Votre dossier d'inscription en {enrollment.class_group} est en attente de "
                f"traitement par l'administration. Vous serez notifié(e) dès que vos frais "
                f"seront fixés et que vous pourrez procéder au paiement."
            ),
            send_email=True,
        )
    elif stage_code == 'attente_paiement' and enrollment:
        notify_ready_for_payment(enrollment, request=request)


@login_required
def candidat_accounts_list_view(request):
    """
    Liste des comptes candidats visibles par l'utilisateur connecté : ceux
    ayant postulé dans SON département (tous les départements de l'institut
    pour la Direction Communication — voir _admissions_department_scope), et
    ceux qui ont déjà vérifié leur compte (clic sur le lien de confirmation)
    mais n'ont encore soumis aucune candidature nulle part — non revendiqués
    par un département, donc visibles par tous les chefs de l'institut afin
    de pouvoir les relancer ou nettoyer un compte resté sans suite.
    """
    if not (request.user.is_responsable() or _can_track_admissions(request.user)):
        messages.error(request, "Accès réservé au chef de département ou à la Direction Communication.")
        return redirect('dashboard:index')
    scope = _admissions_department_scope(request.user)
    if not scope:
        messages.error(request, "Votre compte n'est associé à aucun département.")
        return redirect('dashboard:index')

    from academic_core.apps.accounts.models import User, Role

    candidatures = Candidature.objects.filter(
        program__department_id__in=scope,
    ).select_related('user', 'program').order_by('-submitted_at')

    rows = []
    applied_user_ids = set()
    for c in candidatures:
        applied_user_ids.add(c.user_id)
        stage_code, stage_label, enrollment = _candidature_stage(c)
        rows.append({
            'user': c.user,
            'candidature': c,
            'stage_code': stage_code,
            'stage_label': stage_label,
            'enrollment': enrollment,
            'can_resend': _can_resend_reminder(stage_code),
        })

    pending_users = User.objects.filter(
        role__name=Role.CANDIDAT, is_active=True,
    ).exclude(pk__in=applied_user_ids).order_by('-pk')

    for u in pending_users:
        rows.append({
            'user': u,
            'candidature': None,
            'stage_code': 'sans_candidature',
            'stage_label': 'Compte créé — en attente de candidature',
            'enrollment': None,
            'can_resend': True,
        })

    return render(request, 'admissions/candidat_accounts_list.html', {'rows': rows})


def _get_scoped_candidat_user_or_redirect(request, user_pk):
    """
    Récupère le compte `user_pk` (ex-candidat, éventuellement déjà promu
    étudiant après validation de son inscription — voir le basculement de
    rôle CANDIDAT → ETUDIANT dans accounting/services.py::
    finalize_enrollment_payment) et sa Candidature éventuelle, en vérifiant
    que — s'il a déjà postulé — cela relève bien du périmètre de l'utilisateur
    connecté (voir _admissions_department_scope : son propre département pour
    un chef, tous les départements de l'institut pour la Direction
    Communication ; un compte sans candidature n'appartient à aucun
    département et reste géré par tous). Retourne (user, candidature_ou_None,
    None) si ok, sinon (None, None, HttpResponseRedirect).
    """
    from academic_core.apps.accounts.models import User, Role
    user = get_object_or_404(User, pk=user_pk)
    # Ne PAS chaîner select_related jusqu'à 'faculty' : Faculty est un modèle
    # maître (MASTER_MODEL_NAMES) qui ne vit réellement qu'en base 'default'
    # — un JOIN SQL unique vers la base tenant courante ne trouverait aucune
    # ligne correspondante et ferait disparaître silencieusement le résultat.
    # L'accès à .faculty doit rester un attribut paresseux séparé (voir
    # _resend_candidat_reminder), routé indépendamment vers 'default'.
    candidature = Candidature.objects.select_related('program__department').filter(user=user).first()
    if candidature:
        if candidature.program.department_id not in _admissions_department_scope(request.user):
            messages.error(request, "Ce candidat ne relève pas de votre département.")
            return None, None, redirect('admissions:candidat_accounts_list')
    elif not (user.role and user.role.name == Role.CANDIDAT):
        # Pas de candidature et plus (ou jamais) le rôle CANDIDAT : hors
        # périmètre de cet écran (voir candidat_accounts_list_view).
        messages.error(request, "Ce compte n'est pas géré depuis cet écran.")
        return None, None, redirect('admissions:candidat_accounts_list')
    return user, candidature, None


@login_required
def candidat_account_edit_view(request, user_pk):
    if not (request.user.is_responsable() or _can_track_admissions(request.user)):
        messages.error(request, "Accès réservé au chef de département ou à la Direction Communication.")
        return redirect('dashboard:index')

    user, candidature, err = _get_scoped_candidat_user_or_redirect(request, user_pk)
    if err:
        return err

    if request.method == 'POST':
        from django.db.models import Q
        from academic_core.apps.accounts.models import User

        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip().lower()
        phone = request.POST.get('phone', '').strip()
        is_active = request.POST.get('is_active') == '1'

        errors = []
        if not first_name:
            errors.append("Le prénom est obligatoire.")
        if not last_name:
            errors.append("Le nom est obligatoire.")
        if not email:
            errors.append("L'email est obligatoire.")
        elif User.objects.using('default').filter(
            Q(email__iexact=email) | Q(username__iexact=email)
        ).exclude(pk=user.pk).exists():
            errors.append("Un autre compte utilise déjà cet email.")

        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            user.first_name = first_name
            user.last_name = last_name
            user.email = email
            user.username = email
            user.phone = phone
            user.is_active = is_active
            user.save(using='default')

            from academic_core.apps.accounts.db_utils import sync_user_to_institute_db
            from academic_core.db_router import get_current_db
            sync_user_to_institute_db(user, get_current_db())

            messages.success(request, f"Compte de {user.get_full_name()} mis à jour.")
            return redirect('admissions:candidat_accounts_list')

    return render(request, 'admissions/candidat_account_edit.html', {
        'candidature': candidature, 'user_obj': user,
    })


@login_required
def candidat_account_delete_view(request, user_pk):
    if not (request.user.is_responsable() or _can_track_admissions(request.user)):
        messages.error(request, "Accès réservé au chef de département ou à la Direction Communication.")
        return redirect('dashboard:index')

    user, candidature, err = _get_scoped_candidat_user_or_redirect(request, user_pk)
    if err:
        return err

    student = getattr(user, 'student_profile', None)

    if request.method == 'POST':
        from academic_core.db_router import get_current_db

        full_name = user.get_full_name()
        try:
            _purge_candidat_account(user, get_current_db())
        except Exception:
            messages.error(
                request,
                f"Échec de la suppression du compte de {full_name} — aucune donnée n'a été "
                "modifiée. Réessayez ou contactez le support technique.",
            )
            return redirect('admissions:candidat_accounts_list')

        messages.success(request, f"Le compte candidat de {full_name} a été supprimé.")
        return redirect('admissions:candidat_accounts_list')

    return render(request, 'admissions/candidat_account_confirm_delete.html', {
        'user_obj': user, 'candidature': candidature, 'student': student,
    })


@login_required
def candidat_account_resend_view(request, user_pk):
    if not (request.user.is_responsable() or _can_track_admissions(request.user)):
        messages.error(request, "Accès réservé au chef de département ou à la Direction Communication.")
        return redirect('dashboard:index')
    if request.method != 'POST':
        return redirect('admissions:candidat_accounts_list')

    user, candidature, err = _get_scoped_candidat_user_or_redirect(request, user_pk)
    if err:
        return err

    if candidature:
        stage_code, _stage_label, enrollment = _candidature_stage(candidature)
    else:
        stage_code, enrollment = 'sans_candidature', None

    if not _can_resend_reminder(stage_code):
        messages.error(request, "Aucun rappel pertinent pour ce statut.")
        return redirect('admissions:candidat_accounts_list')

    _resend_candidat_reminder(request, user, candidature, stage_code, enrollment)
    messages.success(request, f"Rappel envoyé à {user.get_full_name()}.")
    return redirect('admissions:candidat_accounts_list')
