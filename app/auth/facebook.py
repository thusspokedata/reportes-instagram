"""Facebook Login / Instagram Graph API OAuth client.

Builds authorization URLs and exchanges authorization codes for tokens. All
URLs are built from ``GRAPH_API_VERSION`` in the environment — the API version
is never hardcoded.

Error handling is defensive: on any Meta-side failure we raise
:class:`OAuthError` with a user-safe message and NEVER include the ``code`` or
any token in the message, logs, or exceptions.
"""

from urllib.parse import urlencode

import requests
from flask import current_app

# Permissions approved for this app in Meta (Instagram Graph API via Facebook
# Login for Business). Request EXACTLY these — no messaging/publishing/ads.
SCOPES = [
    "instagram_basic",
    "instagram_manage_insights",
    "pages_show_list",
    "pages_read_engagement",
    "business_management",
]

# Network timeout (seconds) for calls to Meta.
_TIMEOUT = 15


class OAuthError(Exception):
    """Raised when the OAuth exchange with Meta fails.

    The message is safe to surface to the user; it never contains the
    authorization code or any token.
    """


def _version() -> str:
    return current_app.config["GRAPH_API_VERSION"]


def _graph_base() -> str:
    return f"{current_app.config['GRAPH_API_BASE']}/{_version()}"


def build_login_url(state: str) -> str:
    """Build the Facebook authorization dialog URL."""
    params = {
        "client_id": current_app.config["FACEBOOK_APP_ID"],
        "redirect_uri": current_app.config["REDIRECT_URI"],
        "state": state,
        "scope": ",".join(SCOPES),
        "response_type": "code",
    }
    dialog_base = current_app.config["FACEBOOK_OAUTH_DIALOG_BASE"]
    return f"{dialog_base}/{_version()}/dialog/oauth?{urlencode(params)}"


def _get_json(url: str, params: dict) -> dict:
    """GET a Graph endpoint and return parsed JSON, raising OAuthError safely."""
    try:
        resp = requests.get(url, params=params, timeout=_TIMEOUT)
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        # Do NOT include params (they carry code/secret) in the message.
        raise OAuthError("No se pudo contactar a Meta. Probá de nuevo.") from exc

    if not resp.ok or "error" in data:
        # Meta's error body may echo back sensitive context; never surface it.
        raise OAuthError("Meta rechazó la solicitud de autenticación.")

    return data


def exchange_code_for_token(code: str) -> str:
    """Exchange an authorization code for a short-lived access token (~1h)."""
    data = _get_json(
        f"{_graph_base()}/oauth/access_token",
        {
            "client_id": current_app.config["FACEBOOK_APP_ID"],
            "client_secret": current_app.config["FACEBOOK_APP_SECRET"],
            "redirect_uri": current_app.config["REDIRECT_URI"],
            "code": code,
        },
    )
    token = data.get("access_token")
    if not token:
        raise OAuthError("Meta no devolvió un token de acceso.")
    return token


def exchange_for_long_lived_token(short_token: str):
    """Exchange a short-lived token for a long-lived one (~60 days).

    Returns ``(access_token, expires_in)`` where ``expires_in`` is the token
    lifetime in seconds as reported by Meta.
    """
    data = _get_json(
        f"{_graph_base()}/oauth/access_token",
        {
            "grant_type": "fb_exchange_token",
            "client_id": current_app.config["FACEBOOK_APP_ID"],
            "client_secret": current_app.config["FACEBOOK_APP_SECRET"],
            "fb_exchange_token": short_token,
        },
    )
    token = data.get("access_token")
    if not token:
        raise OAuthError("Meta no devolvió un token de larga duración.")
    return token, data.get("expires_in")


def refresh_long_lived_token(long_token: str):
    """Renueva un token largo de **Facebook Login** re-intercambiándolo.

    Mecanismo: el MISMO endpoint del intercambio inicial,
    ``graph.facebook.com/{version}/oauth/access_token`` con
    ``grant_type=fb_exchange_token``, pasando el token largo actual como
    ``fb_exchange_token``. Es el camino de Facebook Login — NO
    ``graph.instagram.com/refresh_access_token``, que es de Instagram Login.

    Devuelve ``(token_nuevo, expires_in)``; el caller fija el nuevo vencimiento
    con el ``expires_in`` que devuelve Meta.

    NOTA (sin verificar contra la doc vigente — entorno sin acceso a red): no se
    pudo confirmar si este re-intercambio EXTIENDE ~60 días o conserva el
    vencimiento original. Por eso el caller usa el ``expires_in`` real devuelto
    y el manejo de "token expirado -> requiere re-login" cubre el peor caso.
    Confirmar empíricamente en el primer refresh real.
    """
    return exchange_for_long_lived_token(long_token)


def get_user_profile(access_token: str) -> dict:
    """Fetch the authenticated user's basic profile (id, name)."""
    data = _get_json(
        f"{_graph_base()}/me",
        {"fields": "id,name", "access_token": access_token},
    )
    if not data.get("id"):
        raise OAuthError("Meta no devolvió el perfil de la usuaria.")
    return {"id": data["id"], "name": data.get("name")}
