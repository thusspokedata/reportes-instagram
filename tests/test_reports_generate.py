import datetime as _dt

import pytest

from app.reports import generate
from app.reports.generate import (
    ReportError,
    build_report_input,
    generate_report_text,
    previous_month_label,
)


@pytest.mark.parametrize(
    "today,expected",
    [
        (_dt.date(2026, 6, 6), "2026-05"),
        (_dt.date(2026, 1, 15), "2025-12"),  # wrap de año (enero -> diciembre previo)
        (_dt.date(2026, 3, 1), "2026-02"),
        (_dt.date(2026, 12, 31), "2026-11"),
    ],
)
def test_previous_month_label(today, expected):
    assert previous_month_label(today) == expected


class _FakeBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeMessage:
    def __init__(self, text):
        self.content = [_FakeBlock(text)]


class _FakeMessages:
    def __init__(self, parent):
        self._parent = parent

    def create(self, **kwargs):
        self._parent.calls.append(kwargs)
        if self._parent.boom is not None:
            raise self._parent.boom
        return _FakeMessage(self._parent.reply)


class _FakeClient:
    """Cliente Anthropic de mentira: captura kwargs, no toca la red."""

    def __init__(self, reply="REPORTE DE PRUEBA", boom=None):
        self.reply = reply
        self.boom = boom
        self.calls = []
        self.messages = _FakeMessages(self)


def _snapshot(followers=147, reach=228):
    return {"follower_count": followers, "reach": reach}


def _post(media_id="M1", media_type="IMAGE", likes=5, comments=2, reach=10, timestamp=None):
    return {
        "media_id": media_id,
        "media_type": media_type,
        "timestamp": timestamp,
        "likes": likes,
        "comments": comments,
        "reach": reach,
    }


# --- armado de entrada (guardrails aplicados ANTES de Claude) -------------

def test_build_report_input_is_aggregated_and_has_no_ids():
    snapshot = _snapshot()
    posts = [
        _post("MEDIA_SECRET_1", reach=10),
        _post("MEDIA_SECRET_2", reach=30),
    ]
    payload = build_report_input(snapshot, posts, [])

    # Sólo métricas agregadas; nada de IDs internos ni tokens.
    flat = repr(payload)
    assert "MEDIA_SECRET" not in flat
    assert payload["seguidores"] == 147
    assert payload["cantidad_posts"] == 2
    assert payload["medianas"]["reach"] == 20  # mediana(10, 30)
    assert payload["muestra_suficiente"] is False  # 2 < 12


def test_build_report_input_preserves_null_not_zero():
    snapshot = {"follower_count": None, "reach": None}
    payload = build_report_input(snapshot, [], [])
    # NULL se preserva como None (nunca 0).
    assert payload["seguidores"] is None
    assert payload["reach_ultimo_dia"] is None


def test_build_report_input_handles_missing_snapshot():
    payload = build_report_input(None, [], [])
    assert payload["seguidores"] is None
    assert payload["demografia"] is None


# --- llamada al modelo ----------------------------------------------------

def test_generate_report_text_calls_model_and_returns_prose():
    client = _FakeClient(reply="La cuenta tuvo X de reach.")
    text = generate_report_text(
        {"seguidores": 147}, api_key="sk-test", model="claude-haiku-4-5", client=client
    )

    assert text == "La cuenta tuvo X de reach."
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["model"] == "claude-haiku-4-5"
    # El system prompt lleva los guardrails duros.
    system_text = " ".join(
        b["text"] for b in call["system"] if isinstance(b, dict)
    ).lower()
    # Los guardrails duros deben estar presentes en el prompt (que no se
    # degraden en silencio en el futuro).
    assert "descriptivo" in system_text
    assert "causa" in system_text  # sin causalidad
    assert "muestra_minima" in system_text  # gate de muestra
    assert "null" in system_text  # NULL = sin dato
    assert "referencia" in system_text  # demografía referencial
    # Los datos viajan en el mensaje del usuario.
    assert "147" in str(call["messages"])


def test_generate_report_text_builds_real_client(monkeypatch):
    # Ejercita el camino client=None: import perezoso + construcción del cliente
    # real, pasándole la api_key. Se mockea sólo el constructor del SDK.
    import anthropic

    captured = {}

    def fake_ctor(api_key=None):
        captured["api_key"] = api_key
        return _FakeClient(reply="hecho")

    monkeypatch.setattr(anthropic, "Anthropic", fake_ctor)

    text = generate_report_text(
        {"seguidores": 1}, api_key="sk-real", model="claude-haiku-4-5"
    )
    assert text == "hecho"
    assert captured["api_key"] == "sk-real"


def test_generate_report_text_requires_api_key():
    with pytest.raises(ReportError):
        generate_report_text({}, api_key=None, model="claude-haiku-4-5", client=_FakeClient())


def test_generate_report_text_degrades_on_api_error():
    client = _FakeClient(boom=RuntimeError("boom"))
    with pytest.raises(ReportError):
        generate_report_text({}, api_key="sk-test", model="claude-haiku-4-5", client=client)


def test_generate_report_text_raises_on_empty_reply():
    client = _FakeClient(reply="   ")
    with pytest.raises(ReportError):
        generate_report_text({}, api_key="sk-test", model="claude-haiku-4-5", client=client)


def test_generate_report_text_error_message_has_no_secret():
    # La degradación nunca debe filtrar la api_key ni el detalle del SDK.
    client = _FakeClient(boom=RuntimeError("api_key=sk-supersecret leaked"))
    with pytest.raises(ReportError) as excinfo:
        generate_report_text(
            {}, api_key="sk-supersecret", model="claude-haiku-4-5", client=client
        )
    assert "sk-supersecret" not in str(excinfo.value)


# --- orquestación end-to-end (DB) -----------------------------------------

def test_generate_and_save_report_persists(user_factory, inited_app):
    from app.db import get_db

    user = user_factory()
    client = _FakeClient(reply="Reporte mensual de la cuenta.")
    with inited_app.app_context():
        generate.generate_and_save_report(
            user,
            period_label="2026-05",
            api_key="sk-test",
            model="claude-haiku-4-5",
            client=client,
        )
        row = get_db().execute(
            "SELECT period_label, model, content FROM reports WHERE user_id = ?",
            (user["id"],),
        ).fetchone()

    assert row["period_label"] == "2026-05"
    assert row["model"] == "claude-haiku-4-5"
    assert row["content"] == "Reporte mensual de la cuenta."
