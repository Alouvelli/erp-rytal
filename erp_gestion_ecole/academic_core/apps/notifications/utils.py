import threading

from django.core.mail import send_mail, get_connection, EmailMultiAlternatives
from django.conf import settings
from django.template.loader import render_to_string
from .models import Notification


def _resolve_institut_email(sender_email=None):
    """
    Retourne (connection, from_email) à utiliser pour l'envoi d'un email de
    notification, d'après la configuration email de l'institut actuellement
    actif (thread-local, voir academic_core/db_router.py::get_current_db) si
    celui-ci a une InstitutEmailConfig active et exploitable
    (InstitutEmailConfig.is_usable()) — sinon (None, None), pour que
    l'appelant retombe sur le backend/adresse email globaux de la
    plateforme (settings.EMAIL_BACKEND / DEFAULT_FROM_EMAIL).

    Aucun rapport avec le mécanisme d'activation de la plateforme (code
    d'activation, PLATFORM_RESET_EMAIL_1/2 — voir
    academic_core/apps/accounts/platform_activation.py) : cette fonction
    n'est jamais appelée par ce mécanisme, qui garde sa configuration email
    globale, fixe, inchangée.

    `sender_email`, si fourni, reste prioritaire sur l'adresse d'expédition
    de la config institut — inchangé par rapport au comportement historique
    de notify_users (adresse de l'utilisateur ayant déclenché l'action).
    """
    try:
        from academic_core.db_router import get_current_db
        from academic_core.apps.academic_structure.models import InstitutConfig

        current_db = get_current_db()
        if current_db == 'default':
            return None, None

        config = (InstitutConfig.objects.using('default')
                  .select_related('email_config')
                  .filter(db_alias=current_db).first())
        if not config:
            return None, None

        email_config = getattr(config, 'email_config', None)
        if not email_config or not email_config.is_usable():
            return None, None

        connection = get_connection(
            backend='django.core.mail.backends.smtp.EmailBackend',
            host=email_config.email_host,
            port=email_config.email_port,
            username=email_config.email_host_user,
            password=email_config.email_host_password,
            use_tls=email_config.email_use_tls,
            fail_silently=True,
        )
        from_email = sender_email or email_config.default_from_email or email_config.email_host_user
        return connection, from_email
    except Exception:
        return None, None


def _resolve_institut_branding():
    """
    Retourne (nom, couleur_primaire, logo_bytes, logo_content_type) pour
    l'institut actuellement actif (thread-local, voir get_current_db) — nom
    vide / couleur par défaut / logo absent si aucun institut actif, si son
    InstitutConfig est introuvable, ou si le logo ne peut pas être lu (jamais
    d'exception propagée : un email doit toujours pouvoir partir, même sans
    branding).
    """
    try:
        import mimetypes
        from academic_core.db_router import get_current_db
        from academic_core.apps.academic_structure.models import InstitutConfig

        current_db = get_current_db()
        if current_db == 'default':
            return '', '#003d82', None, None

        config = InstitutConfig.objects.using('default').filter(db_alias=current_db).first()
        if not config:
            return '', '#003d82', None, None

        nom = config.nom or config.sigle or ''
        couleur = config.couleur_primaire or '#003d82'
        logo_bytes, logo_content_type = None, None
        if config.logo:
            try:
                config.logo.open('rb')
                logo_bytes = config.logo.read()
            finally:
                config.logo.close()
            logo_content_type = mimetypes.guess_type(config.logo.name)[0] or 'image/png'
        return nom, couleur, logo_bytes, logo_content_type
    except Exception:
        return '', '#003d82', None, None


