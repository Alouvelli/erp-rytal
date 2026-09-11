"""
Moteur de réponse RYTAL sans LLM : associe le message de l'utilisateur à l'un
des outils autorisés pour son rôle par simple correspondance de mots-clés
(français, insensible à la casse et aux accents), exécute cet outil (données
réelles, périmètre déjà garanti par permissions.py/tools/*), puis met le
résultat en forme en français. Aucun appel réseau, aucun coût, aucune
hallucination possible : soit l'outil renvoie des données réelles, soit RYTAL
répond qu'il n'a pas compris et rappelle ce qu'il sait faire.

Bascule prévue vers un LLM plus tard via settings.CHATBOT_USE_LLM — ce module
reste alors utilisable comme repli.
"""
import re
import unicodedata

from django.urls import reverse, NoReverseMatch

from . import permissions

# Marqueur de fin de message reconnu par le widget (chatbot.js) pour afficher
# un lien cliquable vers la page correspondante. Toujours généré par ce
# module (jamais recopié depuis un champ texte modifiable en base — voir
# `_append_link`), donc sûr même si un contenu affiché contient par coïncidence
# la chaîne "[RYTAL_LINK]".
LINK_MARKER = '[RYTAL_LINK]'

# tool_name -> (nom de l'URL Django, libellé du lien affiché)
TOOL_LINKS = {
    'get_my_timetable': ('timetable:index', "Voir mon emploi du temps"),
    'get_my_teaching_timetable': ('timetable:index', "Voir mon emploi du temps"),
    'get_my_grades': ('grades:evaluation_list', "Voir mes notes"),
    'get_my_bulletin': ('grades:evaluation_list', "Voir mes notes"),
    'get_my_absences': ('attendance:my_absences', "Voir mes absences"),
    'get_my_classes': ('attendance:my_modules', "Voir mes modules"),
    'get_my_session_log': ('timetable:mes_seances', "Voir mon cahier de texte"),
    'get_my_honoraires': ('teachers:my_honoraires', "Voir mes honoraires"),
    'get_my_contract': ('teachers:mes_contrats', "Voir mon contrat"),
    'get_my_extra_requests': ('attendance:my_extra_requests', "Voir mes demandes"),
    'get_my_shared_course_supports': ('timetable:teacher_supports_list', "Voir mes supports de cours"),
    'get_my_course_supports': ('timetable:student_supports_list', "Voir les supports de cours"),
    'list_institutes': ('academic_structure:institut_list', "Voir les instituts"),
    'list_institut_admins': ('accounts:inst_admin_list', "Voir les administrateurs d'institut"),
    'get_institut_overview': ('dashboard:index', "Voir le tableau de bord"),
    'get_pending_cancellations': ('cancellations:list', "Voir les annulations/reports"),
    'get_institut_users_summary': ('accounts:users_list', "Voir les utilisateurs"),
    'get_institut_finance_summary': ('accounting:validation_inscription_list', "Voir les inscriptions"),
    'get_department_pending_cancellations': ('cancellations:list', "Voir les annulations/reports"),
    'get_department_enrollment_summary': ('students:list', "Voir les inscriptions"),
    'get_my_notifications': ('notifications:list', "Voir mes notifications"),
}


def _append_link(text, tool_name):
    """Ajoute, si connu, un marqueur de lien à la toute fin du message —
    jamais mêlé au texte formaté lui-même, pour qu'aucune donnée affichée
    (commentaire, remarque...) ne puisse se faire passer pour ce lien."""
    link_info = TOOL_LINKS.get(tool_name)
    if not link_info:
        return text
    url_name, label = link_info
    try:
        url = reverse(url_name)
    except NoReverseMatch:
        return text
    return f"{text}\n{LINK_MARKER}{url}|{label}"


