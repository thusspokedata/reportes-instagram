from app.db import get_db
from app.insights.store import (
    save_account_snapshot,
    save_demographics,
    save_post_metrics,
)


def test_save_account_snapshot_upsert_no_duplicate(user_factory, inited_app):
    user = user_factory()
    with inited_app.app_context():
        save_account_snapshot(user, {"reach": 100, "follower_count": 50}, "2026-06-03")
        save_account_snapshot(user, {"reach": 150, "follower_count": 55}, "2026-06-03")
        rows = get_db().execute(
            "SELECT reach, follower_count FROM account_snapshots WHERE user_id = ?",
            (user["id"],),
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["reach"] == 150
    assert rows[0]["follower_count"] == 55


def test_save_account_snapshot_null_stays_null(user_factory, inited_app):
    user = user_factory()
    with inited_app.app_context():
        save_account_snapshot(user, {"reach": 100, "follower_count": None}, "2026-06-03")
        row = get_db().execute(
            "SELECT follower_count FROM account_snapshots WHERE user_id = ?",
            (user["id"],),
        ).fetchone()
    # Ausencia de dato = NULL, NUNCA 0.
    assert row["follower_count"] is None


def test_save_account_snapshot_persists_extended_metrics(user_factory, inited_app):
    user = user_factory()
    with inited_app.app_context():
        save_account_snapshot(
            user,
            {
                "reach": 105,
                "views": 777,
                "accounts_engaged": 88,
                "total_interactions": 222,
                "follower_count": 193,
            },
            "2026-06-12",
        )
        row = get_db().execute(
            "SELECT views, accounts_engaged, total_interactions"
            " FROM account_snapshots WHERE user_id = ?",
            (user["id"],),
        ).fetchone()
    assert row["views"] == 777
    assert row["accounts_engaged"] == 88
    assert row["total_interactions"] == 222


def test_save_post_metrics_persists_extended_metrics(user_factory, inited_app):
    user = user_factory()
    with inited_app.app_context():
        save_post_metrics(
            user,
            [
                {
                    "media_id": "M1",
                    "media_type": "VIDEO",
                    "reach": 259,
                    "views": 335,
                    "saved": 4,
                    "shares": 2,
                    "total_interactions": 39,
                }
            ],
        )
        row = get_db().execute(
            "SELECT views, saved, shares, total_interactions FROM post_metrics"
            " WHERE user_id = ? AND media_id = 'M1'",
            (user["id"],),
        ).fetchone()
    assert row["views"] == 335
    assert row["saved"] == 4
    assert row["shares"] == 2
    assert row["total_interactions"] == 39


def test_save_post_metrics_upsert_no_duplicate(user_factory, inited_app):
    user = user_factory()
    with inited_app.app_context():
        save_post_metrics(
            user,
            [{"media_id": "M1", "media_type": "IMAGE", "likes": 5, "comments": 1, "reach": 10}],
        )
        save_post_metrics(
            user,
            [{"media_id": "M1", "media_type": "IMAGE", "likes": 8, "comments": 2, "reach": 20}],
        )
        rows = get_db().execute(
            "SELECT likes, comments, reach FROM post_metrics"
            " WHERE user_id = ? AND media_id = 'M1'",
            (user["id"],),
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["likes"] == 8
    assert rows[0]["comments"] == 2
    assert rows[0]["reach"] == 20


def test_save_demographics_replaces_not_duplicates(user_factory, inited_app):
    user = user_factory()
    with inited_app.app_context():
        save_demographics(user, {"gender": {"F": 39, "M": 36}})
        # "foto actual": una segunda bajada reemplaza, no acumula.
        save_demographics(user, {"gender": {"F": 40, "M": 35, "U": 10}})
        rows = get_db().execute(
            "SELECT bucket, value FROM audience_demographics"
            " WHERE user_id = ? AND breakdown = 'gender'",
            (user["id"],),
        ).fetchall()
    got = {r["bucket"]: r["value"] for r in rows}
    assert got == {"F": 40, "M": 35, "U": 10}
