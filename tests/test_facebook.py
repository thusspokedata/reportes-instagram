from urllib.parse import parse_qs, urlparse

import pytest
import requests

from app import create_app
from app.auth import facebook
from app.auth.facebook import OAuthError


class FakeResp:
    def __init__(self, json_data, ok=True):
        self._json = json_data
        self.ok = ok

    def json(self):
        if isinstance(self._json, Exception):
            raise self._json
        return self._json


@pytest.fixture
def app_ctx(env):
    app = create_app()
    ctx = app.app_context()
    ctx.push()
    yield app
    ctx.pop()


def test_build_login_url_uses_version_and_scopes(app_ctx):
    url = facebook.build_login_url("st")

    assert "/v23.0/dialog/oauth" in url
    assert "instagram_manage_insights" in url
    assert "response_type=code" in url
    assert "state=st" in url


def test_login_url_requests_exact_meta_scopes(app_ctx):
    """The authorization URL must request exactly the 5 approved scopes."""
    url = facebook.build_login_url("st")
    query = parse_qs(urlparse(url).query)
    requested = query["scope"][0].split(",")

    # Length check catches accidental duplicate scopes that a set would hide.
    assert len(requested) == 5
    assert set(requested) == {
        "instagram_basic",
        "instagram_manage_insights",
        "pages_show_list",
        "pages_read_engagement",
        "business_management",
    }


def test_login_url_excludes_messaging_publishing_ads_scopes(app_ctx):
    url = facebook.build_login_url("st")
    query = parse_qs(urlparse(url).query)
    requested = set(query["scope"][0].split(","))

    for forbidden in (
        "instagram_manage_messages",
        "instagram_content_publishing",
        "ads_management",
    ):
        assert forbidden not in requested


def test_get_user_profile_parses_id_and_name(app_ctx, monkeypatch):
    monkeypatch.setattr(
        facebook.requests, "get", lambda *a, **k: FakeResp({"id": "42", "name": "Ada"})
    )

    assert facebook.get_user_profile("tok") == {"id": "42", "name": "Ada"}


def test_get_user_profile_missing_id_raises(app_ctx, monkeypatch):
    monkeypatch.setattr(
        facebook.requests, "get", lambda *a, **k: FakeResp({"name": "Ada"})
    )

    with pytest.raises(OAuthError):
        facebook.get_user_profile("tok")


def test_error_body_raises_without_leaking_secrets(app_ctx, monkeypatch):
    monkeypatch.setattr(
        facebook.requests,
        "get",
        lambda *a, **k: FakeResp({"error": {"message": "secret detail xyz"}}, ok=False),
    )

    with pytest.raises(OAuthError) as ei:
        facebook.exchange_code_for_token("the-code")

    msg = str(ei.value)
    assert "secret detail xyz" not in msg
    assert "the-code" not in msg


def test_invalid_json_raises_oautherror(app_ctx, monkeypatch):
    monkeypatch.setattr(
        facebook.requests, "get", lambda *a, **k: FakeResp(ValueError("no json"))
    )

    with pytest.raises(OAuthError):
        facebook.exchange_code_for_token("the-code")


def test_timeout_raises_oautherror(app_ctx, monkeypatch):
    def boom(*a, **k):
        raise requests.Timeout("network down")

    monkeypatch.setattr(facebook.requests, "get", boom)

    with pytest.raises(OAuthError) as ei:
        facebook.exchange_code_for_token("the-code")

    assert "the-code" not in str(ei.value)


def test_long_lived_returns_token_and_expiry(app_ctx, monkeypatch):
    monkeypatch.setattr(
        facebook.requests,
        "get",
        lambda *a, **k: FakeResp({"access_token": "long", "expires_in": 5184000}),
    )

    token, expires_in = facebook.exchange_for_long_lived_token("short")

    assert token == "long"
    assert expires_in == 5184000