def send_branded_email(*, to_email, subject, heading, paragraphs,
                       from_email=None, connection=None, sender_email=None,
                       cta_url=None, cta_label=None, fallback_text=None,
                       attachments=None):
    """
    Envoie un email HTML soigné (logo + couleur de l'institut actif intégrés,
    repli en texte brut pour les clients qui ne supportent pas le HTML) —
    utilisé pour toutes les communications aux candidats/chefs de département
    pendant le parcours de candidature (voir notify_candidature_*,
    notify_ready_for_payment, admissions/views.py::signup_view).

    `from_email`/`connection` : si non fournis, résolus depuis
    InstitutEmailConfig comme le ferait notify_users (voir
    _resolve_institut_email) — permet un appel autonome, sans passer par
    notify_users, pour les emails qui ne créent pas de Notification en base
    (ex. vérification d'adresse email, avant que le compte ne soit actif).

    `attachments` : liste optionnelle de tuples (filename, content_bytes,
    mimetype) — ex. le reçu PDF joint à l'email de validation d'inscription
    (voir notify_inscription_validated).
    """
    if not to_email:
        return
    if from_email is None and connection is None:
        connection, resolved_from = _resolve_institut_email(sender_email)
        from_email = resolved_from or sender_email or settings.DEFAULT_FROM_EMAIL

    institut_nom, couleur_primaire, logo_bytes, logo_content_type = _resolve_institut_branding()

    html_body = render_to_string('emails/base_email.html', {
        'institut_nom': institut_nom,
        'couleur_primaire': couleur_primaire,
        'heading': heading,
        'paragraphs': paragraphs,
        'cta_url': cta_url,
        'cta_label': cta_label,
        'has_logo': bool(logo_bytes),
    })
    text_body = fallback_text or '\n\n'.join(paragraphs)

    try:
        email = EmailMultiAlternatives(
            subject=subject, body=text_body, from_email=from_email,
            to=[to_email], connection=connection,
        )
        email.attach_alternative(html_body, 'text/html')
        for att_filename, att_content, att_mimetype in (attachments or []):
            email.attach(att_filename, att_content, att_mimetype)
        if logo_bytes:
            from email.mime.image import MIMEImage
            email.mixed_subtype = 'related'
            subtype = logo_content_type.split('/')[-1] if logo_content_type else 'png'
            logo_part = MIMEImage(logo_bytes, _subtype=subtype)
            logo_part.add_header('Content-ID', '<institut_logo>')
            logo_part.add_header('Content-Disposition', 'inline', filename='logo')
            email.attach(logo_part)
        email.send(fail_silently=True)
    except Exception:
        pass


def notify_users(recipients, notification_type, title, message,
                 priority='MEDIUM', link='', send_email=False, sender_email=None,
                 email_heading=None, email_paragraphs=None, cta_url=None, cta_label=None,
                 email_attachments=None):
    """
    Crée des notifications internes pour une liste d'utilisateurs.
    sender_email : adresse de l'utilisateur connecté déclenchant l'action ;
                   si fournie, sera utilisée comme expéditeur du mail.

    Si l'institut actif a configuré ses propres paramètres SMTP (voir
    InstitutEmailConfig / academic_structure/views.py::institut_email_config_view),
    l'email est envoyé via cette configuration plutôt que le backend global
    de la plateforme — transparent pour les appelants existants.

    `email_heading`/`email_paragraphs` (+ `cta_url`/`cta_label` optionnels) :
    si fournis, l'email est envoyé au format HTML soigné (logo + couleur de
    l'institut, voir send_branded_email) au lieu du texte brut historique —
    entièrement rétrocompatible : les appelants qui ne les passent pas
    conservent le comportement plain-text existant.

    `email_attachments` : liste optionnelle de tuples (filename, content_bytes,
    mimetype) à joindre à l'email — les contenus doivent être déjà générés
    (bytes en mémoire) par l'appelant avant cet appel, car l'envoi se fait
    dans un thread d'arrière-plan (voir plus bas) qui ne doit pas dépendre
    d'accès DB supplémentaires ni bloquer la requête HTTP en cours.
    """
    notifications = [
        Notification(
            recipient=user,
            notification_type=notification_type,
            title=title,
            message=message,
            priority=priority,
            link=link,
        )
        for user in recipients
    ]
    Notification.objects.bulk_create(notifications)

    if send_email:
        recipient_emails = [user.email for user in recipients if user.email]
        if recipient_emails:
            # Envoi en arrière-plan : un serveur SMTP lent/indisponible ne doit
            # jamais bloquer la requête HTTP en cours (ex. le bouton "Confirmer
            # le paiement et valider l'inscription" restait figé sur "Validation…"
            # le temps que l'email parte). La notification interne (bulk_create
            # ci-dessus) reste, elle, synchrone et immédiatement visible.
            # `get_current_db()` est thread-local (voir db_router.py) : on capture
            # l'alias tenant courant ici et on le repropage explicitement dans le
            # thread de fond, qui sinon retomberait sur 'default' et résoudrait
            # la mauvaise configuration SMTP d'institut (_resolve_institut_email).
            from academic_core.db_router import get_current_db, set_current_db
            current_db = get_current_db()

            def _send_emails_async():
                set_current_db(current_db)
                institut_connection, institut_from_email = _resolve_institut_email(sender_email)
                from_email = institut_from_email or sender_email or settings.DEFAULT_FROM_EMAIL
                for email in recipient_emails:
                    try:
                        if email_heading:
                            send_branded_email(
                                to_email=email, subject=title, heading=email_heading,
                                paragraphs=email_paragraphs or [message],
                                from_email=from_email, connection=institut_connection,
                                cta_url=cta_url, cta_label=cta_label, fallback_text=message,
                                attachments=email_attachments,
                            )
                        else:
                            send_mail(
                                subject=title,
                                message=message,
                                from_email=from_email,
                                recipient_list=[email],
                                fail_silently=True,
                                connection=institut_connection,
                            )
                    except Exception:
                        pass

            threading.Thread(target=_send_emails_async, daemon=True).start()


