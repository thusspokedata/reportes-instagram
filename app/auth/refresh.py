"""Renovación del token largo de Facebook Login.

Refresca el token de cada usuaria SOLO si está cerca de vencer (margen
configurable) y tiene ≥24h de antigüedad (restricción de Meta). Guarda el token
nuevo cifrado con su nuevo vencimiento. El token se descifra sólo en memoria
para la llamada y NUNCA se loguea.

Pensado para correr a diario por cron: como el refresh es condicional, correrlo
todos los días es seguro e idempotente.
"""

import logging
from datetime import datetime, timedelta, timezone

import click
from flask.cli import with_appcontext

from . import facebook
from .crypto import decrypt_token, encrypt_token
from ..db import get_db, update_user_token

logger = logging.getLogger(__name__)

# Margen: refrescar cuando falten <= estos días para vencer. Meta recomienda
# cada 30-45 días; con 15 de margen el cron diario refresca bien antes del día 59.
REFRESH_MARGIN_DAYS = 15
# Meta no permite refrescar un token con menos de 24h de antigüedad.
MIN_TOKEN_AGE = timedelta(hours=24)


def _as_aware_utc(value):
    """Normaliza el token_expira_en (datetime naive/aware o str ISO) a UTC aware."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return None


def refresh_token_if_needed(user, now=None):
    """Refresca el token de ``user`` si corresponde. Devuelve un dict de estado.

    Estados: ``refreshed``, ``skipped`` (con margen), ``too_young`` (<24h),
    ``expired_relogin`` (ya venció, no se puede refrescar), ``unknown_expiry``,
    ``error`` (falló el refresh). Nunca incluye el token en el resultado/logs.
    """
    now = now or datetime.now(timezone.utc)
    expira = _as_aware_utc(user["token_expira_en"])
    user_id = user["id"]

    if expira is None:
        logger.warning("Usuaria %s sin fecha de expiración de token.", user_id)
        return {"status": "unknown_expiry", "user_id": user_id}

    if now >= expira:
        logger.warning("Token de la usuaria %s expirado; requiere re-login.", user_id)
        return {"status": "expired_relogin", "user_id": user_id}

    days_left = (expira - now).total_seconds() / 86400
    if days_left > REFRESH_MARGIN_DAYS:
        return {"status": "skipped", "user_id": user_id, "days_left": round(days_left, 1)}

    # Meta rechaza refrescar un token con <24h de antigüedad. Usamos
    # `actualizado_en` (cuándo se obtuvo/refrescó por última vez) como emisión.
    issued = _as_aware_utc(user["actualizado_en"]) if "actualizado_en" in user.keys() else None
    if issued is not None and (now - issued) < MIN_TOKEN_AGE:
        return {"status": "too_young", "user_id": user_id}

    token = decrypt_token(user["access_token_cifrado"])
    try:
        new_token, expires_in = facebook.refresh_long_lived_token(token)
    except facebook.OAuthError:
        # OAuthError cubre cualquier fallo de Meta (incl. rate limit, token
        # revocado): se registra sin token y se sigue con las demás usuarias.
        logger.warning("Falló el refresh del token de la usuaria %s.", user_id)
        return {"status": "error", "user_id": user_id}

    new_expira = None
    try:
        if expires_in:
            # Naive UTC: el converter de sqlite no maneja el offset de un aware.
            new_expira = (now + timedelta(seconds=int(expires_in))).replace(tzinfo=None)
    except (TypeError, ValueError):
        new_expira = None

    update_user_token(user_id, encrypt_token(new_token), new_expira)
    logger.info("Token de la usuaria %s refrescado.", user_id)
    return {"status": "refreshed", "user_id": user_id, "token_expira_en": new_expira}


@click.command("refresh-tokens")
@with_appcontext
def refresh_tokens_command():
    """Refresca los tokens próximos a vencer de todas las usuarias."""
    users = get_db().execute("SELECT * FROM usuarias").fetchall()
    if not users:
        click.echo("No hay usuarias en la base.")
        return

    for user in users:
        # refresh_token_if_needed es defensivo: captura los errores de Meta y
        # devuelve un estado; no rompe el loop de las demás usuarias.
        result = refresh_token_if_needed(user)
        click.echo(f"usuaria {result['user_id']}: {result['status']}")


def init_app(app):
    app.cli.add_command(refresh_tokens_command)
