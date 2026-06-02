import pytest

from app import create_app


def test_app_starts_with_valid_config(env):
    app = create_app()

    assert app.config["SECRET_KEY"] == "test-secret"
    assert app.config["GRAPH_API_VERSION"] == "v22.0"
    assert app.config["REDIRECT_URI"] == "http://localhost:5000/auth/callback"


def test_missing_secret_key_fails_loudly(env, monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)

    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app()


def test_database_defaults_to_instance_path(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.delenv("DATABASE", raising=False)

    app = create_app()

    assert app.config["DATABASE"].endswith("instance/reportes.db")
