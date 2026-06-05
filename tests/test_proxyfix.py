from urllib.parse import urlparse

from flask import request, url_for

from app import create_app


def test_proxyfix_honors_forwarded_proto_and_host(env):
    """Detrás de nginx, los headers X-Forwarded-* deben hacer que request.scheme/
    host reflejen la request pública HTTPS (cookies Secure, request.is_secure,
    url_for(_external=True))."""
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

    parsed = urlparse(resp.get_data(as_text=True))
    assert parsed.scheme == "https"
    assert parsed.netloc == "reportes.lahuelladelcaminante.de"


def test_scheme_is_http_without_forwarded_header(env):
    app = create_app()
    app.add_url_rule("/__scheme", "scheme", lambda: request.scheme)
    client = app.test_client()

    resp = client.get("/__scheme")

    assert resp.get_data(as_text=True) == "http"
