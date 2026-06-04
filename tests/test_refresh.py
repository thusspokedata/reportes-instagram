import logging
from datetime import datetime, timedelta, timezone

import pytest

from app.auth import facebook, refresh
from app.auth.crypto import encrypt_token
from app.db import get_db, upsert_user

NOW = datetime(2026, 6, 3, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def ctx(inited_app):
    c = inited_app.app_context()
    c.push()
    yield inited_app
    c.pop()


def _make_user(expira, actualizado, token="oldtok"):
    """Crea una fila real (para que update_user_token escriba) y devuelve un
    dict de usuaria con los campos controlados que lee refresh_token_if_needed."""
    uid = upsert_user("fb1", "N", encrypt_token(token), None)
    return {
        "id": uid,
        "token_expira_en": expira,
        "actualizado_en": actualizado,
        "access_token_cifrado": encrypt_token(token),
    }


def _no_call(*a, **k):
    raise AssertionError("no debería llamar al refresh")


def test_refreshes_when_near_expiry(ctx, monkeypatch):
    user = _make_user(expira=NOW + timedelta(days=10), actualizado=NOW - timedelta(days=50))
    monkeypatch.setattr(
        facebook, "refresh_long_lived_token", lambda tok: ("newtok-xyz", 5184000)
    )

    result = refresh.refresh_token_if_needed(user, now=NOW)

    assert result["status"] == "refreshed"
    from app.auth.crypto import decrypt_token

    row = get_db().execute(
        "SELECT access_token_cifrado, token_expira_en FROM usuarias WHERE id = ?",
        (user["id"],),
    ).fetchone()
    assert decrypt_token(row["access_token_cifrado"]) == "newtok-xyz"
    # nuevo vencimiento ~ NOW + 60 días (según expires_in devuelto por Meta)
    assert "newtok-xyz" not in row["access_token_cifrado"]


def test_skips_when_margin(ctx, monkeypatch):
    user = _make_user(expira=NOW + timedelta(days=40), actualizado=NOW - timedelta(days=20))
    monkeypatch.setattr(facebook, "refresh_long_lived_token", _no_call)

    result = refresh.refresh_token_if_needed(user, now=NOW)

    assert result["status"] == "skipped"


def test_expired_requires_relogin(ctx, monkeypatch):
    user = _make_user(expira=NOW - timedelta(days=1), actualizado=NOW - timedelta(days=61))
    monkeypatch.setattr(facebook, "refresh_long_lived_token", _no_call)

    result = refresh.refresh_token_if_needed(user, now=NOW)

    assert result["status"] == "expired_relogin"


def test_too_young_not_refreshed(ctx, monkeypatch):
    # Cerca de vencer pero el token se obtuvo hace < 24h.
    user = _make_user(expira=NOW + timedelta(days=10), actualizado=NOW - timedelta(hours=2))
    monkeypatch.setattr(facebook, "refresh_long_lived_token", _no_call)

    result = refresh.refresh_token_if_needed(user, now=NOW)

    assert result["status"] == "too_young"


def test_refresh_error_does_not_break(ctx, monkeypatch):
    user = _make_user(expira=NOW + timedelta(days=5), actualizado=NOW - timedelta(days=55))

    def boom(tok):
        raise facebook.OAuthError("falló el refresh")

    monkeypatch.setattr(facebook, "refresh_long_lived_token", boom)

    result = refresh.refresh_token_if_needed(user, now=NOW)

    assert result["status"] == "error"


def test_unknown_expiry_does_not_refresh(ctx, monkeypatch):
    user = _make_user(expira=None, actualizado=NOW - timedelta(days=50))
    monkeypatch.setattr(facebook, "refresh_long_lived_token", _no_call)

    result = refresh.refresh_token_if_needed(user, now=NOW)

    assert result["status"] == "unknown_expiry"


def test_unknown_age_allows_refresh(ctx, monkeypatch):
    # Sin actualizado_en no se puede medir antigüedad -> se permite intentar el
    # refresh (peor caso: Meta lo rechaza y cae en 'error', manejado).
    user = _make_user(expira=NOW + timedelta(days=10), actualizado=None)
    monkeypatch.setattr(
        facebook, "refresh_long_lived_token", lambda tok: ("newtok", 5184000)
    )

    result = refresh.refresh_token_if_needed(user, now=NOW)

    assert result["status"] == "refreshed"


def test_refresh_tokens_command_runs(ctx, monkeypatch):
    # Usuaria con token sin fecha de expiración -> unknown_expiry; el comando
    # corre, no rompe, y emite el estado por usuaria.
    upsert_user("fbcmd", "N", encrypt_token("tok"), None)
    monkeypatch.setattr(facebook, "refresh_long_lived_token", _no_call)

    result = ctx.test_cli_runner().invoke(args=["refresh-tokens"])

    assert result.exit_code == 0
    assert "unknown_expiry" in result.output


def test_token_never_logged(ctx, monkeypatch, caplog):
    user = _make_user(
        expira=NOW + timedelta(days=5),
        actualizado=NOW - timedelta(days=55),
        token="SUPERSECRETOLD",
    )
    monkeypatch.setattr(
        facebook, "refresh_long_lived_token", lambda tok: ("SUPERSECRETNEW", 5184000)
    )

    with caplog.at_level(logging.DEBUG):
        refresh.refresh_token_if_needed(user, now=NOW)

    assert "SUPERSECRETOLD" not in caplog.text
    assert "SUPERSECRETNEW" not in caplog.text