# tool_name -> mots-clés déclenchant cet outil (comparés sur texte normalisé)
TOOL_KEYWORDS = {
    'get_my_bulletin': ['bulletin'],
    'get_my_grades': ['note', 'notes', 'evaluation', 'evaluations', 'moyenne', 'moyennes'],
    'get_my_absences': ['absence', 'absences', 'presence', 'presences', 'retard', 'retards'],
    'get_my_timetable': [
        'emploi du temps', 'edt', 'planning', 'horaire', 'horaires', 'cours',
        'seance', 'seances', 'creneau', 'creneaux',
    ],
    'get_my_classes': ['classe', 'classes', 'mes classes'],
    'get_my_session_log': [
        'cahier de texte', 'cahier', 'contenu de cours', 'contenu de seance',
        'objectifs de seance',
    ],
    'get_class_attendance_summary': [
        'presence', 'presences', 'absence', 'absences', 'assiduite', 'emargement', 'emargements',
    ],
    'get_my_teaching_timetable': [
        'emploi du temps', 'edt', 'planning', 'horaire', 'horaires', 'cours',
        'seance', 'seances', 'creneau', 'creneaux',
    ],
    'get_department_timetable': [
        'emploi du temps', 'edt', 'planning', 'horaire', 'horaires', 'cours',
    ],
    'get_department_grades_summary': [
        'note', 'notes', 'moyenne', 'moyennes', 'resultat', 'resultats', 'evaluation', 'evaluations',
        'bulletin', 'bulletins', 'releve de notes', 'releves de notes',
    ],
    'get_department_attendance_summary': [
        'presence', 'presences', 'absence', 'absences', 'assiduite', 'absenteisme',
    ],
    'get_my_honoraires': [
        'honoraire', 'honoraires', 'salaire', 'paiement', 'paye', 'remuneration',
    ],
    'get_my_contract': ['contrat', 'contrats'],
    'get_my_extra_requests': [
        'seance supplementaire', 'seances supplementaires', 'heure supplementaire',
        'heures supplementaires', 'rattrapage de seance',
    ],
    'get_my_shared_course_supports': [
        'support de cours', 'supports de cours', 'support', 'supports', 'document de cours',
        'polycopie', 'polycopies',
    ],
    'get_my_course_supports': [
        'support de cours', 'supports de cours', 'support', 'supports', 'document de cours',
        'polycopie', 'polycopies',
    ],
    'list_institutes': [
        'institut', 'instituts', 'institution', 'institutions', 'etablissement', 'etablissements',
        'abonnement', 'abonnements',
    ],
    'list_institut_admins': [
        'administrateur', 'administrateurs', 'administrateur d\'institut', 'administrateurs d\'institut',
        'admin institut', 'admins institut',
    ],
    'get_pending_cancellations': [
        'annulation', 'annulations', 'report', 'reports', 'reporte', 'seance annulee',
        'seances annulees', 'seance reportee',
    ],
    'get_institut_users_summary': [
        'utilisateur', 'utilisateurs', 'personnel', 'effectif du personnel',
        'repartition des utilisateurs',
    ],
    'get_institut_finance_summary': [
        'finance', 'finances', 'financier', 'financiere', 'recette', 'recettes',
        'encaissement', 'encaissements', 'recouvrement', 'inscription', 'inscriptions',
        'reste a recouvrer',
    ],
    'get_institut_overview': [
        'apercu', 'vue d\'ensemble', 'chiffres cles', 'effectif', 'effectifs',
        'tableau de bord', 'bilan de l\'institut', 'resume de l\'institut',
    ],
    'get_department_pending_cancellations': [
        'annulation', 'annulations', 'report', 'reports', 'reporte', 'seance annulee',
        'seances annulees', 'seance reportee',
    ],
    'get_department_enrollment_summary': [
        'inscription', 'inscriptions', 'liste des etudiants', 'liste des inscriptions',
        'etudiants inscrits', 'nouvelles inscriptions',
    ],
    'get_my_notifications': [
        'notification', 'notifications', 'alerte', 'alertes',
    ],
}

