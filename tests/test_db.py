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


def test_init_db_cli_command(env):
    app = create_app()

    runner = app.test_cli_runner()
    result = runner.invoke(args=["init-db"])

    assert result.exit_code == 0
    assert env["db_path"].exists()
