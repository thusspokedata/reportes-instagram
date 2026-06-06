from app.db import get_db
from app.reports import generate
from app.reports.store import save_report


def _login(client, user):
    with client.session_transaction() as sess:
        sess["user_id"] = user["id"]
        sess["logged_in"] = True


def test_generar_reporte_requires_session(inited_app):
    response = inited_app.test_client().post("/reporte")
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_generar_reporte_creates_report(user_factory, inited_app, monkeypatch):
    user = user_factory()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(
        generate, "generate_report_text", lambda *a, **k: "Tu cuenta creció."
    )

    client = inited_app.test_client()
    _login(client, user)
    response = client.post("/reporte")

    assert response.status_code == 302  # redirige al dashboard
    with inited_app.app_context():
        n = get_db().execute(
            "SELECT COUNT(*) c FROM reports WHERE user_id = ?", (user["id"],)
        ).fetchone()["c"]
    assert n == 1


def test_generar_reporte_degrades_on_failure(user_factory, inited_app, monkeypatch):
    user = user_factory()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    def boom(*a, **k):
        raise generate.ReportError("no disponible")

    monkeypatch.setattr(generate, "generate_report_text", boom)

    client = inited_app.test_client()
    _login(client, user)
    response = client.post("/reporte", follow_redirects=True)

    # No rompe: vuelve al dashboard con un aviso, sin 500.
    assert response.status_code == 200
    with inited_app.app_context():
        n = get_db().execute(
            "SELECT COUNT(*) c FROM reports WHERE user_id = ?", (user["id"],)
        ).fetchone()["c"]
    assert n == 0


def test_dashboard_shows_report_history(user_factory, inited_app):
    user = user_factory()
    with inited_app.app_context():
        save_report(user, "Contenido del reporte mensual.", "2026-05", "claude-haiku-4-5")

    client = inited_app.test_client()
    _login(client, user)
    response = client.get("/dashboard")

    assert response.status_code == 200
    assert b"Contenido del reporte mensual." in response.data


def test_dashboard_escapes_report_content_no_xss(user_factory, inited_app):
    user = user_factory()
    with inited_app.app_context():
        save_report(user, "<script>alert('x')</script>", "2026-05", "claude-haiku-4-5")

    client = inited_app.test_client()
    _login(client, user)
    response = client.get("/dashboard")

    assert response.status_code == 200
    # El contenido se escapa; no debe inyectarse un <script> ejecutable.
    assert b"<script>alert" not in response.data
    assert b"&lt;script&gt;" in response.data


def test_dashboard_report_does_not_leak_other_users(user_factory, inited_app):
    user_a = user_factory(fb_user_id="a", nombre="A")
    user_b = user_factory(fb_user_id="b", nombre="B")
    with inited_app.app_context():
        save_report(user_b, "REPORTE_SECRETO_DE_B", "2026-05", "claude-haiku-4-5")

    client = inited_app.test_client()
    _login(client, user_a)
    response = client.get("/dashboard")

    assert response.status_code == 200
    assert b"REPORTE_SECRETO_DE_B" not in response.data
