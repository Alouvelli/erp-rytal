import os
from celery import Celery
from celery.schedules import crontab
from datetime import timedelta

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

app = Celery('academic_core')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

# ── Tâches planifiées ────────────────────────────────────────
app.conf.beat_schedule = {
    # Génère les fiches d'émargement chaque jour à 5h00
    'generate-attendance-sheets-daily': {
        'task':     'academic_core.apps.attendance.tasks.generate_daily_sheets',
        'schedule': crontab(hour=5, minute=0),
    },
    # Alerte absences excessives chaque lundi à 8h
    'check-absence-alerts-weekly': {
        'task':     'academic_core.apps.attendance.tasks.check_absence_alerts',
        'schedule': crontab(hour=8, minute=0, day_of_week='monday'),
    },
    # Alerte email tuteur + chef de département + assistante quand un étudiant
    # dépasse le seuil d'absences configuré par son département — chaque jour à 7h
    'check-student-absence-alerts-daily': {
        'task':     'academic_core.apps.attendance.tasks.check_student_absence_alerts_task',
        'schedule': crontab(hour=7, minute=0),
    },
    # Nettoyage des tokens expirés chaque nuit à 2h
    'cleanup-expired-tokens-nightly': {
        'task':     'academic_core.apps.accounts.tasks.cleanup_expired_tokens',
        'schedule': crontab(hour=2, minute=0),
    },
    # Envoi des rappels d'émargement non signés à 18h
    'remind-unsigned-sheets-evening': {
        'task':     'academic_core.apps.attendance.tasks.remind_unsigned_sheets',
        'schedule': crontab(hour=18, minute=0),
    },
    # Marquer Absent/Absente les non-pointés dès la fin de séance (toutes les 5 min)
    'auto-mark-absent-after-session': {
        'task':     'academic_core.apps.attendance.tasks.auto_mark_absent_after_session',
        'schedule': timedelta(minutes=5),
    },
    # Vérification des échéances de scolarité chaque jour à 6h00
    # Suspend les comptes impayés après le 10 du mois, réactive si soldés
    'check-tuition-deadlines-daily': {
        'task':     'academic_core.apps.students.tasks.check_tuition_deadlines',
        'schedule': crontab(hour=6, minute=0),
    },
    # Supprime les supports de cours partagés depuis plus de 72h (fichier + enregistrement)
    'cleanup-expired-course-supports-hourly': {
        'task':     'academic_core.apps.timetable.tasks.cleanup_expired_course_supports',
        'schedule': crontab(minute=0),
    },
}
