from app.db import get_db
from app.insights import fetch
from app.insights.fetch import RateLimitError


def test_fetch_insights_command_persists(user_factory, inited_app, monkeypatch):
    user = user_factory()

    monkeypatch.setattr(fetch, "resolve_ig_account", lambda u: "IG1")
    monkeypatch.setattr(
        fetch,
        "fetch_account_insights",
        lambda u, ig_id=None: {"reach": 100, "follower_count": None},
    )
    monkeypatch.setattr(
        fetch,
        "fetch_media_list",
        lambda u, ig_id=None: [
            {
                "id": "M1",
                "media_type": "IMAGE",
                "like_count": 5,
                "comments_count": 2,
                "permalink": "p",
                "caption": "c",
                "timestamp": "2026-06-01T00:00:00+0000",
            }
        ],
    )
    monkeypatch.setattr(
        fetch, "fetch_media_insights", lambda u, mid, mt=None: {"reach": 33}
    )

    result = inited_app.test_cli_runner().invoke(args=["fetch-insights"])

    assert result.exit_code == 0
    with inited_app.app_context():
        db = get_db()
        snap = db.execute(
            "SELECT reach, follower_count FROM account_snapshots WHERE user_id = ?",
            (user["id"],),
        ).fetchone()
        post = db.execute(
            "SELECT likes, comments, reach FROM post_metrics"
            " WHERE user_id = ? AND media_id = 'M1'",
            (user["id"],),
        ).fetchone()

    assert snap["reach"] == 100
    assert snap["follower_count"] is None
    assert post["likes"] == 5
    assert post["comments"] == 2
    assert post["reach"] == 33


def test_fetch_insights_command_aborts_on_rate_limit(user_factory, inited_app, monkeypatch):
    user_factory()

    def boom(u):
        raise RateLimitError("rate limited")

    # El primer toque de red del run es la resolución de la cuenta IG.
    monkeypatch.setattr(fetch, "resolve_ig_account", boom)

    result = inited_app.test_cli_runner().invoke(args=["fetch-insights"])

    # Corta limpio (sin reintentos agresivos) y avisa.
    assert result.exit_code == 0
    assert "Límite de solicitudes" in result.output
