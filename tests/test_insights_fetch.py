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
        raise InsightsError("metric deprecated/unavailable")  # reach falla

    monkeypatch.setattr(fetch, "_graph_get", fake)

    result = fetch.fetch_account_insights(_user())

    # La métrica caída se saltea (None), no es fatal.
    assert result["reach"] is None


def test_account_insights_excludes_follower_count(app_ctx, monkeypatch):
    # follower_count NO se pide a insights (sale del perfil). El extractor de
    # la métrica de insights nunca debe terminar escribiendo follower_count.
    def fake(path, params, token):
        if path == "me/accounts":
            return {"data": [{"instagram_business_account": {"id": "IG1"}}]}
        assert params.get("metric") == "reach"  # sólo reach a insights
        return {"data": [{"name": "reach", "total_value": {"value": 50}}]}

    monkeypatch.setattr(fetch, "_graph_get", fake)

    result = fetch.fetch_account_insights(_user())

    assert result["reach"] == 50
    assert "follower_count" not in result


def test_account_fetch_skips_resolution_when_ig_id_passed(app_ctx, monkeypatch):
    def fake(path, params, token):
        if path == "me/accounts":
            raise AssertionError("no debería resolver: ig_id ya provisto")
        return {"data": [{"name": "reach", "total_value": {"value": 7}}]}

    monkeypatch.setattr(fetch, "_graph_get", fake)

    result = fetch.fetch_account_insights(_user(), ig_id="IG1")

    assert result["reach"] == 7


def test_resolve_ig_account_returns_id(app_ctx, monkeypatch):
    monkeypatch.setattr(
        fetch,
        "_graph_get",
        lambda path, params, token: {
            "data": [{"instagram_business_account": {"id": "IG999"}}]
        },
    )
    assert fetch.resolve_ig_account(_user()) == "IG999"


def test_fetch_profile_reads_followers_and_media_count(app_ctx, monkeypatch):
    def fake(path, params, token):
        if path == "me/accounts":
            return {"data": [{"instagram_business_account": {"id": "IG1"}}]}
        # Perfil: GET /{ig_id}?fields=followers_count,media_count,username
        assert "followers_count" in params.get("fields", "")
        return {"followers_count": 147, "media_count": 13, "username": "lahuella"}

    monkeypatch.setattr(fetch, "_graph_get", fake)

    profile = fetch.fetch_profile(_user())

    assert profile["followers_count"] == 147
    assert profile["media_count"] == 13
    assert profile["username"] == "lahuella"


def test_fetch_profile_missing_followers_is_none(app_ctx, monkeypatch):
    def fake(path, params, token):
        if path == "me/accounts":
            return {"data": [{"instagram_business_account": {"id": "IG1"}}]}
        return {"username": "lahuella"}  # sin followers_count

    monkeypatch.setattr(fetch, "_graph_get", fake)

    profile = fetch.fetch_profile(_user())

    # Ausencia de dato = None, NUNCA 0.
    assert profile["followers_count"] is None


def test_fetch_profile_defensive_on_error(app_ctx, monkeypatch):
    def fake(path, params, token):
        if path == "me/accounts":
            return {"data": [{"instagram_business_account": {"id": "IG1"}}]}
        raise InsightsError("perfil no disponible")

    monkeypatch.setattr(fetch, "_graph_get", fake)

    profile = fetch.fetch_profile(_user())

    # No crashea; followers queda None (no 0).
    assert profile.get("followers_count") is None


def test_media_list_paginates_following_cursor(app_ctx, monkeypatch):
    def fake(path, params, token):
        if path == "me/accounts":
            return {"data": [{"instagram_business_account": {"id": "IG1"}}]}
        # Página 1: trae cursor `after`; página 2: sin `next` -> corta.
        if params.get("after") is None:
            return {
                "data": [{"id": "M1"}, {"id": "M2"}],
                "paging": {"next": "http://next", "cursors": {"after": "CUR2"}},
            }
        assert params.get("after") == "CUR2"
        return {"data": [{"id": "M3"}], "paging": {"cursors": {"after": "CUR3"}}}

    monkeypatch.setattr(fetch, "_graph_get", fake)

    media = fetch.fetch_media_list(_user(), ig_id="IG1")

    ids = [m["id"] for m in media]
    assert ids == ["M1", "M2", "M3"]  # trae las dos páginas, sin duplicar


