import logging

import pytest

from app import create_app
from app.auth.crypto import encrypt_token
from app.insights import fetch
from app.insights.fetch import InsightsError, RateLimitError


@pytest.fixture
def app_ctx(env):
    app = create_app()
    ctx = app.app_context()
    ctx.push()
    yield app
    ctx.pop()


def _user(token="TESTTOKEN"):
    # access_token_cifrado must be real ciphertext (decrypt_token runs inside).
    return {"id": 1, "access_token_cifrado": encrypt_token(token)}


class FakeResp:
    def __init__(self, json_data, ok=True):
        self._json = json_data
        self.ok = ok

    def json(self):
        return self._json


# --- defensive fetch -----------------------------------------------------

def test_account_fetch_is_defensive(app_ctx, monkeypatch):
    def fake(path, params, token):
        if path == "me/accounts":
            return {"data": [{"instagram_business_account": {"id": "IG1"}}]}
        if params.get("metric") == "reach":
            return {"data": [{"name": "reach", "total_value": {"value": 50}}]}
        if params.get("metric") == "follower_count":
            raise InsightsError("metric deprecated/unavailable")
        raise AssertionError(path)

    monkeypatch.setattr(fetch, "_graph_get", fake)

    result = fetch.fetch_account_insights(_user())

    # reach succeeds, follower_count fails -> skipped, not fatal.
    assert result["reach"] == 50
    assert result["follower_count"] is None


def test_follower_count_empty_is_null(app_ctx, monkeypatch):
    def fake(path, params, token):
        if path == "me/accounts":
            return {"data": [{"instagram_business_account": {"id": "IG1"}}]}
        if params.get("metric") == "reach":
            return {"data": [{"name": "reach", "total_value": {"value": 50}}]}
        return {"data": []}  # <100 seguidores -> Meta no devuelve follower_count

    monkeypatch.setattr(fetch, "_graph_get", fake)

    result = fetch.fetch_account_insights(_user())

    assert result["reach"] == 50
    assert result["follower_count"] is None  # ausencia, no error, no 0


def test_rate_limit_propagates_not_swallowed(app_ctx, monkeypatch):
    def fake(path, params, token):
        if path == "me/accounts":
            return {"data": [{"instagram_business_account": {"id": "IG1"}}]}
        raise RateLimitError("rate limited")

    monkeypatch.setattr(fetch, "_graph_get", fake)

    with pytest.raises(RateLimitError):
        fetch.fetch_account_insights(_user())


def test_token_never_logged(app_ctx, monkeypatch, caplog):
    def fake(path, params, token):
        if path == "me/accounts":
            return {"data": [{"instagram_business_account": {"id": "IG1"}}]}
        raise InsightsError("boom")  # forces the warning log path

    monkeypatch.setattr(fetch, "_graph_get", fake)

    with caplog.at_level(logging.DEBUG):
        fetch.fetch_account_insights(_user("SUPERSECRETTOKEN123"))

    assert "SUPERSECRETTOKEN123" not in caplog.text


def test_media_list_and_media_insights(app_ctx, monkeypatch):
    def fake(path, params, token):
        if path == "me/accounts":
            return {"data": [{"instagram_business_account": {"id": "IG1"}}]}
        if path.endswith("/media"):
            return {
                "data": [
                    {
                        "id": "M1",
                        "media_type": "IMAGE",
                        "like_count": 5,
                        "comments_count": 2,
                        "permalink": "http://x",
                        "timestamp": "2026-06-01T00:00:00+0000",
                    }
                ]
            }
        if path.endswith("/insights"):
            return {"data": [{"name": "reach", "values": [{"value": 33}]}]}
        raise AssertionError(path)

    monkeypatch.setattr(fetch, "_graph_get", fake)

    media = fetch.fetch_media_list(_user())
    assert media[0]["id"] == "M1"
    assert media[0]["like_count"] == 5

    insights = fetch.fetch_media_insights(_user(), "M1", "IMAGE")
    assert insights["reach"] == 33


def test_normalize_post_maps_fields():
    media = {
        "id": "M1",
        "media_type": "IMAGE",
        "permalink": "http://x",
        "caption": "hola",
        "timestamp": "2026-06-01T00:00:00+0000",
        "like_count": 5,
        "comments_count": 2,
    }
    post = fetch.normalize_post(media, {"reach": 33})

    assert post["media_id"] == "M1"
    assert post["likes"] == 5
    assert post["comments"] == 2
    assert post["reach"] == 33


# --- low-level HTTP error handling ---------------------------------------

def test_graph_get_rate_limit_code(app_ctx, monkeypatch):
    monkeypatch.setattr(
        fetch.requests,
        "get",
        lambda *a, **k: FakeResp({"error": {"code": 4, "message": "rate"}}, ok=False),
    )
    with pytest.raises(RateLimitError):
        fetch._graph_get("IG1/insights", {"metric": "reach"}, "TOK")


def test_graph_get_error_does_not_leak_token(app_ctx, monkeypatch):
    monkeypatch.setattr(
        fetch.requests,
        "get",
        lambda *a, **k: FakeResp({"error": {"code": 100, "message": "bad"}}, ok=False),
    )
    with pytest.raises(InsightsError) as ei:
        fetch._graph_get("IG1/insights", {"metric": "reach"}, "SECRETTOKEN")
    assert "SECRETTOKEN" not in str(ei.value)