# Ordre de priorité : les intitulés les plus spécifiques doivent être testés
# avant les plus génériques pour éviter qu'un mot-clé large (ex: "absence")
# n'écrase un outil plus précis (ex: bulletin) quand les deux figurent dans
# la même phrase.
TOOL_PRIORITY = [
    'get_my_notifications',
    'get_department_pending_cancellations',
    'get_pending_cancellations',
    'get_department_enrollment_summary',
    'get_institut_users_summary',
    'get_institut_finance_summary',
    'get_institut_overview',
    'list_institut_admins',
    'list_institutes',
    'get_my_extra_requests',
    'get_my_honoraires',
    'get_my_contract',
    'get_my_shared_course_supports',
    'get_my_course_supports',
    'get_my_bulletin',
    'get_my_session_log',
    'get_my_classes',
    'get_my_grades',
    'get_department_grades_summary',
    'get_my_absences',
    'get_class_attendance_summary',
    'get_department_attendance_summary',
    'get_my_timetable',
    'get_my_teaching_timetable',
    'get_department_timetable',
]

# Libellés humains utilisés dans le message d'aide quand rien n'a été reconnu.
CAPABILITY_LABELS = {
    'get_my_timetable': "ton emploi du temps",
    'get_my_teaching_timetable': "ton emploi du temps",
    'get_my_grades': "tes notes",
    'get_my_bulletin': "ton bulletin",
    'get_my_absences': "tes absences",
    'get_my_classes': "tes classes",
    'get_my_session_log': "ton cahier de texte",
    'get_class_attendance_summary': "les présences de tes séances",
    'get_department_timetable': "l'emploi du temps du département",
    'get_department_grades_summary': "les moyennes du département",
    'get_department_attendance_summary': "les présences du département",
    'get_my_honoraires': "tes honoraires",
    'get_my_contract': "ton contrat",
    'get_my_extra_requests': "tes demandes de séances supplémentaires",
    'get_my_shared_course_supports': "tes supports de cours partagés",
    'get_my_course_supports': "les supports de cours de ta classe",
    'list_institutes': "la liste des instituts et leur abonnement",
    'list_institut_admins': "les administrateurs d'institut",
    'get_institut_overview': "les chiffres clés de l'institut",
    'get_pending_cancellations': "les annulations/reports en attente",
    'get_institut_users_summary': "la répartition des utilisateurs",
    'get_institut_finance_summary': "le résumé financier de l'institut",
    'get_department_pending_cancellations': "les annulations/reports en attente",
    'get_department_enrollment_summary': "les inscriptions en attente/validées",
    'get_my_notifications': "tes notifications",
}


def _normalize(text):
    text = text.lower()
    text = unicodedata.normalize('NFKD', text)
    return ''.join(c for c in text if not unicodedata.combining(c))


def _tokenize(normalized_text):
    return set(re.findall(r'[a-z0-9]+', normalized_text))


def _keyword_score(keyword, normalized_text, tokens):
    """None si le mot-clé ne matche pas, sinon (est_exact, nb_mots_significatifs) :
    - est_exact=1 si la phrase apparaît telle quelle (substring littérale) —
      toujours prioritaire, un utilisateur qui tape le mot exact ne doit
      jamais être doublé par une correspondance devinée ;
    - est_exact=0 si tous les mots significatifs du mot-clé (hors mots courts
      comme « de », « du », « le ») apparaissent ailleurs dans le message,
      dans n'importe quel ordre — pour deviner l'intention même quand
      l'utilisateur ne reprend pas l'expression exacte du message d'aide.
    nb_mots_significatifs départage ensuite entre mots-clés de même nature :
    plus un mot-clé est précis (long), plus il l'emporte sur un synonyme
    générique isolé (ex. 'emploi du temps' > 'cours')."""
    words = [w for w in re.findall(r'[a-z0-9]+', keyword) if len(w) > 2]
    nb_words = max(len(words), 1)
    if keyword in normalized_text:
        return (1, nb_words)
    if words and all(w in tokens for w in words):
        return (0, nb_words)
    return None


