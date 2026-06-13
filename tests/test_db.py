import sqlite3

from app import create_app
from app.db import get_db, init_db


def test_init_db_creates_database_file(env):
    app = create_app()

    with app.app_context():
        init_db()

    assert env["db_path"].exists()


def test_get_db_returns_row_factory_connection(env):
    app = create_app()

    with app.app_context():
        db = get_db()
        assert isinstance(db, sqlite3.Connection)
        assert db.row_factory is sqlite3.Row


def test_get_db_enables_foreign_keys(env):
    app = create_app()

    with app.app_context():
        db = get_db()
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_init_db_cli_command(env):
    app = create_app()

    runner = app.test_cli_runner()
    result = runner.invoke(args=["init-db"])

    assert result.exit_code == 0
    assert env["db_path"].exists()


def test_init_db_migrates_existing_tables_with_missing_columns(env):
    # Simula una base "vieja": tablas creadas ANTES de las columnas nuevas.
    # CREATE TABLE IF NOT EXISTS no las agregaría; init_db debe migrarlas.
    con = sqlite3.connect(env["db_path"])
    con.execute(
        "CREATE TABLE account_snapshots ("
        " id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,"
        " snapshot_date DATE NOT NULL, reach INTEGER)"
    )
    con.execute(
        "CREATE TABLE post_metrics ("
        " id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,"
        " media_id TEXT NOT NULL, reach INTEGER)"
    )
    con.commit()
    con.close()

    app = create_app()
    with app.app_context():
        init_db()
        init_db()  # idempotente: correrlo dos veces no duplica ni rompe
        db = get_db()
        snap_cols = {r[1] for r in db.execute("PRAGMA table_info(account_snapshots)")}
        post_cols = {r[1] for r in db.execute("PRAGMA table_info(post_metrics)")}

    assert {"profile_views", "website_clicks"} <= snap_cols
    assert {"avg_watch_time_ms", "video_view_total_time_ms"} <= post_cols


def test_migrated_db_matches_fresh_schema(env):
    # Una base "vieja" migrada por init_db debe quedar con EXACTAMENTE las
    # mismas columnas que una creada fresca desde schema.sql — detecta drift
    # entre schema.sql y _COLUMN_MIGRATIONS (doble mantenimiento).
    from app.db import _COLUMN_MIGRATIONS

    con = sqlite3.connect(env["db_path"])
    con.execute(
        "CREATE TABLE account_snapshots ("
        " id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,"
        " snapshot_date DATE NOT NULL, views INTEGER, reach INTEGER,"
        " follower_count INTEGER, reposts INTEGER, accounts_engaged INTEGER,"
        " total_interactions INTEGER,"
        " creado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        " actualizado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    con.commit()
    con.close()

    app = create_app()
    with app.app_context():
        init_db()
        db = get_db()
        migrated = {
            table: {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
            for table in _COLUMN_MIGRATIONS
        }
        # Fresca: schema.sql aplicado sobre una base vacía en memoria.
        fresh_con = sqlite3.connect(":memory:")
        with app.open_resource("schema.sql") as f:
            fresh_con.executescript(f.read().decode("utf8"))
        fresh = {
            table: {r[1] for r in fresh_con.execute(f"PRAGMA table_info({table})")}
            for table in _COLUMN_MIGRATIONS
        }
        fresh_con.close()

    assert migrated == fresh
