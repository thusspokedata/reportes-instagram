"""WSGI entrypoint.

Used by gunicorn (``gunicorn wsgi:app``) and for local runs
(``python wsgi.py``). ``flask run`` discovers ``create_app`` automatically.
"""

from app import create_app

app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
