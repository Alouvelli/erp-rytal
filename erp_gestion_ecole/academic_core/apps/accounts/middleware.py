from django.utils.deprecation import MiddlewareMixin

# URL name (app:name) → (action, description lisible)
_URL_ACTION_MAP = {
    # Dashboard
    'dashboard:index':                      ('VIEW',     'Tableau de bord'),
    # Emplois du temps
    'timetable:index':                      ('VIEW',     'Consultation des emplois du temps'),
    'timetable:room_swap':                  ('UPDATE',   'Permutation de salles'),
    # Émargements
    'attendance:sheet_list':                ('VIEW',     'Consultation des émargements'),
    'attendance:sheet_detail':              ('VIEW',     'Consultation d\'une fiche d\'émargement'),
    'attendance:sign_sheet':                ('VALIDATE', 'Signature d\'une fiche d\'émargement'),
    'attendance:validate_sheet':            ('VALIDATE', 'Validation d\'une fiche d\'émargement'),
    'attendance:sheet_edit':                ('UPDATE',   'Modification d\'une fiche d\'émargement'),
    'attendance:sheet_delete':              ('DELETE',   'Suppression d\'une fiche d\'émargement'),
    'attendance:record_attendance':         ('CREATE',   'Enregistrement de présence étudiant'),
    'attendance:update_attendance':         ('UPDATE',   'Mise à jour d\'une présence étudiant'),
    'attendance:delete_attendance':         ('DELETE',   'Suppression d\'une présence étudiant'),
    'attendance:extra_requests_admin':      ('VIEW',     'Consultation des demandes de séances supplémentaires'),
    'attendance:extra_request_review':      ('VALIDATE', 'Révision d\'une demande de séances supplémentaires'),
    'attendance:extra_request_create':      ('CREATE',   'Soumission d\'une demande de séances supplémentaires'),
    'attendance:my_extra_requests':         ('VIEW',     'Mes demandes de séances supplémentaires'),
    'attendance:my_modules':                ('VIEW',     'Consultation de mes modules'),
    # Annulations
    'cancellations:list':                   ('VIEW',     'Consultation des annulations / reports'),
    'cancellations:create':                 ('CREATE',   'Création d\'une annulation / report'),
    'cancellations:update':                 ('UPDATE',   'Modification d\'une annulation / report'),
    'cancellations:delete':                 ('DELETE',   'Suppression d\'une annulation / report'),
    # Notes & Évaluations
    'grades:evaluation_list':               ('VIEW',     'Consultation des évaluations et notes'),
    'grades:maquette_list':                 ('VIEW',     'Consultation des maquettes LMD'),
    'grades:maquette_ue_create':            ('CREATE',   'Création d\'une UE dans la maquette'),
    'grades:maquette_ue_edit':              ('UPDATE',   'Modification d\'une UE dans la maquette'),
    'grades:maquette_assign_subjects':      ('UPDATE',   'Assignation des EC à une UE'),
    'grades:bulletin_class_list':           ('VIEW',     'Consultation des bulletins LMD (sélection classe)'),
    'grades:bulletin_list':                 ('VIEW',     'Consultation des bulletins d\'une classe'),
    'grades:bulletin_preview':              ('VIEW',     'Consultation d\'un bulletin étudiant'),
    'grades:import_notes_csv':              ('CREATE',   'Import de notes (fichier CSV/Excel)'),
    'grades:export_grades_excel':           ('VIEW',     'Export des notes en Excel'),
    'grades:archive_bulletins_zip':         ('VIEW',     'Archivage des bulletins en ZIP'),
    # grades:grade_inline_update → loggé directement dans la vue avec contexte complet
    # Enseignants
    'teachers:list':                        ('VIEW',     'Consultation de la liste des enseignants'),
    'teachers:create':                      ('CREATE',   'Création d\'un enseignant'),
    'teachers:update':                      ('UPDATE',   'Modification d\'un enseignant'),
    'teachers:delete':                      ('DELETE',   'Suppression d\'un enseignant'),
    'teachers:detail':                      ('VIEW',     'Consultation du profil d\'un enseignant'),
    'teachers:my_honoraires':               ('VIEW',     'Consultation de mes honoraires'),
    # Étudiants
    'students:list':                        ('VIEW',     'Consultation de la liste des étudiants'),
    'students:create':                      ('CREATE',   'Création d\'un étudiant'),
    'students:edit':                        ('UPDATE',   'Modification d\'un étudiant'),
    'students:delete':                      ('DELETE',   'Suppression d\'un étudiant'),
    'students:detail':                      ('VIEW',     'Consultation du profil d\'un étudiant'),
    'students:import':                      ('CREATE',   'Import des étudiants (CSV)'),
    # Structure académique
    'academic_structure:index':             ('VIEW',     'Gestion de la scolarité'),
    'academic_structure:departments_manage':('VIEW',     'Gestion des départements'),
    'academic_structure:select_department': ('UPDATE',   'Changement de département actif'),
    # Salles
    'rooms:list':                           ('VIEW',     'Consultation de la liste des salles'),
    'rooms:create':                         ('CREATE',   'Création d\'une salle'),
    'rooms:edit':                           ('UPDATE',   'Modification d\'une salle'),
    'rooms:delete':                         ('DELETE',   'Suppression d\'une salle'),
    # Modules (EC)
    'subjects:list':                        ('VIEW',     'Consultation de la liste des modules (EC)'),
    'subjects:create':                      ('CREATE',   'Création d\'un module (EC)'),
    'subjects:edit':                        ('UPDATE',   'Modification d\'un module (EC)'),
    'subjects:delete':                      ('DELETE',   'Suppression d\'un module (EC)'),
    # Comptabilité
    'accounting:dashboard':                 ('VIEW',     'Consultation des honoraires mensuels'),
    'accounting:rate_list':                 ('VIEW',     'Consultation des taux horaires'),
    # Rapports
    'reports:index':                        ('VIEW',     'Consultation des rapports et exports'),
    # Comptes utilisateurs
    'accounts:users_list':                  ('VIEW',     'Consultation de la liste des utilisateurs'),
    'accounts:user_create':                 ('CREATE',   'Création d\'un utilisateur'),
    'accounts:user_edit':                   ('UPDATE',   'Modification d\'un utilisateur'),
    'accounts:user_delete':                 ('DELETE',   'Suppression d\'un utilisateur'),
    'accounts:profile':                     ('VIEW',     'Consultation de mon profil'),
    'accounts:password_change':             ('UPDATE',   'Changement de mot de passe'),
    'accounts:audit_user_detail':           ('VIEW',     'Consultation du journal d\'audit d\'un utilisateur'),
    # Notifications
    'notifications:list':                   ('VIEW',     'Consultation des notifications'),
    'notifications:notify_absence':         ('CREATE',   'Notification d\'absence / retard enseignant'),
}

