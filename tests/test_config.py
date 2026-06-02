import os

import pytest
from cryptography.fernet import Fernet

from app import create_app

VALID_KEY = Fernet.generate_key().decode()


def test_app_starts_with_valid_config(env):
    app = create_app()

    assert app.config["SECRET_KEY"] == "test-secret"
    assert app.config["GRAPH_API_VERSION"] == "v23.0"
    assert app.config["REDIRECT_URI"] == "http://localhost:5000/auth/callback"


def test_missing_secret_key_fails_loudly(env, monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)

    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app()


def test_missing_token_encryption_key_fails_loudly(env, monkeypatch):
    monkeypatch.delenv("TOKEN_ENCRYPTION_KEY", raising=False)

    with pytest.raises(RuntimeError, match="TOKEN_ENCRYPTION_KEY"):
        create_app()


def test_malformed_token_encryption_key_fails_at_boot(env, monkeypatch):
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "not-a-valid-fernet-key")

    with pytest.raises(RuntimeError, match="TOKEN_ENCRYPTION_KEY"):
        create_app()


def test_session_cookie_hardening(env):
    app = create_app()

    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    # Fixture sets SESSION_COOKIE_SECURE=False (local over http).
    assert app.config["SESSION_COOKIE_SECURE"] is False


def test_session_cookie_secure_defaults_to_true(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", VALID_KEY)
    monkeypatch.delenv("SESSION_COOKIE_SECURE", raising=False)

    app = create_app()

    assert app.config["SESSION_COOKIE_SECURE"] is True


def test_database_defaults_to_absolute_instance_path(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", VALID_KEY)
    monkeypatch.delenv("DATABASE", raising=False)

    app = create_app()
    db_path = app.config["DATABASE"]

    # Must be absolute and rooted at instance_path, so the resolved DB does not
    # depend on the process working directory (gunicorn under systemd, etc.).
    assert os.path.isabs(db_path)
    assert db_path == os.path.join(app.instance_path, "reportes.db")


def test_database_env_var_wins_over_default(env):
    app = create_app()

    # The fixture points DATABASE at a temp file; the env value must be honored.
    assert app.config["DATABASE"] == str(env["db_path"])