def notify_inscription_pending(enrollment, request=None):
    """
    Notifie les Trésoriers Généraux et Admins d'Institut qu'une nouvelle
    inscription/réinscription est en attente de validation.
    """
    from django.urls import reverse
    from academic_core.apps.accounts.models import User, Role

    student      = enrollment.student
    class_group  = enrollment.class_group
    acad_year    = enrollment.academic_year
    enroll_type  = enrollment.get_enrollment_type_display() if hasattr(enrollment, 'get_enrollment_type_display') else enrollment.enrollment_type

    title_notif = f"Nouvelle demande d'inscription — {student.full_name}"
    message_notif = (
        f"L'étudiant(e) {student.full_name} ({student.matricule or 'sans matricule'}) "
        f"a soumis une demande de {enroll_type} en {class_group} "
        f"pour l'année académique {acad_year}. "
        f"En attente de validation."
    )
    try:
        link = reverse('accounting:validation_inscription_detail', args=[enrollment.pk])
    except Exception:
        link = ''

    # Destinataires : Trésoriers Généraux + Admins Institut (même base de données)
    tresorier_role = Role.objects.filter(name=Role.TRESORIER_GENERAL).first()
    inst_admin_role = Role.objects.filter(name=Role.INST_ADMIN).first()
    roles_to_notify = [r for r in [tresorier_role, inst_admin_role] if r]

    recipients = list(
        User.objects.filter(role__in=roles_to_notify, is_active=True)
        .distinct()
    )

    if not recipients:
        return

    sender_email = None
    if request and request.user.is_authenticated:
        sender_email = request.user.email or None

    notify_users(
        recipients=recipients,
        notification_type=Notification.TYPE_INSCRIPTION_PENDING,
        title=title_notif,
        message=message_notif,
        priority=Notification.PRIORITY_HIGH,
        link=link,
        send_email=False,
        sender_email=sender_email,
    )


