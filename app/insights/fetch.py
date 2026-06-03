"""Cliente de bajada de insights desde la Instagram Graph API.

Diseño DEFENSIVO: las métricas de Meta cambian sin aviso, así que cada métrica
se pide por separado y, si Meta la rechaza o no está disponible, se saltea
(quedando en ``None``) sin tirar abajo toda la bajada. El error de rate limit
sí se propaga (no se reintenta agresivamente).

El token de la usuaria se descifra sólo en memoria para la llamada y NUNCA se
loguea ni se incluye en mensajes de error.
"""

import logging
from typing import Optional
from urllib.parse import parse_qs, urlparse

import requests
from flask import current_app

from ..auth.crypto import decrypt_token

logger = logging.getLogger(__name__)

_TIMEOUT = 15
# Códigos de error de Meta asociados a límite de solicitudes.
_RATE_LIMIT_CODES = {4, 17, 32, 613}

# Métricas de CUENTA de insights (endpoint /insights). NOTA: follower_count NO
# va acá. La métrica de insights `follower_count` (sin "s") es la serie temporal
# de NUEVOS seguidores por period y devuelve vacío (no 0) si no hay datos; no es
# el total. El conteo actual de seguidores se lee del FIELD del perfil
# `followers_count` (con "s") en fetch_profile().
ACCOUNT_METRICS = (
    ("reach", {"period": "day", "metric_type": "total_value"}),
)
# Fields del perfil del IG user (conteos actuales, en tiempo real).
PROFILE_FIELDS = "followers_count,media_count,username"
# Métricas de POST que se piden como insights. likes/comments NO van acá:
# se leen como fields del media object (like_count, comments_count).
MEDIA_INSIGHT_METRICS = ("reach",)
MEDIA_FIELDS = "id,media_type,permalink,caption,timestamp,like_count,comments_count"
# Tope de seguridad de páginas al paginar media (rate limit ~200/h).
_MAX_MEDIA_PAGES = 25


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
    pages = data.get("data") if isinstance(data, dict) else None
    for page in pages or []:
        iga = page.get("instagram_business_account") if isinstance(page, dict) else None
        if isinstance(iga, dict) and iga.get("id"):
            return iga["id"]
    raise InsightsError("No se encontró una cuenta de Instagram Business vinculada.")


def resolve_ig_account(user) -> str:
    """Resuelve el id de la cuenta IG Business de una usuaria (una llamada).

    Pensado para resolverlo UNA vez por corrida y pasarlo a las funciones de
    fetch, conservando el presupuesto de rate limit.
    """
    return _resolve_ig_user_id(decrypt_token(user["access_token_cifrado"]))


def _extract_metric_value(data):
    """Extrae el valor de una respuesta de insights. Ausencia de dato o forma
    inesperada -> None (defensivo: Meta puede devolver estructuras raras)."""
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        return None
    item = items[0]
    if not isinstance(item, dict):
        return None
    total_value = item.get("total_value")
    if isinstance(total_value, dict):
        return total_value.get("value")
    values = item.get("values")
    if isinstance(values, list) and values and isinstance(values[-1], dict):
        return values[-1].get("value")
    return None


def fetch_profile(user, ig_id=None) -> dict:
    """Lee los conteos actuales del perfil del IG user (en tiempo real).

    Devuelve ``{followers_count, media_count, username}``. Defensivo: si la
    llamada falla (salvo rate limit), devuelve ``{}`` -> los conteos quedan
    ``None`` (NUNCA 0). El conteo de seguidores del snapshot sale de acá, no de
    la métrica de insights.
    """
    token = decrypt_token(user["access_token_cifrado"])
    if ig_id is None:
        ig_id = _resolve_ig_user_id(token)
    try:
        data = _graph_get(ig_id, {"fields": PROFILE_FIELDS}, token)
    except RateLimitError:
        raise
    except (InsightsError, TypeError, AttributeError, KeyError):
        logger.warning("No se pudo leer el perfil de la cuenta; se saltea.")
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        "followers_count": data.get("followers_count"),
        "media_count": data.get("media_count"),
        "username": data.get("username"),
    }


def fetch_account_insights(user, ig_id=None) -> dict:
    """Baja, de forma defensiva, las métricas de cuenta (insights) de esta spec.

    Devuelve sólo métricas de insights (ej. reach). El conteo de seguidores NO
    sale de acá: ver ``fetch_profile``. Si se pasa ``ig_id`` (ya resuelto), evita
    la llamada extra a ``me/accounts``.
    """
    token = decrypt_token(user["access_token_cifrado"])
    if ig_id is None:
        ig_id = _resolve_ig_user_id(token)
    result = {}
    for name, params in ACCOUNT_METRICS:
        try:
            data = _graph_get(f"{ig_id}/insights", {"metric": name, **params}, token)
            result[name] = _extract_metric_value(data)
        except RateLimitError:
            raise  # no seguir golpeando el endpoint
        except (InsightsError, TypeError, AttributeError, KeyError):
            logger.warning("Métrica de cuenta '%s' no disponible; se saltea.", name)
            result[name] = None
    return result


def _after_from_url(url) -> Optional[str]:
    """Extrae el cursor `after` de una URL de paginación de Meta."""
    if not isinstance(url, str):
        return None
    return parse_qs(urlparse(url).query).get("after", [None])[0]


def fetch_media_list(user, ig_id=None) -> list:
    """Trae la lista de media de la usuaria (con like_count/comments_count).

    Si se pasa ``ig_id`` (ya resuelto), evita la llamada extra a ``me/accounts``.
    """
    token = decrypt_token(user["access_token_cifrado"])
    if ig_id is None:
        ig_id = _resolve_ig_user_id(token)

    all_media = []
    params = {"fields": MEDIA_FIELDS, "limit": 100}
    pages = 0
    while pages < _MAX_MEDIA_PAGES:
        data = _graph_get(f"{ig_id}/media", params, token)
        page = data.get("data") if isinstance(data, dict) else None
        all_media.extend(m for m in (page or []) if isinstance(m, dict))
        pages += 1

        # Seguir el cursor `after` mientras Meta indique que hay más páginas.
        paging = data.get("paging") if isinstance(data, dict) else None
        cursor = None
        if isinstance(paging, dict) and paging.get("next"):
            cursor = (paging.get("cursors") or {}).get("after")
            # Fallback: si vino `next` (URL) pero no expuso el cursor, sacarlo
            # de la query de la URL `next`.
            if not cursor:
                cursor = _after_from_url(paging["next"])
        if not cursor:
            break
        params = {"fields": MEDIA_FIELDS, "limit": 100, "after": cursor}

    if pages >= _MAX_MEDIA_PAGES:
        logger.warning(
            "Paginación de media alcanzó el tope de %d páginas; puede faltar media.",
            _MAX_MEDIA_PAGES,
        )
    return all_media


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
        except (InsightsError, TypeError, AttributeError, KeyError):
            logger.warning(
                "Métrica de media '%s' no disponible (media %s); se saltea.",
                name,
                media_id,
            )
            result[name] = None
    return result


def normalize_post(media, insights: Optional[dict] = None) -> dict:
    """Combina un media object + sus insights en un dict listo para persistir.

    Tolera entradas no-dict (Meta puede devolver estructuras raras)."""
    media = media if isinstance(media, dict) else {}
    insights = insights if isinstance(insights, dict) else {}
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
