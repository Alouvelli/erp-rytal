"""
Intégration paiement en ligne du portail public d'admission — Wave et Orange
Money, appelés directement (chacun avec ses propres identifiants marchand,
voir academic_structure.InstitutPaymentConfig pour la configuration par
institut, et admissions/views.py pour le flux candidat + les webhooks de
confirmation).

⚠️ Implémentations basées sur la documentation publique de chaque API (Wave
Checkout Sessions : https://docs.wave.com/business/api ; Orange Money Web
Payment : https://developer.orange.com/apis/om-webpay). Elles n'ont pas pu
être testées de bout en bout faute d'identifiants marchand réels au moment
de l'écriture — à valider avec de vrais comptes de test avant toute mise en
production. La réponse brute de chaque confirmation est conservée
(OnlinePaymentTransaction.raw_response) pour faciliter le diagnostic si un
champ de l'une ou l'autre API a changé de forme.
"""
import base64

import requests

REQUEST_TIMEOUT = 15


class PaymentGatewayError(Exception):
    """Levée pour toute erreur de communication ou de réponse du fournisseur."""


# ── Wave ─────────────────────────────────────────────────────────────────────
WAVE_BASE_URL = "https://api.wave.com/v1"


def _wave_headers(config):
    return {
        'Authorization': f'Bearer {config.wave_api_key}',
        'Content-Type': 'application/json',
    }


def create_wave_checkout(config, *, amount, success_url, error_url, client_reference):
    """
    Crée une session de paiement Wave et retourne (session_id, wave_launch_url) —
    le candidat est redirigé vers wave_launch_url pour finaliser le paiement.
    Lève PaymentGatewayError si la création échoue.
    """
    payload = {
        "amount": str(int(amount)),
        "currency": "XOF",
        "client_reference": client_reference,
        "success_url": success_url,
        "error_url": error_url,
    }
    try:
        resp = requests.post(
            f"{WAVE_BASE_URL}/checkout/sessions",
            json=payload, headers=_wave_headers(config), timeout=REQUEST_TIMEOUT,
        )
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise PaymentGatewayError(f"Erreur de connexion à Wave : {exc}") from exc

    if resp.status_code >= 400 or not data.get('id'):
        raise PaymentGatewayError(
            data.get('message') or "Échec de création de la session de paiement Wave."
        )

    return data['id'], data.get('wave_launch_url')


def confirm_wave_checkout(config, session_id):
    """
    Interroge Wave pour l'état réel d'une session de paiement (source de
    vérité — ne jamais faire confiance au seul contenu du webhook/de l'URL de
    retour). Retourne le dict de réponse brut ; lève PaymentGatewayError en
    cas d'échec de communication. `payment_status` vaut 'succeeded' une fois
    le paiement effectivement confirmé.
    """
    try:
        resp = requests.get(
            f"{WAVE_BASE_URL}/checkout/sessions/{session_id}",
            headers=_wave_headers(config), timeout=REQUEST_TIMEOUT,
        )
        return resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise PaymentGatewayError(f"Erreur de connexion à Wave : {exc}") from exc


# ── Orange Money ─────────────────────────────────────────────────────────────
OM_TOKEN_URL = "https://api.orange.com/oauth/v3/token"
OM_BASE_URL = "https://api.orange.com/orange-money-webpay"


def _om_get_access_token(config):
    """Jeton OAuth2 client_credentials — un jeton par appel, jamais réutilisé
    d'une requête à l'autre (durée de vie courte côté Orange)."""
    creds = base64.b64encode(
        f"{config.om_client_id}:{config.om_client_secret}".encode()
    ).decode()
    try:
        resp = requests.post(
            OM_TOKEN_URL,
            data={'grant_type': 'client_credentials'},
            headers={'Authorization': f'Basic {creds}'},
            timeout=REQUEST_TIMEOUT,
        )
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise PaymentGatewayError(f"Erreur d'authentification Orange Money : {exc}") from exc

    if not data.get('access_token'):
        raise PaymentGatewayError("Échec d'authentification Orange Money.")
    return data['access_token']


def create_orange_money_payment(config, *, amount, order_id, return_url,
                                 cancel_url, notif_url, reference):
    """
    Crée un paiement Orange Money Web Payment et retourne (pay_token,
    payment_url) — le candidat est redirigé vers payment_url pour finaliser
    le paiement. Lève PaymentGatewayError si la création échoue.
    """
    token = _om_get_access_token(config)
    payload = {
        "merchant_key": config.om_merchant_key,
        "currency": "XOF",
        "order_id": order_id,
        "amount": int(amount),
        "return_url": return_url,
        "cancel_url": cancel_url,
        "notif_url": notif_url,
        "lang": "fr",
        "reference": reference,
    }
    try:
        resp = requests.post(
            f"{OM_BASE_URL}/{config.om_region}/v1/webpayment",
            json=payload,
            headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
            timeout=REQUEST_TIMEOUT,
        )
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise PaymentGatewayError(f"Erreur de connexion à Orange Money : {exc}") from exc

    if not data.get('payment_url'):
        raise PaymentGatewayError(
            data.get('message') or "Échec de création du paiement Orange Money."
        )

    return data['pay_token'], data['payment_url']


def confirm_orange_money_payment(config, *, pay_token, order_id, amount):
    """
    Interroge Orange Money pour l'état réel d'une transaction (source de
    vérité — ne jamais faire confiance au seul contenu du webhook/de l'URL de
    retour). Retourne le dict de réponse brut ; lève PaymentGatewayError en
    cas d'échec de communication.
    """
    token = _om_get_access_token(config)
    try:
        resp = requests.get(
            f"{OM_BASE_URL}/{config.om_region}/v1/transactionstatus",
            params={'order_id': order_id, 'amount': int(amount), 'pay_token': pay_token},
            headers={'Authorization': f'Bearer {token}'}, timeout=REQUEST_TIMEOUT,
        )
        return resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise PaymentGatewayError(f"Erreur de connexion à Orange Money : {exc}") from exc