def notify_inscription_pending_caisse(enrollment, request=None):
    """
    Notifie les Caissiers (+ Trésoriers Généraux et Admins d'Institut) qu'un
    dossier d'inscription vient d'être envoyé « à la caisse » et attend
    l'encaissement/la validation du paiement (voir accounting/views.py::
    validation_inscription_detail, action='send_to_caisse'). Complète
    notify_inscription_pending, qui ne couvre que l'étape précédente (dossier
    en attente de validation par le Trésorier Général).
    """
    from django.urls import reverse
    from academic_core.apps.accounts.models import User, Role

    student     = enrollment.student
    class_group = enrollment.class_group
    acad_year   = enrollment.academic_year

    title_notif = f"Dossier à encaisser — {student.full_name}"
    message_notif = (
        f"Le dossier d'inscription de {student.full_name} ({student.matricule or 'sans matricule'}) "
        f"en {class_group} pour l'année académique {acad_year} a été transmis à la caisse "
        f"— en attente d'encaissement et de validation finale."
    )
    try:
        link = reverse('accounting:validation_inscription_detail', args=[enrollment.pk])
    except Exception:
        link = ''

    caissier_role   = Role.objects.filter(name=Role.CAISSIER).first()
    tresorier_role  = Role.objects.filter(name=Role.TRESORIER_GENERAL).first()
    inst_admin_role = Role.objects.filter(name=Role.INST_ADMIN).first()
    roles_to_notify = [r for r in [caissier_role, tresorier_role, inst_admin_role] if r]

    recipients = list(
        User.objects.filter(role__in=roles_to_notify, is_active=True)
        .distinct()
    )
    if not recipients:
        return

    sender_email = None
    if request and request.user.is_authenticated:
        sender_email = request.user.email or None

    notify_users(
        recipients=recipients,
        notification_type=Notification.TYPE_INSCRIPTION_PENDING,
        title=title_notif,
        message=message_notif,
        priority=Notification.PRIORITY_HIGH,
        link=link,
        send_email=False,
        sender_email=sender_email,
    )


def _resolve_institut_config(request=None):
    """
    Retourne l'InstitutConfig de l'institut actif, depuis `request.active_faculty`
    si disponible, sinon depuis l'alias de base tenant courant (thread-local,
    voir get_current_db) — permet de résoudre le logo/en-tête institut dans
    des contextes sans requête HTTP (ex. génération de pièce jointe avant
    l'envoi d'un email en arrière-plan). None si non résolvable.
    """
    try:
        from academic_core.apps.academic_structure.models import InstitutConfig
        faculty = getattr(request, 'active_faculty', None) if request else None
        if faculty:
            return InstitutConfig.objects.using('default').get(faculty=faculty)
        from academic_core.db_router import get_current_db
        current_db = get_current_db()
        if current_db == 'default':
            return None
        return InstitutConfig.objects.using('default').filter(db_alias=current_db).first()
    except Exception:
        return None


def notify_inscription_validated(enrollment, request=None):
    """Notifie l'étudiant que son inscription a été validée et qu'il peut
    désormais se connecter pour accéder à ses ressources pédagogiques —
    email avec reçu de paiement PDF joint (généré ici, avant le départ du
    thread d'envoi en arrière-plan, pour ne pas y rouvrir de connexion DB)."""
    from django.urls import reverse

    student = enrollment.student
    if not hasattr(student, 'user') or not student.user:
        return

    try:
        link = reverse('accounting:mon_certificat_inscription_pdf')
    except Exception:
        link = ''

    try:
        login_link = reverse('accounts:login')
    except Exception:
        login_link = ''
    cta_url = request.build_absolute_uri(login_link) if (request and login_link) else None

    filiere = getattr(enrollment.class_group, 'program', None)
    filiere_txt = f" en filière « {filiere.name} »" if filiere else ''

    email_attachments = None
    try:
        from academic_core.apps.accounting.services import generate_inscription_recu_pdf
        config = _resolve_institut_config(request)
        recu_buf = generate_inscription_recu_pdf(enrollment, config=config)
        safe_ref = (enrollment.payment_reference or f'inscription-{enrollment.pk}').replace('/', '-')
        email_attachments = [(f'recu_{safe_ref}.pdf', recu_buf.read(), 'application/pdf')]
    except Exception:
        pass

    notify_users(
        recipients=[student.user],
        notification_type=Notification.TYPE_INSCRIPTION_VALIDATED,
        title="Votre inscription a été validée",
        message=(
            f"Votre inscription en classe {enrollment.class_group.name}{filiere_txt} "
            f"pour l'année académique {enrollment.academic_year} a été validée. "
            f"Vous pouvez vous connecter pour accéder à vos ressources pédagogiques et "
            f"télécharger votre certificat d'inscription."
        ),
        priority=Notification.PRIORITY_HIGH,
        link=link,
        send_email=True,
        email_heading="Votre inscription a été validée",
        email_attachments=email_attachments,
        email_paragraphs=[
            f"Votre inscription en classe {enrollment.class_group.name}{filiere_txt} "
            f"pour l'année académique {enrollment.academic_year} a été validée.",
            "Vous pouvez dès à présent vous connecter à votre espace pour accéder à vos "
            "ressources pédagogiques (emploi du temps, cours, notes) et télécharger votre "
            "certificat d'inscription."
            + (" Votre reçu de paiement d'inscription est joint à cet email." if email_attachments else ''),
        ],
        cta_url=cta_url,
        cta_label="Se connecter à mon espace",
    )


