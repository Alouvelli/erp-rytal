"""
Corrige rétroactivement le statut de validation des UE déjà enregistrées
(BulletinUEResult.is_validated) pour appliquer la règle correcte : une UE est
validée dès que sa moyenne pondérée est >= 10, quelles que soient les
moyennes des EC qui la composent (l'ancienne règle exigeait à tort qu'aucun
EC ne soit "Non Validé", ce qui invalidait des UE dont la moyenne réelle
était pourtant suffisante — voir compute_bulletin_data() dans
academic_core/apps/grades/services.py).

Ne touche JAMAIS Bulletin.status, .jury_decision, .mention ni .semester_average
(la moyenne semestrielle ne dépend pas du statut de validation des UE).

Fonctionne en deux passes, toutes deux idempotentes (ré-exécutable sans risque
à tout moment, y compris pour corriger des données déjà partiellement
corrigées) :
  1. Pour chaque UE enregistrée : recalcule is_validated/credits_obtained.
  2. Pour CHAQUE bulletin possédant au moins une UE (pas seulement ceux
     touchés en passe 1) : recalcule total_credits_obtained comme la SOMME
     FRAÎCHE (agrégat SQL) des credits_obtained de ses UE, et corrige si la
     valeur stockée diverge — quelle qu'en soit la cause. Cette passe n'incrémente
     JAMAIS une valeur en mémoire (delta += ...), ce qui évite toute perte de
     mise à jour si un bulletin a plusieurs UE modifiées dans la même exécution
     (contrairement à une première version de cette commande qui souffrait de
     ce bug).

Usage :
    python manage.py recompute_bulletin_ue_validation --dry-run
    python manage.py recompute_bulletin_ue_validation
    python manage.py recompute_bulletin_ue_validation --database db_rytal_isi_s_dhiou
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.conf import settings
from django.db import transaction
from django.db.models import Sum


class Command(BaseCommand):
    help = (
        "Recalcule le statut de validation des UE et le total de crédits "
        "obtenus des bulletins déjà enregistrés (idempotent, sans risque à "
        "ré-exécuter)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--database', type=str, default='',
            help="Limiter à une seule base (ex: db_rytal_isi). Par défaut : toutes les bases db_rytal_*.",
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help="N'écrit rien, affiche seulement ce qui serait changé.",
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        only_db = options['database'].strip()

        if only_db:
            aliases = [only_db]
        else:
            aliases = sorted(a for a in settings.DATABASES if a.startswith('db_rytal_'))

        grand_total_ue = 0
        grand_total_bulletins = 0

        for alias in aliases:
            self.stdout.write(self.style.MIGRATE_HEADING(f'\n=== Base : {alias} ==='))
            try:
                nb_ue, nb_bul = self._process_db(alias, dry_run)
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f'  [ERREUR] {alias} : {exc}'))
                continue
            grand_total_ue += nb_ue
            grand_total_bulletins += nb_bul

        verb = "seraient corrigé(e)s" if dry_run else "corrigé(e)s"
        self.stdout.write(self.style.SUCCESS(
            f"\n{grand_total_ue} UE et {grand_total_bulletins} total(aux) de bulletin {verb}."
        ))
        if dry_run:
            self.stdout.write(self.style.WARNING("(--dry-run : aucune écriture effectuée)"))

    def _process_db(self, alias, dry_run):
        from academic_core.apps.grades.models import BulletinUEResult, Bulletin
        from academic_core.db_router import set_current_db

        # Requis : les accès paresseux ci-dessous (ue.subjects.all(),
        # ue_result.ec_results.all()) ne respectent PAS un .using(alias)
        # explicite sur la requête d'origine — le routeur multi-tenant route
        # les modèles tenant via le thread-local get_current_db(), jamais via
        # l'état de l'instance. Sans cet appel, ces accès retomberaient sur la
        # base 'default' (vide côté tenant) et calculeraient des crédits à 0.
        set_current_db(alias)

        nb_ue_touched = 0
        nb_bulletins_touched = 0

        with transaction.atomic(using=alias):
            # ── Passe 1 : is_validated / credits_obtained par UE ──────────────
            ue_results = (
                BulletinUEResult.objects.using(alias)
                .filter(average__isnull=False)
                .select_related('bulletin__student__user', 'bulletin__semester', 'ue')
                .prefetch_related('ec_results')
            )

            for ue_result in ue_results:
                ec_apprs = [ec.appreciation for ec in ue_result.ec_results.all()]
                if 'A faire' in ec_apprs:
                    new_validated = False
                else:
                    new_validated = ue_result.average >= Decimal('10')

                if new_validated == ue_result.is_validated:
                    continue

                ue_credits = sum(int(s.credits or 0) for s in ue_result.ue.subjects.all())
                new_credits_obtained = ue_credits if new_validated else 0

                bulletin = ue_result.bulletin
                self.stdout.write(
                    f"  [UE] {bulletin.student.user.get_full_name()} - S{bulletin.semester.number} - "
                    f"{ue_result.ue.code} (moy={ue_result.average}) : "
                    f"{'Validée' if ue_result.is_validated else 'Non Validée'} -> "
                    f"{'Validée' if new_validated else 'Non Validée'} "
                    f"(crédits {ue_result.credits_obtained} -> {new_credits_obtained})"
                )

                if not dry_run:
                    ue_result.is_validated = new_validated
                    ue_result.credits_obtained = new_credits_obtained
                    ue_result.save(update_fields=['is_validated', 'credits_obtained'])

                nb_ue_touched += 1

            # ── Passe 2 : total_credits_obtained de CHAQUE bulletin, recalculé
            # comme une somme fraîche (agrégat SQL) — jamais un incrément en
            # mémoire, pour ne perdre aucune mise à jour même si un même
            # bulletin a plusieurs UE modifiées dans cette exécution. Passe
            # volontairement sur TOUS les bulletins (pas seulement ceux
            # touchés en passe 1) pour corriger aussi toute incohérence
            # préexistante, quelle qu'en soit l'origine.
            bulletins = Bulletin.objects.using(alias).all()
            for bulletin in bulletins:
                fresh_total = BulletinUEResult.objects.using(alias).filter(
                    bulletin=bulletin
                ).aggregate(s=Sum('credits_obtained'))['s'] or 0

                if fresh_total == (bulletin.total_credits_obtained or 0):
                    continue

                self.stdout.write(
                    f"  [BULLETIN] {bulletin} : total_credits_obtained "
                    f"{bulletin.total_credits_obtained} -> {fresh_total}"
                )
                if not dry_run:
                    Bulletin.objects.using(alias).filter(pk=bulletin.pk).update(
                        total_credits_obtained=fresh_total
                    )
                nb_bulletins_touched += 1

            if dry_run:
                transaction.set_rollback(True, using=alias)

        return nb_ue_touched, nb_bulletins_touched
