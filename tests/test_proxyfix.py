from flask import request, url_for

from app import create_app


def test_proxyfix_honors_forwarded_proto_and_host(env):
    """Detrás de nginx, los headers X-Forwarded-* deben hacer que la app genere
    URLs https con el host público (si no, el redirect_uri del OAuth se rompe)."""
    app = create_app()
    app.add_url_rule("/__proxytest", "proxytest", lambda: url_for("proxytest", _external=True))
    client = app.test_client()

    resp = client.get(
        "/__proxytest",
        headers={
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "reportes.lahuelladelcaminante.de",
        },
    )

    url = resp.get_data(as_text=True)
    assert url.startswith("https://reportes.lahuelladelcaminante.de")


def test_scheme_is_http_without_forwarded_header(env):
    app = create_app()
    app.add_url_rule("/__scheme", "scheme", lambda: request.scheme)
    client = app.test_client()

    resp = client.get("/__scheme")

    assert resp.get_data(as_text=True) == "http"
