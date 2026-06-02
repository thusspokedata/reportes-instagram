"""WSGI entrypoint.

Used by gunicorn (``gunicorn wsgi:app``) and for local runs
(``python wsgi.py``). ``flask run`` discovers ``create_app`` automatically.
"""

import os

from app import create_app

app = create_app()


if __name__ == "__main__":
    # Debug is OFF by default. Werkzeug's debugger exposes an interactive
    # console (RCE) and stack traces, so it must be opted into explicitly via
    # FLASK_DEBUG=1 for local development only — never in production.
    debug = os.environ.get("FLASK_DEBUG") == "1"
    app.run(host="127.0.0.1", port=5000, debug=debug)
