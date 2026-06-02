"""SQLite connection handling, schema init, and the ``init-db`` CLI command.

The connection is cached on Flask's application context (``g``) so a single
request reuses one connection, and it is closed automatically on teardown.

``init_db`` creates the database file and applies ``schema.sql``.
"""

import os
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

    return g.db


def close_db(e=None):
    """Close the connection if one was opened for this context."""
    db = g.pop("db", None)

    if db is not None:
        db.close()


def init_db():
    """Create the database file and apply ``schema.sql``.

    The parent directory (e.g. ``instance/``) is created if missing.
    """
    db_path = current_app.config["DATABASE"]
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    db = get_db()
    with current_app.open_resource("schema.sql") as f:
        db.executescript(f.read().decode("utf8"))
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