def match_tool(user_text, allowed_tool_names):
    normalized = _normalize(user_text)
    tokens = _tokenize(normalized)
    allowed = set(allowed_tool_names)

    best_tool, best_score = None, (0, 0)
    for tool_name in TOOL_PRIORITY:
        if tool_name not in allowed:
            continue
        scores = [
            score for score in (
                _keyword_score(keyword, normalized, tokens)
                for keyword in TOOL_KEYWORDS.get(tool_name, [])
            )
            if score is not None
        ]
        if not scores:
            continue
        score = max(scores)
        if score > best_score:
            best_score, best_tool = score, tool_name
    return best_tool


def _fmt_hours(volume):
    if volume is None:
        return '—'
    v = float(volume)
    if v == int(v):
        return f'{int(v)}H'
    return f'{v:.2f}'.rstrip('0').rstrip('.') + 'H'


def _format_timetable(result):
    entries = result.get('entries', [])
    if result.get('note'):
        return result['note']
    if not entries:
        return "Aucun créneau trouvé pour le moment."
    lines = ["Voici les créneaux trouvés :"]
    for e in entries:
        parts = [f"- {e['day_of_week']} {e['start_time']}–{e['end_time']} : {e['subject']}"]
        if e.get('class_group'):
            parts.append(f"(classe {e['class_group']})")
        if e.get('teacher'):
            parts.append(f"— {e['teacher']}")
        if e.get('room'):
            parts.append(f"— salle {e['room']}")
        lines.append(' '.join(parts))
    return '\n'.join(lines)


def _format_grades(result):
    grades = result.get('grades', [])
    if not grades:
        return "Aucune note trouvée pour le moment."
    lines = ["Voici tes notes :"]
    for g in grades:
        lines.append(
            f"- {g['subject']} ({g['evaluation_type']} — {g['title']}, {g['date']}) : "
            f"{g['score']}/{g['max_score']}"
        )
    return '\n'.join(lines)


def _format_bulletin(result):
    bulletins = result.get('bulletins', [])
    if not bulletins:
        return "Aucun bulletin disponible pour le moment."
    lines = ["Voici ton/tes bulletin(s) :"]
    for b in bulletins:
        avg = b['semester_average'] if b['semester_average'] is not None else '—'
        lines.append(
            f"- {b['semester']} : moyenne {avg}, mention {b['mention'] or '—'}, "
            f"statut {b['status']}, crédits {b['total_credits_obtained']}/{b['total_credits_possible']}"
        )
    return '\n'.join(lines)


def _format_absences(result):
    stats = result.get('stats', {})
    records = result.get('records', [])
    if not stats:
        return "Aucune donnée de présence pour le moment."
    lines = [
        f"Résumé : {stats.get('total', 0)} séance(s) — "
        f"{stats.get('present', 0)} présent(s), {stats.get('absent', 0)} absent(s), "
        f"{stats.get('justified', 0)} justifiée(s), {stats.get('late', 0)} retard(s)."
    ]
    if records:
        lines.append("Détail récent :")
        for r in records[:10]:
            comment = f" ({r['comment']})" if r.get('comment') else ''
            lines.append(f"- {r['date']} — {r['subject']} : {r['status']}{comment}")
    return '\n'.join(lines)


def _format_classes(result):
    classes = result.get('classes', [])
    if not classes:
        return "Aucune classe affectée pour le moment."
    lines = ["Voici tes classes :"]
    for c in classes:
        subjects = ', '.join(c.get('subjects', [])) or '—'
        lines.append(f"- {c['class_group']} ({subjects})")
    return '\n'.join(lines)


def _format_session_log(result):
    sessions = result.get('sessions', [])
    if not sessions:
        return "Aucune séance enregistrée dans le cahier de texte pour le moment."
    lines = ["Voici les dernières séances de ton cahier de texte :"]
    for s in sessions[:10]:
        lines.append(f"- {s['date']} — {s['subject']} ({s['class_group']}) : {s['objectives']}")
    return '\n'.join(lines)