def notify_inscription_rejected(enrollment):
    """Notifie l'étudiant que son inscription a été rejetée."""
    from academic_core.apps.accounts.models import User

    student = enrollment.student
    if not hasattr(student, 'user') or not student.user:
        return

    filiere = getattr(enrollment.class_group, 'program', None)
    filiere_txt = f" en filière « {filiere.name} »" if filiere else ''

    notify_users(
        recipients=[student.user],
        notification_type=Notification.TYPE_INSCRIPTION_REJECTED,
        title="Votre demande d'inscription a été rejetée",
        message=(
            f"Votre demande d'inscription en {enrollment.class_group} "
            f"pour l'année académique {enrollment.academic_year} a été rejetée. "
            f"Veuillez contacter l'administration pour plus d'informations."
        ),
        priority=Notification.PRIORITY_HIGH,
        send_email=True,
        email_heading="Votre demande d'inscription a été rejetée",
        email_paragraphs=[
            f"Votre demande d'inscription en classe {enrollment.class_group.name}{filiere_txt} "
            f"pour l'année académique {enrollment.academic_year} a été rejetée.",
            "Veuillez contacter l'administration pour plus d'informations.",
        ],
    )


def notify_candidature_pending(candidature, request=None):
    """
    Notifie le chef du département de la filière choisie (Department.admin,
    à défaut tout titulaire du rôle RESPONSABLE de ce département) qu'une
    nouvelle candidature attend sa validation.
    """
    from django.urls import reverse
    from academic_core.apps.accounts.models import User, Role

    department = candidature.program.department
    recipients = []
    if department.admin_id:
        recipients.append(department.admin)
    else:
        recipients = list(
            User.objects.filter(role__name=Role.RESPONSABLE, department=department, is_active=True)
        )
    if not recipients:
        return

    try:
        link = reverse('admissions:candidature_detail', args=[candidature.pk])
    except Exception:
        link = ''

    sender_email = None
    cta_url = None
    if request and request.user.is_authenticated:
        sender_email = request.user.email or None
    if request and link:
        cta_url = request.build_absolute_uri(link)

    notify_users(
        recipients=recipients,
        notification_type=Notification.TYPE_CANDIDATURE_PENDING,
        title=f"Nouvelle candidature — {candidature.user.get_full_name()}",
        message=(
            f"{candidature.user.get_full_name()} a soumis une candidature pour la filière "
            f"« {candidature.program.name} ». En attente de votre validation."
        ),
        priority=Notification.PRIORITY_HIGH,
        link=link,
        send_email=True,
        sender_email=sender_email,
        email_heading="Nouvelle candidature reçue",
        email_paragraphs=[
            f"{candidature.user.get_full_name()} a soumis une candidature pour la filière "
            f"« {candidature.program.name} ».",
            "Vous pouvez la consulter et la valider depuis votre espace « Candidatures en ligne ».",
        ],
        cta_url=cta_url,
        cta_label="Voir la candidature",
    )


