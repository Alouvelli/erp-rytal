from django.apps import AppConfig


class DashboardConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name  = 'academic_core.apps.dashboard'
    label = 'dashboard'
    verbose_name = 'Tableau de Bord'

    def ready(self):
        from django.db.backends.signals import connection_created

        def _configure_sqlite_wal(sender, connection, **kwargs):
            if connection.vendor != 'sqlite':
                return
            with connection.cursor() as cursor:
                # WAL : lectures et écritures simultanées sans blocage mutuel
                cursor.execute('PRAGMA journal_mode=WAL;')
                # NORMAL : flush au point de contrôle WAL seulement (plus rapide, sûr avec WAL)
                cursor.execute('PRAGMA synchronous=NORMAL;')
                # Attendre jusqu'à 5 s avant de lever "database is locked"
                cursor.execute('PRAGMA busy_timeout=5000;')
                # Cache de 20 Mo en mémoire (valeur négative = kilo-octets)
                cursor.execute('PRAGMA cache_size=-20000;')
                # Intégrité référentielle active
                cursor.execute('PRAGMA foreign_keys=ON;')
                # Tables temporaires en mémoire
                cursor.execute('PRAGMA temp_store=MEMORY;')
                # Taille du checkpoint WAL (en pages de 4 Ko) avant auto-checkpoint
                cursor.execute('PRAGMA wal_autocheckpoint=1000;')

        connection_created.connect(_configure_sqlite_wal)
