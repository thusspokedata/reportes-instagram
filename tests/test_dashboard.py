import json
import re

from app.db import get_db
from app.routes.dashboard import (
    MIN_SAMPLE,
    _median,
    _reach_by_media_type,
    build_dashboard_data,
    build_demographics,
    build_evolution,
)


def _snap(date, followers=None, reach=None, views=None):
    return {
        "snapshot_date": date,
        "follower_count": followers,
        "reach": reach,
        "views": views,
    }


def _drow(breakdown, bucket, value):
    return {"breakdown": breakdown, "bucket": bucket, "value": value}


def _post(
    media_id="M1",
    media_type="IMAGE",
    likes=0,
    comments=0,
    reach=0,
    timestamp=None,
    views=None,
    saved=None,
    shares=None,
    total_interactions=None,
):
    return {
        "media_id": media_id,
        "media_type": media_type,
        "permalink": None,
        "caption": None,
        "timestamp": timestamp,
        "likes": likes,
        "comments": comments,
        "reach": reach,
        "views": views,
        "saved": saved,
        "shares": shares,
        "total_interactions": total_interactions,
    }


# --- cálculos puros ------------------------------------------------------

def test_median_ignores_none():
    assert _median([1, 2, 3]) == 2
    assert _median([1, 2, 3, None]) == 2
    assert _median([10, None, 20]) == 15
    assert _median([5]) == 5
    assert _median([None, None]) is None
    assert _median([]) is None


def test_median_ignores_non_numeric_garbage():
    # SQLite es de tipado dinámico: si llegara un no-número desde Meta, se
    # ignora como un NULL en vez de romper la aritmética.
    assert _median(["garbage", 5, 15]) == 10
    assert _median(["a", "b"]) is None


def test_build_summary_and_medians():
    snapshot = {
        "follower_count": 147,
        "reach": 228,
        "views": 500,
        "total_interactions": 40,
        "accounts_engaged": 30,
        "snapshot_date": "2026-06-03",
    }
    posts = [
        _post("M1", "IMAGE", likes=5, comments=2, reach=10, views=20, saved=2, shares=1, total_interactions=8),
        _post("M2", "IMAGE", likes=15, comments=4, reach=None, views=40, saved=4, shares=3, total_interactions=22),
    ]
    data = build_dashboard_data(snapshot, posts)

    assert data["summary"]["followers"] == 147
    assert data["summary"]["reach"] == 228
    assert data["summary"]["views"] == 500
    assert data["summary"]["interactions"] == 40
    assert data["summary"]["accounts_engaged"] == 30
    assert data["summary"]["posts"] == 2
    assert data["medians"]["likes"] == 10  # median(5, 15)
    assert data["medians"]["reach"] == 10  # median([10]) ignorando el None
    assert data["medians"]["views"] == 30  # median(20, 40)
    assert data["medians"]["saved"] == 3  # median(2, 4)
    assert data["medians"]["shares"] == 2  # median(1, 3)
    assert data["medians"]["interactions"] == 15  # median(8, 22)
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


def test_build_summary_includes_profile_views_and_clicks():
    snapshot = {
        "follower_count": 196,
        "reach": 109,
        "profile_views": 17,
        "website_clicks": 2,
        "snapshot_date": "2026-06-12",
    }
    data = build_dashboard_data(snapshot, [])
    assert data["summary"]["profile_views"] == 17
    assert data["summary"]["website_clicks"] == 2
    # Snapshot viejo sin las columnas -> None (no rompe, no 0).
    assert build_dashboard_data({"follower_count": 1}, [])["summary"]["profile_views"] is None


def test_build_reels_watch_median_only_videos_in_seconds():
    posts = [
        dict(_post("V1", "VIDEO", reach=1), avg_watch_time_ms=6585),
        dict(_post("V2", "VIDEO", reach=1), avg_watch_time_ms=4000),
        dict(_post("V3", "VIDEO", reach=1), avg_watch_time_ms=None),  # NULL ignorado
        dict(_post("I1", "IMAGE", reach=1), avg_watch_time_ms=None),
    ]
    data = build_dashboard_data(None, posts)
    # mediana(6585, 4000) = 5292.5 ms -> 5.3 s; n = videos con dato real.
    assert data["reels"]["median_watch_s"] == 5.3
    assert data["reels"]["n"] == 2


