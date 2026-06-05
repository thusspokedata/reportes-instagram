import sqlite3
from urllib.parse import urlparse

import pytest

from app import create_app
from app.auth import facebook
from app.auth.crypto import decrypt_token


@pytest.fixture
def app(env):
    app = create_app()
    with app.app_context():
        from app.db import init_db

        init_db()
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def _mock_meta(monkeypatch):
    """Patch the Meta client so no real network calls happen."""
    monkeypatch.setattr(facebook, "exchange_code_for_token", lambda code: "short-token-abc")
    monkeypatch.setattr(
        facebook,
        "exchange_for_long_lived_token",
        lambda short: ("long-token-xyz", 5184000),
    )
    monkeypatch.setattr(
        facebook,
        "get_user_profile",
        lambda token: {"id": "fbuser123", "name": "Test User"},
    )


# --- /auth/login ---------------------------------------------------------

def test_login_redirects_to_meta_with_state(client, app):
    response = client.get("/auth/login")

    assert response.status_code == 302
    location = response.headers["Location"]
    # Host exacto (no substring): el redirect debe ir a www.facebook.com.
    assert urlparse(location).netloc == "www.facebook.com"
    assert "state=" in location
    # Version must come from GRAPH_API_VERSION, not be hardcoded.
    assert app.config["GRAPH_API_VERSION"] in location

    with client.session_transaction() as sess:
        assert sess.get("oauth_state")
        assert sess["oauth_state"] in location


def test_login_clears_existing_session(client):
    with client.session_transaction() as sess:
        sess["stale"] = "value"
        sess["logged_in"] = True

    client.get("/auth/login")

    with client.session_transaction() as sess:
        # Stale session data is dropped; only a fresh state remains.
        assert not sess.get("stale")
        assert not sess.get("logged_in")
        assert sess.get("oauth_state")


# --- /auth/callback: state anti-CSRF ------------------------------------

def test_callback_rejects_missing_state(client):
    with client.session_transaction() as sess:
        sess["oauth_state"] = "expected-state"

    response = client.get("/auth/callback?code=somecode")

    assert response.status_code == 400


def test_callback_rejects_mismatched_state(client):
    with client.session_transaction() as sess:
        sess["oauth_state"] = "expected-state"

    response = client.get("/auth/callback?code=somecode&state=attacker-state")

    assert response.status_code == 400


# --- /auth/callback: success --------------------------------------------

def test_callback_success_logs_in_and_redirects(client, monkeypatch):
    _mock_meta(monkeypatch)
    with client.session_transaction() as sess:
        sess["oauth_state"] = "good-state"

    response = client.get("/auth/callback?code=the-code&state=good-state")

    assert response.status_code == 302
    with client.session_transaction() as sess:
        assert sess.get("logged_in") is True
        # The one-time CSRF state must be consumed on success too.
        assert not sess.get("oauth_state")


def test_callback_stores_token_encrypted(client, app, monkeypatch):
    _mock_meta(monkeypatch)
    with client.session_transaction() as sess:
        sess["oauth_state"] = "good-state"

    client.get("/auth/callback?code=the-code&state=good-state")

    with app.app_context():
        from app.db import get_db

        row = get_db().execute(
            "SELECT fb_user_id, nombre, access_token_cifrado FROM usuarias"
            " WHERE fb_user_id = ?",
            ("fbuser123",),
        ).fetchone()

    assert row is not None
    assert row["nombre"] == "Test User"
    # The plaintext token must NOT be stored.
    assert "long-token-xyz" not in row["access_token_cifrado"]
    # And it must decrypt back correctly.
    with app.app_context():
        assert decrypt_token(row["access_token_cifrado"]) == "long-token-xyz"


def test_callback_does_not_leak_secrets_in_logs(client, monkeypatch, caplog):
    _mock_meta(monkeypatch)
    with client.session_transaction() as sess:
        sess["oauth_state"] = "good-state"

    with caplog.at_level("DEBUG"):
        client.get("/auth/callback?code=the-code&state=good-state")

    log_text = caplog.text
    assert "the-code" not in log_text
    assert "good-state" not in log_text
    assert "long-token-xyz" not in log_text
    assert "short-token-abc" not in log_text


# --- /auth/callback: Meta error -----------------------------------------

def test_callback_handles_meta_error_param(client):
    # User cancelled the dialog: Meta redirects with ?error=access_denied
    with client.session_transaction() as sess:
        sess["oauth_state"] = "good-state"

    response = client.get(
        "/auth/callback?error=access_denied&error_reason=user_denied&state=good-state"
    )

    # Should not crash; should not be a successful login.
    assert response.status_code == 400
    with client.session_transaction() as sess:
        assert not sess.get("logged_in")
        # state must be consumed even on the error path (single-use).
        assert not sess.get("oauth_state")


# --- /auth/logout --------------------------------------------------------

def test_logout_clears_session(client):
    with client.session_transaction() as sess:
        sess["logged_in"] = True
        sess["user_id"] = 1

    response = client.get("/auth/logout")

    assert response.status_code == 302
    with client.session_transaction() as sess:
        assert not sess.get("logged_in")
        assert not sess.get("user_id")


def test_callback_tolerates_non_numeric_expires_in(client, app, monkeypatch):
    monkeypatch.setattr(facebook, "exchange_code_for_token", lambda code: "short")
    monkeypatch.setattr(
        facebook,
        "exchange_for_long_lived_token",
        lambda short: ("long-token-xyz", "not-a-number"),
    )
    monkeypatch.setattr(
        facebook, "get_user_profile", lambda token: {"id": "u1", "name": "N"}
    )
    with client.session_transaction() as sess:
        sess["oauth_state"] = "good-state"

    response = client.get("/auth/callback?code=c&state=good-state")

    # Must not 500; the token is stored with no expiry rather than crashing.
    assert response.status_code == 302
    with app.app_context():
        from app.db import get_db

        row = get_db().execute(
            "SELECT token_expira_en FROM usuarias WHERE fb_user_id = 'u1'"
        ).fetchone()
    assert row["token_expira_en"] is None
