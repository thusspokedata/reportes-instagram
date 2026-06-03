from app.db import get_db
from app.routes.dashboard import (
    MIN_SAMPLE,
    _median,
    _reach_by_media_type,
    build_dashboard_data,
)


def _post(media_id="M1", media_type="IMAGE", likes=0, comments=0, reach=0, timestamp=None):
    return {
        "media_id": media_id,
        "media_type": media_type,
        "permalink": None,
        "caption": None,
        "timestamp": timestamp,
        "likes": likes,
        "comments": comments,
        "reach": reach,
    }


# --- cálculos puros ------------------------------------------------------

def test_median_ignores_none():
    assert _median([1, 2, 3]) == 2
    assert _median([1, 2, 3, None]) == 2
    assert _median([10, None, 20]) == 15
    assert _median([5]) == 5
    assert _median([None, None]) is None
    assert _median([]) is None


def test_build_summary_and_medians():
    snapshot = {"follower_count": 147, "reach": 228, "views": None, "snapshot_date": "2026-06-03"}
    posts = [
        _post("M1", "IMAGE", likes=5, comments=2, reach=10),
        _post("M2", "IMAGE", likes=15, comments=4, reach=None),  # reach NULL
    ]
    data = build_dashboard_data(snapshot, posts)

    assert data["summary"] == {"followers": 147, "reach": 228, "posts": 2}
    assert data["medians"]["likes"] == 10  # median(5, 15)
    assert data["medians"]["reach"] == 10  # median([10]) ignorando el None
    assert data["enough_sample"] is False  # 2 < 12


def test_build_summary_null_not_zero():
    snapshot = {"follower_count": None, "reach": None, "views": None, "snapshot_date": "x"}
    data = build_dashboard_data(snapshot, [])

    # NULL se preserva como None (el front muestra "sin dato"), NUNCA 0.
    assert data["summary"]["followers"] is None
    assert data["summary"]["reach"] is None
    assert data["summary"]["posts"] == 0


def test_build_summary_handles_missing_snapshot():
    data = build_dashboard_data(None, [])
    assert data["summary"]["followers"] is None
    assert data["summary"]["reach"] is None


def test_reach_by_media_type_medians_and_sample_sizes():
    posts = [
        _post("1", "VIDEO", reach=30),
        _post("2", "VIDEO", reach=10),
        _post("3", "IMAGE", reach=None),  # único IMAGE, reach NULL
    ]
    result = {r["type"]: r for r in _reach_by_media_type(posts)}

    assert result["VIDEO"]["median_reach"] == 20
    assert result["VIDEO"]["n"] == 2
    assert result["IMAGE"]["median_reach"] is None  # NULL, no 0
    assert result["IMAGE"]["n"] == 1


def test_enough_sample_true_at_threshold():
    posts = [_post(str(i), "IMAGE", reach=1) for i in range(MIN_SAMPLE)]
    data = build_dashboard_data(None, posts)
    assert data["enough_sample"] is True


# --- ruta ----------------------------------------------------------------

def test_dashboard_requires_session(inited_app):
    response = inited_app.test_client().get("/dashboard")
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_dashboard_renders_for_logged_in_user(user_factory, inited_app):
    user = user_factory()
    with inited_app.app_context():
        db = get_db()
        db.execute(
            "INSERT INTO account_snapshots (user_id, snapshot_date, follower_count, reach)"
            " VALUES (?, ?, ?, ?)",
            (user["id"], "2026-06-03", 147, 228),
        )
        db.execute(
            "INSERT INTO post_metrics (user_id, media_id, media_type, likes, comments, reach)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (user["id"], "M1", "IMAGE", 5, 2, 10),
        )
        db.commit()

    client = inited_app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = user["id"]
        sess["logged_in"] = True

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert b"147" in response.data  # seguidores en la tarjeta


def test_dashboard_does_not_leak_other_users_data(user_factory, inited_app):
    user_a = user_factory(fb_user_id="a", nombre="A")
    user_b = user_factory(fb_user_id="b", nombre="B")
    with inited_app.app_context():
        db = get_db()
        db.execute(
            "INSERT INTO post_metrics (user_id, media_id, media_type, likes, comments, reach)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (user_b["id"], "SECRETMEDIAB", "IMAGE", 999, 888, 777),
        )
        db.commit()

    client = inited_app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = user_a["id"]
        sess["logged_in"] = True

    response = client.get("/dashboard")

    assert response.status_code == 200
    # No se filtran datos de otra usuaria.
    assert b"SECRETMEDIAB" not in response.data
    assert b"999" not in response.data
