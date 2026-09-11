"""
Commande quotidienne de vérification des abonnements instituts.

Comportement :
  - Envoie un mail de rappel à l'administrateur d'institut (INST_ADMIN) à 60, 30, 15 et 5 jours
    avant l'expiration, si le rappel n'a pas encore été envoyé pour ce seuil.
  - Si l'abonnement a expiré (date_fin < today) et n'est pas renouvelé → suspend l'institut
    (InstitutConfig.actif = False) et marque l'abonnement EXPIRE.

Usage :
  python manage.py check_abonnements --settings=config.settings.development
"""

from datetime import date

from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.conf import settings

SEUILS_RAPPEL = [60, 30, 15, 5]  # jours avant expiration


def _admins_for_config(config):
    """Retourne les utilisateurs INST_ADMIN liés à cette config."""
    from academic_core.apps.accounts.models import User, Role
    return User.objects.filter(
        institut_config=config,
        role__name=Role.INST_ADMIN,
        is_active=True,
    ).exclude(email='')


def _send_rappel(abonnement, jours_restants):
    """Envoie le mail de rappel et marque le seuil comme notifié."""
    config = abonnement.config
    admins = _admins_for_config(config)
    if not admins.exists():
        return False

    date_exp = abonnement.date_fin.strftime('%d/%m/%Y')
    nom_institut = config.nom or config.sigle or 'Votre institut'

    if jours_restants <= 5:
        urgence = "⚠️ URGENT — "
    elif jours_restants <= 15:
        urgence = "⚠️ "
    else:
        urgence = ""

    sujet = (
        f"{urgence}Abonnement {nom_institut} — expiration dans {jours_restants} jour(s)"
    )
    corps = f"""Bonjour,

Ceci est un rappel automatique concernant l'abonnement de {nom_institut}.

Votre abonnement à la plateforme de gestion académique expire le {date_exp},
soit dans {jours_restants} jour(s).

⚠️ Si vous ne renouvelez pas avant cette date, l'accès à votre établissement
sera automatiquement suspendu.

Pour renouveler votre abonnement, veuillez contacter l'équipe technique.

Cordialement,
Le système de gestion académique
"""

    destinataires = [u.email for u in admins]
    try:
        send_mail(
            sujet,
            corps,
            settings.DEFAULT_FROM_EMAIL,
            destinataires,
            fail_silently=False,
        )
        # Marquer ce seuil comme notifié
        rappels = list(abonnement.rappels_envoyes or [])
        rappels.append(jours_restants)
        abonnement.rappels_envoyes = rappels
        abonnement.save(update_fields=['rappels_envoyes'])
        return True
    except Exception as exc:
        return False


def _suspend_institut(abonnement):
    """Expire l'abonnement et suspend l'InstitutConfig."""
    from django.utils import timezone

    config = abonnement.config
    admins = _admins_for_config(config)
    nom_institut = config.nom or config.sigle or 'Votre institut'

    # Suspendre l'InstitutConfig
    config.actif = False
    config.date_suspension = timezone.now()
    config.motif_suspension = f"Abonnement expiré le {abonnement.date_fin.strftime('%d/%m/%Y')} — non renouvelé."
    config.save(update_fields=['actif', 'date_suspension', 'motif_suspension'])

    # Marquer l'abonnement comme expiré
    abonnement.statut = abonnement.STATUT_EXPIRE
    abonnement.save(update_fields=['statut'])

    # Notifier les admins
    if admins.exists():
        destinataires = [u.email for u in admins]
        sujet = f"🔴 Accès suspendu — {nom_institut}"
        corps = f"""Bonjour,

L'abonnement de {nom_institut} a expiré le {abonnement.date_fin.strftime('%d/%m/%Y')}.

Comme il n'a pas été renouvelé à temps, l'accès à votre établissement
sur la plateforme a été automatiquement suspendu.

Pour rétablir l'accès, veuillez contacter l'équipe technique afin de
procéder au renouvellement de votre abonnement.

Cordialement,
Le système de gestion académique
"""
        try:
            send_mail(sujet, corps, settings.DEFAULT_FROM_EMAIL, destinataires, fail_silently=True)
        except Exception:
            pass


class Command(BaseCommand):
    help = "Vérifie les abonnements instituts : rappels par mail et suspension automatique."

    def handle(self, *args, **options):
        from academic_core.apps.academic_structure.models import AbonnementInstitut

        today = date.today()
        traites = 0
        suspendus = 0
        rappels_envoyes = 0

        # Abonnements actifs (seuls ceux-ci peuvent expirer ou mériter un rappel)
        abonnements_actifs = AbonnementInstitut.objects.filter(
            statut=AbonnementInstitut.STATUT_ACTIF,
        ).select_related('config')

        for abo in abonnements_actifs:
            jours = (abo.date_fin - today).days
            traites += 1

            if jours < 0:
                # Expiré → suspension immédiate
                self.stdout.write(
                    self.style.ERROR(
                        f"[EXPIRE] {abo.config.nom} — expiré depuis {-jours} jour(s). Suspension..."
                    )
                )
                _suspend_institut(abo)
                suspendus += 1

            else:
                # Vérifier chaque seuil de rappel
                for seuil in SEUILS_RAPPEL:
                    if jours <= seuil and seuil not in (abo.rappels_envoyes or []):
                        ok = _send_rappel(abo, jours)
                        if ok:
                            self.stdout.write(
                                self.style.WARNING(
                                    f"[RAPPEL J-{seuil}] {abo.config.nom} — expire le {abo.date_fin} "
                                    f"(dans {jours}j). Mail envoyé."
                                )
                            )
                            rappels_envoyes += 1
                        else:
                            self.stdout.write(
                                self.style.WARNING(
                                    f"[RAPPEL J-{seuil}] {abo.config.nom} — aucun admin email trouvé ou erreur envoi."
                                )
                            )
                        break  # Un seul rappel par passage (le seuil le plus proche atteint)

        self.stdout.write(self.style.SUCCESS(
            f"Terminé : {traites} abonnement(s) vérifié(s), "
            f"{rappels_envoyes} rappel(s) envoyé(s), "
            f"{suspendus} suspension(s) effectuée(s)."
        ))