def notify_candidature_validated(candidature, request=None):
    """Notifie le candidat que sa candidature a été validée et qu'il peut poursuivre son inscription."""
    from django.urls import reverse

    try:
        link = reverse('candidat:candidat_inscription')
    except Exception:
        link = ''
    cta_url = request.build_absolute_uri(link) if (request and link) else None

    notify_users(
        recipients=[candidature.user],
        notification_type=Notification.TYPE_CANDIDATURE_VALIDATED,
        title="Votre candidature a été validée",
        message=(
            f"Votre candidature pour la filière « {candidature.program} » a été validée. "
            f"Vous pouvez maintenant compléter votre dossier d'inscription."
        ),
        priority=Notification.PRIORITY_HIGH,
        link=link,
        send_email=True,
        email_heading="Votre candidature a été validée",
        email_paragraphs=[
            f"Bonne nouvelle : votre candidature pour la filière « {candidature.program.name} » a été validée par le département.",
            "Vous pouvez désormais compléter votre dossier d'inscription depuis votre espace candidat.",
        ],
        cta_url=cta_url,
        cta_label="Compléter mon inscription",
    )


def notify_candidature_rejected(candidature):
    """Notifie le candidat que sa candidature a été rejetée."""
    notify_users(
        recipients=[candidature.user],
        notification_type=Notification.TYPE_CANDIDATURE_REJECTED,
        title="Votre candidature n'a pas été retenue",
        message=(
            f"Votre candidature pour la filière « {candidature.program} » n'a pas été retenue. "
            + (f"Motif : {candidature.motif_rejet}" if candidature.motif_rejet else
               "Veuillez contacter l'administration pour plus d'informations.")
        ),
        priority=Notification.PRIORITY_HIGH,
        send_email=True,
        email_heading="Votre candidature n'a pas été retenue",
        email_paragraphs=[
            f"Nous vous informons que votre candidature pour la filière « {candidature.program.name} » n'a pas été retenue.",
            (f"Motif : {candidature.motif_rejet}" if candidature.motif_rejet else
             "N'hésitez pas à contacter l'administration pour plus d'informations."),
        ],
    )


def notify_ready_for_payment(enrollment, request=None):
    """
    Notifie le candidat que les frais de son dossier ont été fixés par le
    Trésorier Général (statut PENDING_CAISSE) et qu'il peut désormais payer
    ses frais d'inscription, avec les coordonnées de paiement de l'institut.
    """
    from django.urls import reverse
    from academic_core.apps.academic_structure.models import InstitutConfig

    student = enrollment.student
    if not hasattr(student, 'user') or not student.user:
        return

    try:
        link = reverse('candidat:candidat_paiement')
    except Exception:
        link = ''
    cta_url = request.build_absolute_uri(link) if (request and link) else None

    faculty = getattr(getattr(enrollment.class_group, 'program', None), 'department', None)
    faculty = getattr(faculty, 'faculty', None)
    infos_paiement = ''
    if faculty:
        cfg = InstitutConfig.objects.using('default').filter(faculty=faculty).first()
        infos_paiement = (cfg.informations_paiement or '') if cfg else ''

    filiere = getattr(enrollment.class_group, 'program', None)
    filiere_txt = f" (filière « {filiere.name} »)" if filiere else ''
    montant = enrollment.payment_amount
    message = (
        f"Votre dossier d'inscription en {enrollment.class_group}{filiere_txt} a été validé par le Trésorier Général. "
        f"Montant à régler : {montant} FCFA. " if montant else
        f"Votre dossier d'inscription en {enrollment.class_group}{filiere_txt} a été validé par le Trésorier Général. "
    )
    message += "Merci de procéder au paiement rapidement, dans la limite des places disponibles."
    if infos_paiement:
        message += f"\n\nInformations de paiement :\n{infos_paiement}"

    email_paragraphs = [
        f"Votre dossier d'inscription en classe {enrollment.class_group.name}{filiere_txt} a été validé par le Trésorier Général."
        + (f" Montant à régler : {montant} FCFA." if montant else ''),
        "Merci de procéder au paiement rapidement, dans la limite des places disponibles.",
    ]
    if infos_paiement:
        email_paragraphs.append(f"Informations de paiement :\n{infos_paiement}")

    notify_users(
        recipients=[student.user],
        notification_type=Notification.TYPE_READY_FOR_PAYMENT,
        title="Vos frais d'inscription sont prêts à être réglés",
        message=message,
        priority=Notification.PRIORITY_HIGH,
        link=link,
        send_email=True,
        email_heading="Vos frais d'inscription sont prêts à être réglés",
        email_paragraphs=email_paragraphs,
        cta_url=cta_url,
        cta_label="Procéder au paiement",
    )