def test_build_reels_watch_none_without_data():
    posts = [_post("I1", "IMAGE", reach=1)]
    data = build_dashboard_data(None, posts)
    # Sin videos con dato: None (sin dato), nunca 0.
    assert data["reels"]["median_watch_s"] is None
    assert data["reels"]["n"] == 0


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
    # La línea de medianas incluye las métricas nuevas (aunque sin dato aún).
    assert b"vistas:" in response.data
    assert b"guardados:" in response.data
    assert b"compartidos:" in response.data
    assert b"interacciones:" in response.data


def test_dashboard_renders_new_account_metric_cards(user_factory, inited_app):
    user = user_factory()
    with inited_app.app_context():
        db = get_db()
        db.execute(
            "INSERT INTO account_snapshots (user_id, snapshot_date, follower_count,"
            " reach, views, accounts_engaged, total_interactions, profile_views,"
            " website_clicks)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user["id"], "2026-06-12", 193, 105, 777, 88, 222, 17, 31),
        )
        db.commit()
    client = inited_app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = user["id"]
        sess["logged_in"] = True

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert b"Vistas del d" in response.data and b"777" in response.data
    assert b"Interacciones del d" in response.data and b"222" in response.data
    assert b"Cuentas que interactuaron" in response.data and b"88" in response.data
    assert b"Visitas al perfil" in response.data and b"17" in response.data
    # 31 es distintivo (un "3" pelado matchearía dentro de "193").
    assert b"Clics al sitio web" in response.data and b"31" in response.data


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


# --- demografía ----------------------------------------------------------

def test_build_demographics_none_when_empty():
    assert build_demographics([]) is None


def test_build_demographics_gender_mapped_and_sorted():
    rows = [_drow("gender", "M", 36), _drow("gender", "F", 39), _drow("gender", "U", 16)]
    demo = build_demographics(rows)
    # F primero (desc por value) y etiquetas legibles.
    assert demo["gender"][0] == {"label": "Femenino", "value": 39}
    assert [g["label"] for g in demo["gender"]] == [
        "Femenino", "Masculino", "Desconocido"
    ]


def test_build_demographics_country_top_n_groups_rest():
    rows = [_drow("country", f"C{i}", 20 - i) for i in range(12)]  # 12 países
    demo = build_demographics(rows)
    assert len(demo["country"]) == 9  # top 8 + "Otros"
    assert demo["country"][-1]["label"] == "Otros"
    assert demo["country"][-1]["value"] == sum(20 - i for i in range(8, 12))


def test_build_demographics_age_sorted():
    rows = [
        _drow("age", "25-34", 31),
        _drow("age", "18-24", 2),
        _drow("age", "45-54", 19),
    ]
    demo = build_demographics(rows)
    assert [a["label"] for a in demo["age"]] == ["18-24", "25-34", "45-54"]


def test_dashboard_renders_demographics_when_present(user_factory, inited_app):
    user = user_factory()
    with inited_app.app_context():
        db = get_db()
        db.execute(
            "INSERT INTO audience_demographics (user_id, breakdown, bucket, value)"
            " VALUES (?, ?, ?, ?)",
            (user["id"], "gender", "F", 39),
        )
        db.commit()
    client = inited_app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = user["id"]
        sess["logged_in"] = True

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert b"chart-demo-gender" in response.data


def test_build_demographics_otros_is_none_when_rest_all_none():
    # Top con valores; el resto todo None -> "Otros" debe ser None (no 0).
    rows = [_drow("country", f"C{i}", 20 - i) for i in range(8)]
    rows += [_drow("country", f"X{j}", None) for j in range(3)]
    demo = build_demographics(rows)
    otros = [c for c in demo["country"] if c["label"] == "Otros"]
    assert len(otros) == 1
    assert otros[0]["value"] is None  # null, nunca 0


# --- evolución (serie temporal) ------------------------------------------

def test_build_evolution_orders_and_preserves_null():
    rows = [
        _snap("2026-06-03", 147, 228),
        _snap("2026-06-06", 154, None),  # reach NULL
    ]
    evo = build_evolution(rows)
    assert evo["labels"] == ["2026-06-03", "2026-06-06"]
    assert evo["followers"] == [147, 154]
    assert evo["reach"] == [228, None]  # NULL se preserva, nunca 0
    assert evo["enough"] is True


