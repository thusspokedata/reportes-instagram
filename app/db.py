"""SQLite connection handling, schema init, and the ``init-db`` CLI command.

The connection is cached on Flask's application context (``g``) so a single
request reuses one connection, and it is closed automatically on teardown.

``init_db`` creates the database file and applies ``schema.sql``.
"""

import os
import re
import sqlite3

import click
from flask import current_app, g
from flask.cli import with_appcontext


def get_db():
    """Return a SQLite connection for the current app context.

    Cached on ``g`` so repeated calls within one context reuse the connection.
    Rows are returned as ``sqlite3.Row`` for dict-like access by column name.
    """
    if "db" not in g:
        g.db = sqlite3.connect(
            current_app.config["DATABASE"],
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        g.db.row_factory = sqlite3.Row
        # SQLite does not enforce foreign keys unless asked, per connection.
        # Enable it now so future snapshot tables get real referential
        # integrity instead of silently-ignored constraints.
        g.db.execute("PRAGMA foreign_keys = ON")

    return g.db


def close_db(e=None):
    """Close the connection if one was opened for this context."""
    db = g.pop("db", None)

    if db is not None:
        db.close()


# Columnas agregadas DESPUÉS de que una tabla ya existía en producción.
# ``CREATE TABLE IF NOT EXISTS`` no altera tablas existentes, así que init_db
# las migra con ALTER TABLE (idempotente: sólo agrega las que falten). Las
# columnas nuevas nacen NULL (= sin dato, consistente con el guardrail NULL≠0).
_COLUMN_MIGRATIONS = {
    "account_snapshots": {
        "profile_views": "INTEGER",
        "website_clicks": "INTEGER",
    },
    "post_metrics": {
        "avg_watch_time_ms": "INTEGER",
        "video_view_total_time_ms": "INTEGER",
    },
}


# Forma válida de los identificadores/tipos de _COLUMN_MIGRATIONS. Guard
# defensivo: el dict es literal hoy, pero si un refactor futuro lo alimentara
# desde otra fuente, esto evita que llegue algo raro al SQL interpolado.
_IDENT_RE = re.compile(r"[a-z_][a-z0-9_]*\Z")


def _ensure_columns(db):
    """Agrega a las tablas existentes las columnas que falten (idempotente)."""
    for table, columns in _COLUMN_MIGRATIONS.items():
        if not _IDENT_RE.match(table):
            raise ValueError(f"Nombre de tabla inválido en migración: {table!r}")
        existing = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
        for name, decl in columns.items():
            if not _IDENT_RE.match(name) or decl != "INTEGER":
                raise ValueError(f"Columna/tipo inválido en migración: {name!r} {decl!r}")
            if name not in existing:
                # Identificadores fijos del dict de arriba, validados arriba.
                db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def init_db():
    """Create the database file and apply ``schema.sql`` (+ column migrations).

    The parent directory (e.g. ``instance/``) is created if missing. Re-running
    is safe: tables are IF NOT EXISTS and column migrations are idempotent.
    """
    db_path = current_app.config["DATABASE"]
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    db = get_db()
    with current_app.open_resource("schema.sql") as f:
        db.executescript(f.read().decode("utf8"))
    _ensure_columns(db)
    db.commit()


def upsert_user(fb_user_id, nombre, access_token_cifrado, token_expira_en):
    """Insert or update a user's profile and (encrypted) token.

    ``access_token_cifrado`` MUST already be encrypted by the caller; this
    function never sees a plaintext token.
    """
    db = get_db()
    db.execute(
        """
        INSERT INTO usuarias (fb_user_id, nombre, access_token_cifrado,
                              token_expira_en, actualizado_en)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(fb_user_id) DO UPDATE SET
            nombre = excluded.nombre,
            access_token_cifrado = excluded.access_token_cifrado,
            token_expira_en = excluded.token_expira_en,
            actualizado_en = CURRENT_TIMESTAMP
        """,
        (fb_user_id, nombre, access_token_cifrado, token_expira_en),
    )
    db.commit()
    row = db.execute(
        "SELECT id FROM usuarias WHERE fb_user_id = ?", (fb_user_id,)
    ).fetchone()
    return row["id"]


def update_user_token(user_id, access_token_cifrado, token_expira_en):
    """Actualiza el token (ya cifrado) y su vencimiento de una usuaria.

    Usado por el refresh: ``access_token_cifrado`` ya viene cifrado por el
    caller; esta función nunca ve el token en claro.
    """
    db = get_db()
    db.execute(
        """
        UPDATE usuarias
        SET access_token_cifrado = ?,
            token_expira_en = ?,
            actualizado_en = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (access_token_cifrado, token_expira_en, user_id),
    )
    db.commit()


@click.command("init-db")
@with_appcontext
def init_db_command():
    """Flask CLI command: ``flask init-db``."""
    init_db()
    click.echo(f"Initialized the database at {current_app.config['DATABASE']}.")


def init_app(app):
    """Register DB teardown and CLI command on the app."""
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
