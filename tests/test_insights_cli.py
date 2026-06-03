from app.db import get_db
from app.insights import fetch
from app.insights.fetch import RateLimitError


def test_fetch_insights_command_persists(user_factory, inited_app, monkeypatch):
    user = user_factory()

    monkeypatch.setattr(fetch, "resolve_ig_account", lambda u: "IG1")
    monkeypatch.setattr(
        fetch,
        "fetch_profile",
        lambda u, ig_id=None: {"followers_count": 147, "media_count": 1, "username": "x"},
    )
    monkeypatch.setattr(
        fetch, "fetch_account_insights", lambda u, ig_id=None: {"reach": 100}
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

    # follower_count viene del perfil (147), no de insights.
    assert snap["follower_count"] == 147
    assert snap["reach"] == 100
    assert post["likes"] == 5
    assert post["comments"] == 2
    assert post["reach"] == 33


def test_fetch_insights_snapshot_follower_count_null_when_profile_empty(
    user_factory, inited_app, monkeypatch
):
    user = user_factory()
    monkeypatch.setattr(fetch, "resolve_ig_account", lambda u: "IG1")
    # Perfil vacío (ej. <100 seguidores / Meta no devuelve) -> follower_count NULL.
    monkeypatch.setattr(fetch, "fetch_profile", lambda u, ig_id=None: {})
    monkeypatch.setattr(fetch, "fetch_account_insights", lambda u, ig_id=None: {"reach": 5})
    monkeypatch.setattr(fetch, "fetch_media_list", lambda u, ig_id=None: [])

    result = inited_app.test_cli_runner().invoke(args=["fetch-insights"])

    assert result.exit_code == 0
    with inited_app.app_context():
        snap = get_db().execute(
            "SELECT follower_count FROM account_snapshots WHERE user_id = ?",
            (user["id"],),
        ).fetchone()
    assert snap["follower_count"] is None  # NULL, nunca 0


def test_fetch_insights_warns_on_media_count_discrepancy(
    user_factory, inited_app, monkeypatch
):
    user_factory()
    monkeypatch.setattr(fetch, "resolve_ig_account", lambda u: "IG1")
    # El perfil dice 13 posts pero sólo bajamos 1 -> debe avisar.
    monkeypatch.setattr(
        fetch, "fetch_profile", lambda u, ig_id=None: {"followers_count": 147, "media_count": 13}
    )
    monkeypatch.setattr(fetch, "fetch_account_insights", lambda u, ig_id=None: {"reach": 1})
    monkeypatch.setattr(
        fetch, "fetch_media_list", lambda u, ig_id=None: [{"id": "M1"}]
    )
    monkeypatch.setattr(fetch, "fetch_media_insights", lambda u, mid, mt=None: {"reach": 1})

    result = inited_app.test_cli_runner().invoke(args=["fetch-insights"])

    assert result.exit_code == 0
    assert "13" in result.output and "media_count" in result.output


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