def test_build_evolution_views_none_when_all_null():
    rows = [_snap("2026-06-03", 147, 228, None), _snap("2026-06-04", 150, 100, None)]
    # views todo NULL (caso típico): la serie se omite (no se dibuja vacía).
    assert build_evolution(rows)["views"] is None


def test_build_evolution_views_present_when_some_real():
    rows = [_snap("2026-06-03", 147, 228, None), _snap("2026-06-04", 150, 100, 5)]
    assert build_evolution(rows)["views"] == [None, 5]


def test_build_evolution_not_enough_with_single_point():
    # Una línea de un solo punto no se dibuja.
    assert build_evolution([_snap("2026-06-03", 147, 228)])["enough"] is False


def test_build_evolution_empty():
    evo = build_evolution([])
    assert evo["enough"] is False
    assert evo["labels"] == []


def _insert_snapshots(db, user_id, rows):
    for date, followers, reach in rows:
        db.execute(
            "INSERT INTO account_snapshots (user_id, snapshot_date, follower_count, reach)"
            " VALUES (?, ?, ?, ?)",
            (user_id, date, followers, reach),
        )
    db.commit()


def test_dashboard_renders_evolution_with_enough_snapshots(user_factory, inited_app):
    user = user_factory()
    with inited_app.app_context():
        _insert_snapshots(
            get_db(),
            user["id"],
            [("2026-06-03", 147, 228), ("2026-06-04", 150, 100), ("2026-06-05", 155, 300)],
        )
    client = inited_app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = user["id"]
        sess["logged_in"] = True

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert b"chart-evolution-followers" in response.data
    assert b"chart-evolution-reach" in response.data


def test_dashboard_evolution_placeholder_with_one_snapshot(user_factory, inited_app):
    user = user_factory()
    with inited_app.app_context():
        _insert_snapshots(get_db(), user["id"], [("2026-06-03", 147, 228)])
    client = inited_app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = user["id"]
        sess["logged_in"] = True

    response = client.get("/dashboard")

    assert response.status_code == 200
    # Con 1 solo snapshot no se dibuja la evolución (se mantiene el placeholder).
    assert b"chart-evolution-followers" not in response.data


def _dashboard_data(html_bytes):
    """Extrae el JSON inyectado para Chart.js desde el HTML renderizado."""
    m = re.search(
        rb'<script id="dashboard-data" type="application/json">(.*?)</script>',
        html_bytes,
        re.S,
    )
    assert m, "no se encontró el bloque dashboard-data"
    return json.loads(m.group(1).decode())


def test_dashboard_evolution_orders_by_date_and_card_shows_latest(
    user_factory, inited_app
):
    user = user_factory()
    with inited_app.app_context():
        # Insertadas DESORDENADAS a propósito: la serie debe salir ASC y la
        # tarjeta de seguidores debe mostrar el día más reciente (no el viejo).
        _insert_snapshots(
            get_db(),
            user["id"],
            [("2026-06-05", 155, 300), ("2026-06-03", 147, 228), ("2026-06-04", 150, 100)],
        )
    client = inited_app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = user["id"]
        sess["logged_in"] = True

    response = client.get("/dashboard")
    data = _dashboard_data(response.data)

    assert data["evolution"]["labels"] == ["2026-06-03", "2026-06-04", "2026-06-05"]
    assert data["evolution"]["followers"] == [147, 150, 155]
    # La tarjeta de resumen toma el snapshot más reciente.
    assert data["summary"]["followers"] == 155


def test_dashboard_evolution_reach_null_serialized_as_null(user_factory, inited_app):
    user = user_factory()
    with inited_app.app_context():
        _insert_snapshots(
            get_db(),
            user["id"],
            [("2026-06-03", 147, 228), ("2026-06-04", 150, None)],  # reach NULL
        )
    client = inited_app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = user["id"]
        sess["logged_in"] = True

    response = client.get("/dashboard")
    data = _dashboard_data(response.data)

    # NULL llega como null (no 0, no "None") al JSON que consume Chart.js.
    assert data["evolution"]["reach"] == [228, None]
