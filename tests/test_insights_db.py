import sqlite3

import pytest

from app.db import get_db


def test_insights_tables_exist(inited_app):
    with inited_app.app_context():
        names = {
            r[0]
            for r in get_db().execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert {"account_snapshots", "post_metrics"} <= names


def test_account_snapshots_unique_per_user_day(user_factory, inited_app):
    user = user_factory()
    with inited_app.app_context():
        db = get_db()
        db.execute(
            "INSERT INTO account_snapshots (user_id, snapshot_date, reach) VALUES (?,?,?)",
            (user["id"], "2026-06-03", 10),
        )
        db.commit()
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO account_snapshots (user_id, snapshot_date, reach) VALUES (?,?,?)",
                (user["id"], "2026-06-03", 20),
            )
            db.commit()


def test_post_metrics_unique_per_user_media(user_factory, inited_app):
    user = user_factory()
    with inited_app.app_context():
        db = get_db()
        db.execute(
            "INSERT INTO post_metrics (user_id, media_id) VALUES (?,?)",
            (user["id"], "M1"),
        )
        db.commit()
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO post_metrics (user_id, media_id) VALUES (?,?)",
                (user["id"], "M1"),
            )
            db.commit()


def test_fk_cascade_delete(user_factory, inited_app):
    user = user_factory()
    with inited_app.app_context():
        db = get_db()
        db.execute(
            "INSERT INTO account_snapshots (user_id, snapshot_date) VALUES (?,?)",
            (user["id"], "2026-06-03"),
        )
        db.execute(
            "INSERT INTO post_metrics (user_id, media_id) VALUES (?,?)",
            (user["id"], "M1"),
        )
        db.commit()
        db.execute("DELETE FROM usuarias WHERE id = ?", (user["id"],))
        db.commit()
        assert db.execute("SELECT COUNT(*) FROM account_snapshots").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM post_metrics").fetchone()[0] == 0
