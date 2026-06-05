"""Application factory.

The factory pattern lets later specs register the ``auth`` and ``dashboard``
blueprints (and a snapshots cron) without rewriting startup.
"""

import os

from cryptography.fernet import Fernet
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from . import db
from . import insights
from .auth.routes import bp as auth_bp
from .config import Config
from .routes.dashboard import bp as dashboard_bp
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

    token_key = app.config.get("TOKEN_ENCRYPTION_KEY")
    if not token_key:
        raise RuntimeError(
            "TOKEN_ENCRYPTION_KEY is not set. Generate one with "
            '`python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"` and set it in the '
            "environment (or .env); there is no insecure default."
        )
    try:
        # Validate the key format at boot so a malformed key fails loudly here
        # instead of at the first token encryption in production.
        Fernet(token_key.encode() if isinstance(token_key, str) else token_key)
    except (ValueError, TypeError) as exc:
        raise RuntimeError(
            "TOKEN_ENCRYPTION_KEY is not a valid Fernet key. Generate one with "
            '`python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"`.'
        ) from exc

    # When DATABASE is not set in the environment, default to an absolute path
    # under instance_path so the resolved DB is stable regardless of the
    # process working directory (e.g. gunicorn under systemd).
    if not app.config.get("DATABASE"):
        app.config["DATABASE"] = os.path.join(app.instance_path, "reportes.db")

    # DB teardown + `flask init-db` command.
    db.init_app(app)

    # `flask fetch-insights` + `flask daily-snapshot` commands.
    insights.init_app(app)

    # `flask refresh-tokens` command.
    from .auth import refresh as auth_refresh

    auth_refresh.init_app(app)

    # Blueprints.
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)

    # Detrás de nginx (1 proxy): honrar X-Forwarded-Proto/Host para que la app
    # genere URLs https con el host público. Sin esto, el redirect_uri del OAuth
    # se construiría como http y rompería el login en producción. En producción
    # gunicorn escucha solo en 127.0.0.1 (solo nginx lo alcanza).
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    return app