def test_media_list_parses_after_from_next_url_when_cursor_missing(app_ctx, monkeypatch):
    # Meta a veces da paging.next (URL) sin exponer cursors.after.
    def fake(path, params, token):
        if path == "me/accounts":
            return {"data": [{"instagram_business_account": {"id": "IG1"}}]}
        if params.get("after") is None:
            return {
                "data": [{"id": "M1"}],
                "paging": {"next": "https://graph.facebook.com/v23.0/IG1/media?after=CURX"},
            }
        assert params.get("after") == "CURX"
        return {"data": [{"id": "M2"}], "paging": {}}

    monkeypatch.setattr(fetch, "_graph_get", fake)

    media = fetch.fetch_media_list(_user(), ig_id="IG1")

    assert [m["id"] for m in media] == ["M1", "M2"]


def test_media_list_respects_page_cap(app_ctx, monkeypatch):
    counter = {"n": 0}

    def fake(path, params, token):
        if path == "me/accounts":
            return {"data": [{"instagram_business_account": {"id": "IG1"}}]}
        counter["n"] += 1
        n = counter["n"]
        # Siempre hay "más" -> sólo el tope debe cortar el loop.
        return {
            "data": [{"id": f"M{n}"}],
            "paging": {"next": "http://n", "cursors": {"after": f"C{n}"}},
        }

    monkeypatch.setattr(fetch, "_graph_get", fake)

    media = fetch.fetch_media_list(_user(), ig_id="IG1")

    # Corta en el tope, no entra en loop infinito.
    assert len(media) == fetch._MAX_MEDIA_PAGES


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

def test_extract_metric_value_tolerates_garbage(app_ctx):
    # Respuestas con formas inesperadas -> None, nunca crash.
    assert fetch._extract_metric_value({"data": "garbage"}) is None
    assert fetch._extract_metric_value({"data": [42]}) is None
    assert fetch._extract_metric_value("nope") is None
    assert fetch._extract_metric_value({}) is None
    assert fetch._extract_metric_value({"data": [{"total_value": None}]}) is None


def test_account_fetch_defensive_against_malformed_response(app_ctx, monkeypatch):
    def fake(path, params, token):
        if path == "me/accounts":
            return {"data": [{"instagram_business_account": {"id": "IG1"}}]}
        return {"data": "garbage"}  # forma malformada para reach

    monkeypatch.setattr(fetch, "_graph_get", fake)

    result = fetch.fetch_account_insights(_user())

    # La métrica malformada se saltea (None), no crashea.
    assert result["reach"] is None


def test_normalize_post_tolerates_non_dict(app_ctx):
    assert fetch.normalize_post(None)["media_id"] is None
    assert fetch.normalize_post("garbage")["likes"] is None


# --- demografía ----------------------------------------------------------

def test_extract_demographics_parses_real_shape(app_ctx):
    data = {
        "data": [
            {
                "name": "follower_demographics",
                "total_value": {
                    "breakdowns": [
                        {
                            "dimension_keys": ["gender"],
                            "results": [
                                {"dimension_values": ["F"], "value": 39},
                                {"dimension_values": ["M"], "value": 36},
                            ],
                        }
                    ]
                },
            }
        ]
    }
    assert fetch._extract_demographics(data) == {"F": 39, "M": 36}


def test_extract_demographics_tolerates_garbage(app_ctx):
    assert fetch._extract_demographics({}) == {}
    assert fetch._extract_demographics({"data": []}) == {}
    assert fetch._extract_demographics("nope") == {}
    assert fetch._extract_demographics({"data": [{"total_value": {}}]}) == {}


def test_fetch_demographics_is_defensive(app_ctx, monkeypatch):
    def fake(path, params, token):
        if path == "me/accounts":
            return {"data": [{"instagram_business_account": {"id": "IG1"}}]}
        bd = params.get("breakdown")
        if bd == "gender":
            return {
                "data": [
                    {"total_value": {"breakdowns": [{"results": [
                        {"dimension_values": ["F"], "value": 39}
                    ]}]}}
                ]
            }
        if bd == "city":
            raise InsightsError("corte no disponible")
        return {"data": []}  # age/country vacíos

    monkeypatch.setattr(fetch, "_graph_get", fake)

    res = fetch.fetch_demographics(_user(), ig_id="IG1")

    assert res["gender"] == {"F": 39}
    assert res["city"] == {}  # un corte caído no rompe los demás
    assert res["age"] == {} and res["country"] == {}


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
