import os

import pytest
from cryptography.fernet import Fernet


@pytest.fixture
def env(monkeypatch, tmp_path):
    """Set a valid baseline environment for the app, using a temp DB path."""
    db_path = tmp_path / "test.db"
    token_key = Fernet.generate_key().decode()
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("FACEBOOK_APP_ID", "test-app-id")
    monkeypatch.setenv("FACEBOOK_APP_SECRET", "test-app-secret")
    monkeypatch.setenv("REDIRECT_URI", "http://localhost:5000/auth/callback")
    monkeypatch.setenv("GRAPH_API_VERSION", "v23.0")
    monkeypatch.setenv("DATABASE", str(db_path))
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", token_key)
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "False")
    return {"db_path": db_path, "token_key": token_key}


@pytest.fixture
def inited_app(env):
    """App with the schema applied (init_db run)."""
    from app import create_app
    from app.db import init_db

    app = create_app()
    with app.app_context():
        init_db()
    return app


@pytest.fixture
def user_factory(inited_app):
    """Create a usuaria row (with an encrypted token) and return it."""
    from app.auth.crypto import encrypt_token
    from app.db import get_db, upsert_user

    def make(token="TESTTOKEN", fb_user_id="fbuser1", nombre="Tester"):
        with inited_app.app_context():
            upsert_user(fb_user_id, nombre, encrypt_token(token), None)
            return get_db().execute(
                "SELECT * FROM usuarias WHERE fb_user_id = ?", (fb_user_id,)
            ).fetchone()

    return make
