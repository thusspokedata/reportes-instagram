from app.db import get_db
from app.insights import fetch, service


def _login(client, user):
    with client.session_transaction() as sess:
        sess["user_id"] = user["id"]
        sess["logged_in"] = True


def test_actualizar_requires_session(inited_app):
    response = inited_app.test_client().post("/actualizar")
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_actualizar_rejects_cross_origin(user_factory, inited_app, monkeypatch):
    user = user_factory()
    called = {"n": 0}
    monkeypatch.setattr(
        service, "refresh_account_data", lambda u: called.__setitem__("n", called["n"] + 1)
    )
    client = inited_app.test_client()
    _login(client, user)

    response = client.post("/actualizar", headers={"Origin": "http://evil.example"})

    assert response.status_code == 403
    assert called["n"] == 0  # no se tocó Meta


def test_actualizar_success_persists(user_factory, inited_app, monkeypatch):
    user = user_factory()
    monkeypatch.setattr(fetch, "resolve_ig_account", lambda u: "IG1")
    monkeypatch.setattr(
        fetch, "fetch_profile", lambda u, ig_id=None: {"followers_count": 192}
    )
    monkeypatch.setattr(
        fetch, "fetch_account_insights", lambda u, ig_id=None: {"reach": 379}
    )
    monkeypatch.setattr(
        fetch,
        "fetch_demographics",
        lambda u, ig_id=None: {"gender": {"F": 100}, "age": {}, "country": {}, "city": {}},
    )
    client = inited_app.test_client()
    _login(client, user)

    response = client.post("/actualizar")

    assert response.status_code == 302  # redirige al dashboard
    assert "/dashboard" in response.headers["Location"]
    with inited_app.app_context():
        db = get_db()
        snap = db.execute(
            "SELECT follower_count FROM account_snapshots WHERE user_id = ?",
            (user["id"],),
        ).fetchone()
        demo = db.execute(
            "SELECT COUNT(*) c FROM audience_demographics WHERE user_id = ?",
            (user["id"],),
        ).fetchone()["c"]
    assert snap["follower_count"] == 192  # snapshot del día persistido
    assert demo == 1  # demografía también refrescada


def test_actualizar_allows_same_origin(user_factory, inited_app, monkeypatch):
    user = user_factory()
    monkeypatch.setattr(service, "refresh_account_data", lambda u: None)
    client = inited_app.test_client()
    _login(client, user)

    # Origin propio (mismo host del test client): se acepta.
    response = client.post("/actualizar", headers={"Origin": "http://localhost"})

    assert response.status_code == 302
    assert "/dashboard" in response.headers["Location"]


def test_actualizar_degrades_on_rate_limit(user_factory, inited_app, monkeypatch):
    user = user_factory()

    def boom(u):
        raise fetch.RateLimitError("rate limited")

    monkeypatch.setattr(service, "refresh_account_data", boom)
    client = inited_app.test_client()
    _login(client, user)

    response = client.post("/actualizar", follow_redirects=True)

    # No rompe: vuelve al dashboard (botón presente) con un flash de error, sin 500.
    assert response.status_code == 200
    assert b"Actualizar datos" in response.data
    assert b"flash-error" in response.data


def test_actualizar_degrades_on_insights_error(user_factory, inited_app, monkeypatch):
    user = user_factory()

    def boom(u):
        raise fetch.InsightsError("falló Meta")

    monkeypatch.setattr(service, "refresh_account_data", boom)
    client = inited_app.test_client()
    _login(client, user)

    response = client.post("/actualizar", follow_redirects=True)

    assert response.status_code == 200
    assert b"Actualizar datos" in response.data
    assert b"flash-error" in response.data