def _format_class_attendance_summary(result):
    stats = result.get('stats', {})
    if not stats:
        return "Aucune donnée de présence pour le moment."
    return (
        f"Résumé de tes séances : {stats.get('total', 0)} présence(s) enregistrée(s) — "
        f"{stats.get('present', 0)} présent(s), {stats.get('absent', 0)} absent(s), "
        f"{stats.get('justified', 0)} justifiée(s), {stats.get('late', 0)} retard(s)."
    )


def _format_department_grades_summary(result):
    if result.get('note'):
        return result['note']
    subjects = result.get('subjects', [])
    if not subjects:
        return "Aucune note trouvée pour le département sélectionné."
    lines = ["Moyennes par module (EC) (département) :"]
    for s in subjects:
        avg = round(s['average'], 2) if s['average'] is not None else '—'
        lines.append(f"- {s['subject']} : moyenne {avg} ({s['nb_notes']} note(s))")
    return '\n'.join(lines)


def _format_department_attendance_summary(result):
    if result.get('note'):
        return result['note']
    stats = result.get('stats', {})
    return (
        f"Présences du département : {stats.get('total', 0)} enregistrement(s) — "
        f"{stats.get('present', 0)} présent(s), {stats.get('absent', 0)} absent(s), "
        f"{stats.get('justified', 0)} justifiée(s), {stats.get('late', 0)} retard(s)."
    )


def _format_honoraires(result):
    if not result.get('nb_sessions'):
        return "Aucun honoraire enregistré pour le mois en cours."
    return (
        f"Ce mois-ci : {result['nb_sessions']} séance(s) validée(s) pour un total de "
        f"{result['total']} FCFA (net à payer : {result['net']} FCFA)."
    )


def _format_contract(result):
    contrats = result.get('contrats', [])
    if not contrats:
        return "Aucun contrat généré pour le moment — il apparaîtra automatiquement dès qu'un module te sera affecté."
    lines = ["Voici ton/tes contrat(s) :"]
    for c in contrats:
        lines.append(f"- {c['department']} ({c['academic_year']})")
    lines.append("Télécharge le PDF depuis la page « Mon Contrat ».")
    return '\n'.join(lines)


def _format_extra_requests(result):
    requests = result.get('requests', [])
    if not requests:
        return "Aucune demande de séance supplémentaire pour le moment."
    lines = ["Voici tes demandes de séances supplémentaires :"]
    for r in requests:
        approved = f", {r['extra_hours_approved']}h approuvée(s)" if r.get('extra_hours_approved') else ''
        lines.append(f"- {r['subject']} ({r['class_group']}) : {r['extra_hours_requested']}h demandée(s) — {r['status']}{approved}")
    return '\n'.join(lines)


def _format_course_supports(result):
    supports = result.get('supports', [])
    if result.get('note'):
        return result['note']
    if not supports:
        return "Aucun support de cours disponible pour le moment."
    lines = ["Voici les supports de cours disponibles :"]
    for s in supports:
        who = f" — {s['teacher']}" if 'teacher' in s else ''
        lines.append(f"- {s['title']} ({s['subject']}, {s['type']}){who}")
    return '\n'.join(lines)


def _format_institutes(result):
    instituts = result.get('instituts', [])
    if not instituts:
        return "Aucun institut enregistré pour le moment."
    lines = [f"Voici les {len(instituts)} institut(s) de la plateforme :"]
    for i in instituts:
        statut = "actif" if i['actif'] else "suspendu"
        lines.append(f"- {i['nom']} ({i['sigle']}) — {statut}, abonnement : {i['abonnement_statut']}")
    return '\n'.join(lines)


def _format_institut_admins(result):
    admins = result.get('admins', [])
    if not admins:
        return "Aucun administrateur d'institut enregistré pour le moment."
    lines = [f"Voici les {len(admins)} administrateur(s) d'institut :"]
    for a in admins:
        lines.append(f"- {a['nom']} ({a['role']}) — {a['institut']} — {a['email']}")
    return '\n'.join(lines)


