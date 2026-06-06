from app.reports.store import latest_reports, save_report


def test_save_and_latest_reports_orders_newest_first(user_factory, inited_app):
    user = user_factory()
    with inited_app.app_context():
        save_report(user, "primero", "2026-04", "claude-haiku-4-5")
        save_report(user, "segundo", "2026-05", "claude-haiku-4-5")
        rows = latest_reports(user["id"])

    assert len(rows) == 2
    # El más nuevo (mayor id) primero.
    assert rows[0]["content"] == "segundo"
    assert rows[1]["content"] == "primero"


def test_latest_reports_respects_limit(user_factory, inited_app):
    user = user_factory()
    with inited_app.app_context():
        for i in range(5):
            save_report(user, f"r{i}", "2026-05", "claude-haiku-4-5")
        rows = latest_reports(user["id"], limit=2)
    assert len(rows) == 2


def test_latest_reports_isolates_users(user_factory, inited_app):
    user_a = user_factory(fb_user_id="a", nombre="A")
    user_b = user_factory(fb_user_id="b", nombre="B")
    with inited_app.app_context():
        save_report(user_b, "secreto de B", "2026-05", "claude-haiku-4-5")
        rows = latest_reports(user_a["id"])
    assert rows == []
