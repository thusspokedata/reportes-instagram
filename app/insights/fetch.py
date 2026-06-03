"""Cliente de bajada de insights desde la Instagram Graph API.

Diseño DEFENSIVO: las métricas de Meta cambian sin aviso, así que cada métrica
se pide por separado y, si Meta la rechaza o no está disponible, se saltea
(quedando en ``None``) sin tirar abajo toda la bajada. El error de rate limit
sí se propaga (no se reintenta agresivamente).

El token de la usuaria se descifra sólo en memoria para la llamada y NUNCA se
loguea ni se incluye en mensajes de error.
"""

import logging

import requests
from flask import current_app

from ..auth.crypto import decrypt_token

logger = logging.getLogger(__name__)

_TIMEOUT = 15
# Códigos de error de Meta asociados a límite de solicitudes.
_RATE_LIMIT_CODES = {4, 17, 32, 613}

# Subconjunto de métricas de CUENTA de esta spec (nombres/period vigentes v23.0).
# Sumar el resto después repitiendo el patrón.
ACCOUNT_METRICS = (
    ("reach", {"period": "day", "metric_type": "total_value"}),
    ("follower_count", {"period": "day"}),
)
# Métricas de POST que se piden como insights. likes/comments NO van acá:
# se leen como fields del media object (like_count, comments_count).
MEDIA_INSIGHT_METRICS = ("reach",)
MEDIA_FIELDS = "id,media_type,permalink,caption,timestamp,like_count,comments_count"


class InsightsError(Exception):
    """Fallo recuperable al pedir insights. Mensaje user-safe, sin secretos."""


class RateLimitError(InsightsError):
    """Meta devolvió un error de límite de solicitudes."""


def _graph_base() -> str:
    return f"{current_app.config['GRAPH_API_BASE']}/{current_app.config['GRAPH_API_VERSION']}"


def _graph_get(path: str, params: dict, token: str) -> dict:
    """GET a un endpoint de la Graph API. Errores se traducen a InsightsError
    sin filtrar el token ni los params (que llevan el access_token)."""
    url = f"{_graph_base()}/{path.lstrip('/')}"
    query = dict(params)
    query["access_token"] = token
    try:
        resp = requests.get(url, params=query, timeout=_TIMEOUT)
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise InsightsError("No se pudo contactar a Meta.") from exc

    if not resp.ok or (isinstance(data, dict) and "error" in data):
        err = data.get("error", {}) if isinstance(data, dict) else {}
        if err.get("code") in _RATE_LIMIT_CODES:
            raise RateLimitError(
                "Límite de solicitudes de Meta alcanzado. Probá más tarde."
            )
        raise InsightsError("Meta rechazó la solicitud de insights.")

    return data


def _resolve_ig_user_id(token: str) -> str:
    """Resuelve el id de la cuenta de Instagram Business desde el token."""
    data = _graph_get("me/accounts", {"fields": "instagram_business_account"}, token)
    for page in data.get("data", []):
        iga = page.get("instagram_business_account") or {}
        if iga.get("id"):
            return iga["id"]
    raise InsightsError("No se encontró una cuenta de Instagram Business vinculada.")


def _extract_metric_value(data: dict):
    """Extrae el valor de una respuesta de insights. Ausencia de dato -> None."""
    items = data.get("data") or []
    if not items:
        return None
    item = items[0]
    if "total_value" in item:
        return (item["total_value"] or {}).get("value")
    values = item.get("values") or []
    if values:
        return values[-1].get("value")
    return None


def fetch_account_insights(user) -> dict:
    """Baja, de forma defensiva, las métricas de cuenta de esta spec."""
    token = decrypt_token(user["access_token_cifrado"])
    ig_id = _resolve_ig_user_id(token)
    result = {}
    for name, params in ACCOUNT_METRICS:
        try:
            data = _graph_get(f"{ig_id}/insights", {"metric": name, **params}, token)
            result[name] = _extract_metric_value(data)
        except RateLimitError:
            raise  # no seguir golpeando el endpoint
        except InsightsError:
            logger.warning("Métrica de cuenta '%s' no disponible; se saltea.", name)
            result[name] = None
    return result


def fetch_media_list(user) -> list:
    """Trae la lista de media de la usuaria (con like_count/comments_count)."""
    token = decrypt_token(user["access_token_cifrado"])
    ig_id = _resolve_ig_user_id(token)
    data = _graph_get(f"{ig_id}/media", {"fields": MEDIA_FIELDS}, token)
    return data.get("data", [])


def fetch_media_insights(user, media_id, media_type=None) -> dict:
    """Baja, de forma defensiva, las métricas de insights de un post."""
    token = decrypt_token(user["access_token_cifrado"])
    result = {}
    for name in MEDIA_INSIGHT_METRICS:
        try:
            data = _graph_get(
                f"{media_id}/insights", {"metric": name, "period": "day"}, token
            )
            result[name] = _extract_metric_value(data)
        except RateLimitError:
            raise
        except InsightsError:
            logger.warning(
                "Métrica de media '%s' no disponible (media %s); se saltea.",
                name,
                media_id,
            )
            result[name] = None
    return result


def normalize_post(media: dict, insights: dict = None) -> dict:
    """Combina un media object + sus insights en un dict listo para persistir."""
    insights = insights or {}
    return {
        "media_id": media.get("id"),
        "media_type": media.get("media_type"),
        "permalink": media.get("permalink"),
        "caption": media.get("caption"),
        "timestamp": media.get("timestamp"),
        "likes": media.get("like_count"),
        "comments": media.get("comments_count"),
        "reach": insights.get("reach"),
        "views": insights.get("views"),
        "saved": insights.get("saved"),
        "shares": insights.get("shares"),
        "total_interactions": insights.get("total_interactions"),
    }