def _format_institut_overview(result):
    if result.get('note'):
        return result['note']
    return (
        f"Chiffres clés de l'institut : {result['total_students']} étudiant(s), "
        f"{result['total_teachers']} enseignant(s), {result['total_users']} utilisateur(s) actif(s). "
        f"Émargement : {result['sheets_pending']} feuille(s) en attente, "
        f"{result['sheets_validated']} validée(s). "
        f"Annulations/reports en attente : {result['cancellations_pending']}."
    )


def _format_pending_cancellations(result):
    if result.get('note'):
        return result['note']
    cancels = result.get('cancellations', [])
    if not cancels:
        return "Aucune annulation/report en attente pour le moment."
    lines = [f"Voici les {len(cancels)} demande(s) en attente :"]
    for c in cancels:
        lines.append(
            f"- {c['type']} du {c['session_date']} — {c['subject']} ({c['class_group']}), "
            f"demandé par {c['requested_by']} : {c['reason']}"
        )
    return '\n'.join(lines)


def _format_institut_users_summary(result):
    if result.get('note'):
        return result['note']
    roles = result.get('roles', [])
    if not roles:
        return "Aucun utilisateur actif trouvé pour l'institut sélectionné."
    lines = ["Répartition des utilisateurs actifs :"]
    for r in roles:
        lines.append(f"- {r['role']} : {r['total']}")
    return '\n'.join(lines)


def _fmt_fcfa(amount):
    return f"{int(amount):,}".replace(',', ' ') + " FCFA"


def _format_institut_finance_summary(result):
    if result.get('note'):
        return result['note']
    return (
        f"Inscriptions : {result['nb_pending']} en attente, {result['nb_validated']} validée(s). "
        f"Encaissé aujourd'hui : {_fmt_fcfa(result['encaisse_jour'])} — ce mois-ci : "
        f"{_fmt_fcfa(result['encaisse_mois'])}. "
        f"Total encaissé (inscriptions validées) : {_fmt_fcfa(result['total_collected'])}, "
        f"reste à recouvrer : {_fmt_fcfa(result['total_remaining'])}."
    )


def _format_department_enrollment_summary(result):
    if result.get('note'):
        return result['note']
    lines = [
        f"Inscriptions : {result['nb_pending']} en attente, {result['nb_validated']} validée(s)."
    ]
    pending = result.get('pending_list', [])
    if pending:
        lines.append("Dernières inscriptions en attente :")
        for p in pending[:10]:
            lines.append(f"- {p['student']} ({p['matricule']}) — {p['class_group']}, le {p['enrollment_date']}")
    return '\n'.join(lines)


def _format_my_notifications(result):
    notifs = result.get('notifications', [])
    unread = result.get('unread_count', 0)
    if not notifs:
        return "Aucune notification pour le moment."
    lines = [f"Tu as {unread} notification(s) non lue(s) :"]
    for n in notifs[:10]:
        marker = '●' if not n['is_read'] else '○'
        lines.append(f"- {marker} {n['title']} ({n['created_at']})")
    return '\n'.join(lines)


FORMATTERS = {
    'get_my_timetable': _format_timetable,
    'get_my_teaching_timetable': _format_timetable,
    'get_department_timetable': _format_timetable,
    'get_my_grades': _format_grades,
    'get_my_bulletin': _format_bulletin,
    'get_my_absences': _format_absences,
    'get_my_classes': _format_classes,
    'get_my_session_log': _format_session_log,
    'get_class_attendance_summary': _format_class_attendance_summary,
    'get_department_grades_summary': _format_department_grades_summary,
    'get_department_attendance_summary': _format_department_attendance_summary,
    'get_my_honoraires': _format_honoraires,
    'get_my_contract': _format_contract,
    'get_my_extra_requests': _format_extra_requests,
    'get_my_shared_course_supports': _format_course_supports,
    'get_my_course_supports': _format_course_supports,
    'list_institutes': _format_institutes,
    'list_institut_admins': _format_institut_admins,
    'get_institut_overview': _format_institut_overview,
    'get_pending_cancellations': _format_pending_cancellations,
    'get_institut_users_summary': _format_institut_users_summary,
    'get_institut_finance_summary': _format_institut_finance_summary,
    'get_department_pending_cancellations': _format_pending_cancellations,
    'get_department_enrollment_summary': _format_department_enrollment_summary,
    'get_my_notifications': _format_my_notifications,
}


