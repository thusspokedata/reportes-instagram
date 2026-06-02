"""Application configuration, loaded entirely from environment variables.

Secrets (app secret, tokens, session key) never live in the repo. In
development they are read from a local ``.env`` file via python-dotenv; in
production they come from the real process environment.
"""

import os

from dotenv import load_dotenv

# Load a local .env in development. In production the variables are already
# present in the environment and this is a no-op.
load_dotenv()


class Config:
    """Reads configuration from the environment on instantiation.

    Reading in ``__init__`` (rather than at class-definition time) means the
    environment is consulted fresh every time the app factory runs, which keeps
    the factory testable.
    """

    def __init__(self):
        self.SECRET_KEY = os.environ.get("SECRET_KEY")
        self.FACEBOOK_APP_ID = os.environ.get("FACEBOOK_APP_ID")
        self.FACEBOOK_APP_SECRET = os.environ.get("FACEBOOK_APP_SECRET")
        self.REDIRECT_URI = os.environ.get("REDIRECT_URI")
        self.GRAPH_API_VERSION = os.environ.get("GRAPH_API_VERSION")
        # If unset, the factory derives an absolute default from the app's
        # instance_path (see create_app). A relative default would be resolved
        # against the process CWD, which is brittle under gunicorn/systemd.
        self.DATABASE = os.environ.get("DATABASE")

        # Key used to encrypt access tokens at rest (Fernet). Required: the
        # factory refuses to start without it (see create_app).
        self.TOKEN_ENCRYPTION_KEY = os.environ.get("TOKEN_ENCRYPTION_KEY")

        # Session cookie hardening.
        self.SESSION_COOKIE_HTTPONLY = True
        self.SESSION_COOKIE_SAMESITE = "Lax"
        # Secure cookies require HTTPS, which breaks local http development.
        # Default True (production); set SESSION_COOKIE_SECURE=False locally.
        self.SESSION_COOKIE_SECURE = (
            os.environ.get("SESSION_COOKIE_SECURE", "True").lower() != "false"
        )

        # Meta OAuth / Graph API hosts. The API *version* is never hardcoded;
        # it always comes from GRAPH_API_VERSION above.
        self.FACEBOOK_OAUTH_DIALOG_BASE = "https://www.facebook.com"
        self.GRAPH_API_BASE = "https://graph.facebook.com"
