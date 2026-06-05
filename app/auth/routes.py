"""Auth blueprint: Facebook Login OAuth flow.

Routes: ``/auth/login``, ``/auth/callback``, ``/auth/logout``.

Security notes:
- ``state`` is a CSRF token: generated on login, stored in the session, and
  verified (constant-time) on callback.
- The authorization ``code``, the ``state``, and any token are NEVER logged.
- Tokens are encrypted before being stored (see ``crypto`` / ``db.upsert_user``).
"""

import secrets
from datetime import datetime, timedelta, timezone

from flask import (
    Blueprint,
    abort,
    current_app,
    redirect,
    request,
    session,
    url_for,
)

from . import facebook
from .crypto import encrypt_token
from ..db import upsert_user

bp = Blueprint("auth", __name__, url_prefix="/auth")


@bp.route("/login")
def login():
    """Start the OAuth flow: store a fresh state and redirect to Meta."""
    # Drop any prior session content (stale state, fixated session) before
    # issuing a fresh CSRF state.
    session.clear()
    state = secrets.token_urlsafe(32)
    session["oauth_state"] = state
    return redirect(facebook.build_login_url(state))


@bp.route("/callback")
def callback():
    """Handle Meta's redirect back to the app."""
    # Consume the issued state first, so it is single-use on every path
    # (including the error path below), preventing replay.
    expected_state = session.pop("oauth_state", None)

    # The user cancelled or Meta returned an error. Don't leak details.
    if request.args.get("error"):
        return (
            "No se pudo completar el inicio de sesión con Facebook. "
            "Probá de nuevo.",
            400,
        )

    # Anti-CSRF: state must be present and match the one we issued.
    received_state = request.args.get("state")
    if (
        not expected_state
        or not received_state
        or not secrets.compare_digest(expected_state, received_state)
    ):
        current_app.logger.warning("OAuth callback con state inválido o ausente.")
        abort(400)

    code = request.args.get("code")
    if not code:
        abort(400)

    try:
        short_token = facebook.exchange_code_for_token(code)
        long_token, expires_in = facebook.exchange_for_long_lived_token(short_token)
        profile = facebook.get_user_profile(long_token)
    except facebook.OAuthError:
        # Mensaje fijo al usuario: no devolvemos el objeto/str de la excepción
        # (evita exponer trazas; CodeQL py/stack-trace-exposure).
        current_app.logger.warning("Fallo el intercambio OAuth con Meta.")
        return (
            "No se pudo completar el inicio de sesión con Facebook. Probá de nuevo.",
            400,
        )

    expira_en = None
    try:
        # `is not None`: un expires_in de 0 es válido (distinto de ausente).
        if expires_in is not None:
            # Naive UTC: el converter TIMESTAMP de sqlite no parsea el offset de
            # un datetime aware (rompería lecturas posteriores en Python 3.12).
            expira_en = (
                datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
            ).replace(tzinfo=None)
    except (TypeError, ValueError):
        # Meta returned an unexpected expires_in; store with no expiry rather
        # than crashing the login.
        expira_en = None

    user_id = upsert_user(
        fb_user_id=profile["id"],
        nombre=profile.get("name"),
        access_token_cifrado=encrypt_token(long_token),
        token_expira_en=expira_en,
    )

    session.clear()
    session["user_id"] = user_id
    session["logged_in"] = True

    return redirect(url_for("dashboard.dashboard"))


@bp.route("/logout")
def logout():
    """Clear the session."""
    session.clear()
    return redirect(url_for("main.health"))
