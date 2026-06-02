import os

import pytest


@pytest.fixture
def env(monkeypatch, tmp_path):
    """Set a valid baseline environment for the app, using a temp DB path."""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("FACEBOOK_APP_ID", "test-app-id")
    monkeypatch.setenv("FACEBOOK_APP_SECRET", "test-app-secret")
    monkeypatch.setenv("REDIRECT_URI", "http://localhost:5000/auth/callback")
    monkeypatch.setenv("GRAPH_API_VERSION", "v22.0")
    monkeypatch.setenv("DATABASE", str(db_path))
    return {"db_path": db_path}
