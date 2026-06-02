"""Application factory.

The factory pattern lets later specs register the ``auth`` and ``dashboard``
blueprints (and a snapshots cron) without rewriting startup.
"""

import os

from flask import Flask

from . import db
from .auth.routes import bp as auth_bp
from .config import Config
from .routes.main import bp as main_bp


def create_app():
    """Create and configure the Flask application."""
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config())

    if not app.config.get("SECRET_KEY"):
        raise RuntimeError(
            "SECRET_KEY is not set. Define it in the environment (or .env) "
            "before starting the app; there is no insecure default."
        )

    if not app.config.get("TOKEN_ENCRYPTION_KEY"):
        raise RuntimeError(
            "TOKEN_ENCRYPTION_KEY is not set. Generate one with "
            '`python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"` and set it in the '
            "environment (or .env); there is no insecure default."
        )

    # When DATABASE is not set in the environment, default to an absolute path
    # under instance_path so the resolved DB is stable regardless of the
    # process working directory (e.g. gunicorn under systemd).
    if not app.config.get("DATABASE"):
        app.config["DATABASE"] = os.path.join(app.instance_path, "reportes.db")

    # DB teardown + `flask init-db` command.
    db.init_app(app)

    # Blueprints. Add `dashboard` here in a later spec.
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)

    return app