_SKIP_PREFIXES = ('/static/', '/media/', '/admin/', '/favicon', '/api/grade-inline/', '/grades/api/grade-inline/', '__debug__')
_SKIP_URL_NAMES = {'accounts:login', 'accounts:logout', 'accounts:audit_log',
                   'accounts:audit_log_delete', 'accounts:audit_log_delete_all'}

# Mots-clés pour deviner l'action sur POST non mappés
_KEYWORD_ACTION = [
    ('delete',   'DELETE',   'Suppression d\'un élément'),
    ('remove',   'DELETE',   'Suppression d\'un élément'),
    ('create',   'CREATE',   'Création d\'un élément'),
    ('add',      'CREATE',   'Ajout d\'un élément'),
    ('import',   'CREATE',   'Import de données'),
    ('edit',     'UPDATE',   'Modification d\'un élément'),
    ('update',   'UPDATE',   'Modification d\'un élément'),
    ('validate', 'VALIDATE', 'Validation d\'un élément'),
    ('sign',     'VALIDATE', 'Signature'),
    ('review',   'VALIDATE', 'Révision'),
    ('swap',     'UPDATE',   'Permutation'),
]


def _get_ip(request):
    x = request.META.get('HTTP_X_FORWARDED_FOR')
    return x.split(',')[0].strip() if x else request.META.get('REMOTE_ADDR', '')


def _resolve_key(request):
    rm = getattr(request, 'resolver_match', None)
    if not rm:
        return None, None
    app = rm.app_name or rm.namespace or ''
    name = rm.url_name or ''
    return (f"{app}:{name}" if app else name), name


def _get_action_and_details(request, key, url_name_only, path):
    """Retourne (action_code, description) pour cette requête."""
    if key in _URL_ACTION_MAP:
        action, details = _URL_ACTION_MAP[key]
        if request.method == 'GET':
            return action, details
        # POST sur une URL mappée VIEW → chercher keyword
        if action != 'VIEW':
            return action, details

    # Fallback sur les mots-clés pour POST
    if request.method == 'POST':
        search = ((url_name_only or '') + ' ' + path).lower()
        for kw, act, label in _KEYWORD_ACTION:
            if kw in search:
                mapped = _URL_ACTION_MAP.get(key)
                return act, (mapped[1] if mapped else label)
        return 'UPDATE', _URL_ACTION_MAP.get(key, (None, 'Action sur la plateforme'))[1]

    # GET non mappé → description depuis le chemin
    parts = [p for p in path.strip('/').split('/') if p and not p.isdigit()]
    if parts:
        desc = 'Consultation : /' + '/'.join(parts[:3]) + '/'
    else:
        desc = 'Consultation de la plateforme'
    return 'VIEW', desc


class AuditMiddleware(MiddlewareMixin):
    """Résout l'IP réelle et trace toutes les actions des utilisateurs authentifiés."""

    def process_request(self, request):
        request.real_ip = _get_ip(request)

    def process_response(self, request, response):
        if not getattr(request, 'user', None) or not request.user.is_authenticated:
            return response

        path = request.path
        if any(path.startswith(p) for p in _SKIP_PREFIXES):
            return response

        key, url_name_only = _resolve_key(request)
        if key in _SKIP_URL_NAMES:
            return response

        if request.method == 'GET':
            if response.status_code != 200:
                return response
        elif request.method == 'POST':
            if response.status_code >= 500:
                return response
        else:
            return response

        action, details = _get_action_and_details(request, key, url_name_only, path)

        try:
            from .models import AuditLog
            AuditLog.objects.create(
                user=request.user,
                action=action,
                url=path[:500],
                details=details[:500] if details else '',
                ip_address=request.real_ip or None,
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
            )
        except Exception:
            pass

        return response
