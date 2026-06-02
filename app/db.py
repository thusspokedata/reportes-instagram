"""SQLite connection handling and the ``init-db`` CLI command.

The connection is cached on Flask's application context (``g``) so a single
request reuses one connection, and it is closed automatically on teardown.

No tables are defined yet: ``init_db`` only ensures the database file exists.
The data model is defined in a later spec by the architecture agent.
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
    """Create the database file.

    The parent directory (e.g. ``instance/``) is created if missing. No schema
    is applied yet; opening the connection is enough to create the file.
    """
    db_path = current_app.config["DATABASE"]
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    db = get_db()
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
