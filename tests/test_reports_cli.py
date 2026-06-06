from app.db import get_db
from app.reports import generate


def test_generate_monthly_report_command_persists(user_factory, inited_app, monkeypatch):
    user = user_factory()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    # No tocar la red: el texto del modelo se mockea.
    monkeypatch.setattr(
        generate, "generate_report_text", lambda *a, **k: "Reporte mensual."
    )

    result = inited_app.test_cli_runner().invoke(args=["generate-monthly-report"])

    assert result.exit_code == 0
    with inited_app.app_context():
        n = get_db().execute(
            "SELECT COUNT(*) c FROM reports WHERE user_id = ?", (user["id"],)
        ).fetchone()["c"]
    assert n == 1


def test_generate_monthly_report_uses_previous_month_label(
    user_factory, inited_app, monkeypatch
):
    user = user_factory()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(generate, "generate_report_text", lambda *a, **k: "x")

    # Congelar "hoy" en junio: el período del reporte mensual es mayo.
    import datetime as _dt

    class _FixedDate(_dt.date):
        @classmethod
        def today(cls):
            return _dt.date(2026, 6, 6)

    monkeypatch.setattr(generate, "date", _FixedDate)

    result = inited_app.test_cli_runner().invoke(args=["generate-monthly-report"])

    assert result.exit_code == 0
    with inited_app.app_context():
        row = get_db().execute(
            "SELECT period_label FROM reports WHERE user_id = ?", (user["id"],)
        ).fetchone()
    assert row["period_label"] == "2026-05"


def test_generate_monthly_report_degrades_without_api_key(
    user_factory, inited_app, monkeypatch
):
    user = user_factory()
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    # Sin api key, no se debe tocar la red ni romper: corta limpio y avisa.
    result = inited_app.test_cli_runner().invoke(args=["generate-monthly-report"])

    assert result.exit_code == 0
    with inited_app.app_context():
        n = get_db().execute(
            "SELECT COUNT(*) c FROM reports WHERE user_id = ?", (user["id"],)
        ).fetchone()["c"]
    assert n == 0  # no se guardó nada


def test_generate_monthly_report_no_users(inited_app, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    result = inited_app.test_cli_runner().invoke(args=["generate-monthly-report"])
    assert result.exit_code == 0
