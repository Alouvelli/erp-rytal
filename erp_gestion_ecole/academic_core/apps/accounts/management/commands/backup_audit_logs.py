import gzip
import json
import os
from datetime import datetime
from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone
from academic_core.apps.accounts.models import AuditLog, AuditBackup


class Command(BaseCommand):
    help = 'Sauvegarde les journaux d\'audit dans un fichier compressé (.json.gz)'

    def add_arguments(self, parser):
        parser.add_argument('--full', action='store_true', help='Sauvegarde complète (ignore la dernière sauvegarde)')
        parser.add_argument('--user-id', type=int, default=None, help='ID de l\'utilisateur déclencheur')

    def handle(self, *args, **options):
        backup_dir = os.path.join(settings.MEDIA_ROOT, 'audit_backups')
        os.makedirs(backup_dir, exist_ok=True)

        # Déterminer la période à sauvegarder
        last_backup = AuditBackup.objects.first()  # ordered by -created_at
        if last_backup and not options['full']:
            qs = AuditLog.objects.filter(timestamp__gt=last_backup.period_end).order_by('timestamp')
            period_start = last_backup.period_end
        else:
            qs = AuditLog.objects.all().order_by('timestamp')
            period_start = None

        logs = list(qs.select_related('user'))
        if not logs:
            self.stdout.write(self.style.WARNING('Aucune nouvelle entrée à sauvegarder.'))
            return None

        period_end = logs[-1].timestamp
        if period_start is None:
            period_start = logs[0].timestamp

        # Sérialiser en JSON
        data = []
        for log in logs:
            data.append({
                'id': log.pk,
                'timestamp': log.timestamp.isoformat(),
                'user': log.user.username if log.user else None,
                'user_full_name': log.user.get_full_name() if log.user else None,
                'action': log.action,
                'action_label': log.get_action_display(),
                'model_name': log.model_name,
                'object_id': log.object_id,
                'object_repr': log.object_repr,
                'details': log.details,
                'url': log.url,
                'ip_address': str(log.ip_address) if log.ip_address else None,
                'user_agent': log.user_agent,
            })

        # Écrire le fichier gzip
        now_str = timezone.now().strftime('%Y%m%d_%H%M%S')
        file_name = f'audit_backup_{now_str}.json.gz'
        file_path = os.path.join(backup_dir, file_name)

        json_bytes = json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8')
        with gzip.open(file_path, 'wb') as f:
            f.write(json_bytes)

        file_size = os.path.getsize(file_path)

        # Enregistrer en base
        from academic_core.apps.accounts.models import User
        user = None
        if options.get('user_id'):
            try:
                user = User.objects.get(pk=options['user_id'])
            except User.DoesNotExist:
                pass

        backup = AuditBackup.objects.create(
            period_start=period_start,
            period_end=period_end,
            entries_count=len(logs),
            file_name=file_name,
            file_size=file_size,
            is_auto=options.get('user_id') is None,
            created_by=user,
        )

        self.stdout.write(self.style.SUCCESS(
            f'Sauvegarde créée : {file_name} ({len(logs)} entrées, {round(file_size/1024,1)} Ko)'
        ))