def notify_payment_proof_pending(payment_proof, request=None):
    """Notifie les Caissiers/Trésoriers Généraux qu'une preuve de paiement attend validation."""
    from django.urls import reverse
    from academic_core.apps.accounts.models import User, Role

    roles_to_notify = list(Role.objects.filter(name__in=[Role.CAISSIER, Role.TRESORIER_GENERAL]))
    recipients = list(User.objects.filter(role__in=roles_to_notify, is_active=True).distinct())
    if not recipients:
        return

    try:
        link = reverse('accounting:payment_proof_detail', args=[payment_proof.pk])
    except Exception:
        link = ''

    sender_email = None
    if request and request.user.is_authenticated:
        sender_email = request.user.email or None

    notify_users(
        recipients=recipients,
        notification_type=Notification.TYPE_PAYMENT_PROOF_PENDING,
        title=f"Preuve de paiement déposée — {payment_proof.enrollment.student.full_name}",
        message=(
            f"{payment_proof.enrollment.student.full_name} a déposé une preuve de paiement "
            f"({payment_proof.get_moyen_paiement_display()}, {payment_proof.montant_declare} FCFA). "
            f"En attente de validation."
        ),
        priority=Notification.PRIORITY_HIGH,
        link=link,
        send_email=False,
        sender_email=sender_email,
    )


def notify_payment_proof_rejected(payment_proof, request=None):
    """Notifie le candidat que sa preuve de paiement a été rejetée — il peut en déposer une nouvelle."""
    from django.urls import reverse

    student = payment_proof.enrollment.student
    if not hasattr(student, 'user') or not student.user:
        return

    try:
        link = reverse('candidat:candidat_paiement')
    except Exception:
        link = ''
    cta_url = request.build_absolute_uri(link) if (request and link) else None

    class_group = payment_proof.enrollment.class_group
    filiere = getattr(class_group, 'program', None)
    filiere_txt = f" (filière « {filiere.name} »)" if filiere else ''

    notify_users(
        recipients=[student.user],
        notification_type=Notification.TYPE_PAYMENT_PROOF_REJECTED,
        title="Votre preuve de paiement a été rejetée",
        message=(
            "Votre preuve de paiement n'a pas pu être validée. "
            + (f"Motif : {payment_proof.motif_rejet}. " if payment_proof.motif_rejet else "")
            + "Merci de déposer un nouveau justificatif."
        ),
        priority=Notification.PRIORITY_HIGH,
        link=link,
        send_email=True,
        email_heading="Votre preuve de paiement a été rejetée",
        email_paragraphs=[
            f"Votre preuve de paiement pour votre inscription en classe {class_group.name}{filiere_txt} n'a pas pu être validée.",
            (f"Motif : {payment_proof.motif_rejet}" if payment_proof.motif_rejet else
             "Merci de déposer un nouveau justificatif."),
        ],
        cta_url=cta_url,
        cta_label="Déposer un nouveau justificatif",
    )


def notify_class_students(class_group, notification_type, title, message,
                          priority='MEDIUM', link='', send_email=False, sender_email=None):
    """Notifie tous les étudiants actifs d'une classe."""
    from academic_core.apps.students.models import Enrollment
    enrollments = Enrollment.objects.filter(
        class_group=class_group, status=Enrollment.STATUS_VALIDATED
    ).select_related('student__user')
    recipients = [
        e.student.user for e in enrollments
        if e.student and getattr(e.student, 'user', None)
    ]
    notify_users(recipients, notification_type, title, message,
                 priority, link, send_email, sender_email=sender_email)
