import pytest

from app.db import get_db
from app.insights import fetch, service


def test_refresh_account_data_captures_snapshot_and_demographics(
    user_factory, inited_app, monkeypatch
):
    user = user_factory()
    calls = {"resolve": 0}

    def resolve(u):
        calls["resolve"] += 1
        return "IG1"

    monkeypatch.setattr(fetch, "resolve_ig_account", resolve)

    # Cada bajada debe recibir el ig_id resuelto ("IG1"), no None: confirma que
    # refresh_account_data propaga la cuenta resuelta a snapshot + demografía.
    def _profile(u, ig_id=None):
        assert ig_id == "IG1"
        return {"followers_count": 192, "media_count": 10}

    def _account(u, ig_id=None):
        assert ig_id == "IG1"
        return {"reach": 379}

    def _demographics(u, ig_id=None):
        assert ig_id == "IG1"
        return {"gender": {"F": 100, "M": 87}, "age": {}, "country": {}, "city": {}}

    monkeypatch.setattr(fetch, "fetch_profile", _profile)
    monkeypatch.setattr(fetch, "fetch_account_insights", _account)
    monkeypatch.setattr(fetch, "fetch_demographics", _demographics)

    with inited_app.app_context():
        service.refresh_account_data(user)
        db = get_db()
        snap = db.execute(
            "SELECT follower_count, reach FROM account_snapshots WHERE user_id = ?",
            (user["id"],),
        ).fetchone()
        gender = db.execute(
            "SELECT COUNT(*) c FROM audience_demographics"
            " WHERE user_id = ? AND breakdown = 'gender'",
            (user["id"],),
        ).fetchone()["c"]

    # follower_count viene del PERFIL (192), no del delta de insights.
    assert snap["follower_count"] == 192
    assert snap["reach"] == 379
    assert gender == 2
    # La cuenta IG se resuelve UNA sola vez para snapshot + demografía.
    assert calls["resolve"] == 1


def test_refresh_account_data_propagates_rate_limit(user_factory, inited_app, monkeypatch):
    user = user_factory()

    def boom(u):
        raise fetch.RateLimitError("rate limited")

    monkeypatch.setattr(fetch, "resolve_ig_account", boom)

    with inited_app.app_context():
        with pytest.raises(fetch.RateLimitError):
            service.refresh_account_data(user)