# Petites phrases de courtoisie — non reliées à un outil, mais méritent une
# réponse chaleureuse plutôt que le message générique « je n'ai pas compris »,
# qui donnait l'impression que RYTAL ne comprenait rien du tout.
GREETING_KEYWORDS = ['bonjour', 'salut', 'bonsoir', 'coucou', 'hello', 'bonne journee', 'bonne soiree']
THANKS_KEYWORDS = ['merci', 'merci beaucoup', 'merci bien']
HELP_KEYWORDS = [
    'aide', 'aide moi', 'que peux tu faire', 'que sais tu faire', 'options',
    'que puis je faire', 'quelles sont mes options', 'comment ca marche', 'menu',
]


def _matches_any(keywords, normalized, tokens):
    return any(_keyword_score(kw, normalized, tokens) is not None for kw in keywords)


def _capabilities_sentence(user):
    allowed = permissions.get_allowed_tool_names(user)
    if not allowed:
        return "je peux t'aider à naviguer dans l'application, mais je ne consulte pas encore de données personnalisées pour ton profil"
    labels = sorted({CAPABILITY_LABELS[n] for n in allowed if n in CAPABILITY_LABELS})
    return "je peux te renseigner sur : " + ', '.join(labels)


def _greeting_reply(user):
    first_name = getattr(user, 'first_name', '') or user.get_username()
    sentence = _capabilities_sentence(user)
    return f"Bonjour {first_name} ! {sentence[0].upper()}{sentence[1:]}. Que veux-tu savoir ?"


def _thanks_reply():
    return "Avec plaisir ! N'hésite pas si tu as d'autres questions."


def _help_reply(user):
    return f"Bien sûr, {_capabilities_sentence(user)}. Dis-moi simplement ce qui t'intéresse."


def _help_message(user):
    sentence = _capabilities_sentence(user)
    return f"Je n'ai pas trouvé de réponse précise à ta demande. Pour rappel, {sentence}."


def respond(request, conversation, user_text, institut_config=None):
    """Point d'entrée du moteur à règles — même signature que llm.run_chat_turn."""
    user = request.user
    allowed = permissions.get_allowed_tool_names(user)

    tool_name = match_tool(user_text, allowed)
    if not tool_name:
        normalized = _normalize(user_text)
        tokens = _tokenize(normalized)
        if _matches_any(THANKS_KEYWORDS, normalized, tokens):
            return _thanks_reply()
        if _matches_any(HELP_KEYWORDS, normalized, tokens):
            return _help_reply(user)
        if _matches_any(GREETING_KEYWORDS, normalized, tokens):
            return _greeting_reply(user)
        return _help_message(user)

    handler = permissions.get_tool_handler(tool_name, user)
    if handler is None:
        return _help_message(user)

    try:
        result = handler(user, request)
    except Exception:
        import logging
        logging.getLogger(__name__).exception(
            'chatbot rule_engine: échec outil %s pour user=%s', tool_name, user.pk,
        )
        return "Une erreur est survenue en récupérant cette information. Réessaie plus tard."

    formatter = FORMATTERS.get(tool_name)
    text = formatter(result) if formatter else "Voici les informations demandées."
    # Neutralise toute occurrence préexistante du marqueur avant d'ajouter le
    # vrai lien (défense en profondeur si un champ affiché contenait la chaîne
    # par coïncidence) — seul CE lien, ajouté en dernier par ce module, compte.
    text = text.replace(LINK_MARKER, '')
    return _append_link(text, tool_name)
