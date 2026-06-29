"""Tests del BYMADATAProvider. Sin red ni Excel: mockea requests/http_get_json.

Cubre: resolución de modo, is_available() por modo, caché de token (modo rest),
ruteo de capacidades y degradación a None/{} cuando no está disponible.
"""
import core.infrastructure._http as _http
from core.infrastructure import bymadata_provider as bp
from core.infrastructure.bymadata_provider import BYMADATAProvider

import pytest


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    # Limpia estado de clase + env entre tests.
    BYMADATAProvider._token = None
    BYMADATAProvider._xl_book = None
    for k in ("BYMADATA_MODE", "BYMADATA_CLIENT_ID", "BYMADATA_CLIENT_SECRET",
              "BYMADATA_WORKBOOK", "BYMADATA_BASE_URL", "BYMADATA_TOKEN_URL"):
        monkeypatch.delenv(k, raising=False)
    yield


# ----------------------------------------------------------------- disponibilidad
def test_deshabilitado_por_default():
    assert BYMADATAProvider().is_available() is False


def test_rest_sin_credenciales_no_disponible(monkeypatch):
    monkeypatch.setenv("BYMADATA_MODE", "rest")
    assert BYMADATAProvider().is_available() is False


def test_rest_con_credenciales_disponible(monkeypatch):
    monkeypatch.setenv("BYMADATA_MODE", "rest")
    monkeypatch.setenv("BYMADATA_CLIENT_ID", "cid")
    monkeypatch.setenv("BYMADATA_CLIENT_SECRET", "sec")
    assert BYMADATAProvider().is_available() is True


def test_excel_sin_workbook_no_disponible(monkeypatch):
    monkeypatch.setenv("BYMADATA_MODE", "excel")
    assert BYMADATAProvider().is_available() is False


def test_modo_desconocido_no_disponible(monkeypatch):
    monkeypatch.setenv("BYMADATA_MODE", "foobar")
    assert BYMADATAProvider().is_available() is False


# ------------------------------------------------------------- degradación capacidades
def test_capacidades_degradan_si_no_disponible():
    p = BYMADATAProvider()  # deshabilitado
    assert p.fetch_depth("AL30") is None
    assert p.fetch_reference_data(["AL30"]) == {}
    assert p.fetch_indices() == {}
    assert p.fetch_turnover() == {}
    assert p.fetch_eod() == {}


def test_excel_disponible_pero_sin_mapear_degrada(monkeypatch):
    # Simula modo excel "disponible" (workbook + xlwings) sin tocar Excel real:
    monkeypatch.setenv("BYMADATA_MODE", "excel")
    monkeypatch.setenv("BYMADATA_WORKBOOK", "C:/fake/bridge.xlsx")
    monkeypatch.setattr(BYMADATAProvider, "_import_xlwings", staticmethod(lambda: object()))
    p = BYMADATAProvider()
    assert p.is_available() is True
    # Aún sin mapear capacidad→UDF → degrada a default.
    assert p.fetch_indices() == {}
    assert p.fetch_depth("AL30") is None


# --------------------------------------------------------------------- modo rest
class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_token_y_capacidad_rest(monkeypatch):
    monkeypatch.setenv("BYMADATA_MODE", "rest")
    monkeypatch.setenv("BYMADATA_CLIENT_ID", "cid")
    monkeypatch.setenv("BYMADATA_CLIENT_SECRET", "sec")

    posts = []

    def fake_post(url, data=None, auth=None, timeout=None, verify=None):
        posts.append((url, data, auth))
        return _FakeResp({"access_token": "TKN", "expires_in": 3600})

    import requests
    monkeypatch.setattr(requests, "post", fake_post)

    gets = []

    def fake_get_json(url, params=None, headers=None, **kw):
        gets.append((url, params, headers))
        return {"items": [{"ticker": "AL30", "isin": "X"}]}

    monkeypatch.setattr(_http, "http_get_json", fake_get_json)

    p = BYMADATAProvider()
    out = p.fetch_reference_data(["AL30", "GD30"])
    assert out == {"items": [{"ticker": "AL30", "isin": "X"}]}
    # token pedido una vez, con grant client_credentials y auth (cid, sec)
    assert len(posts) == 1
    assert posts[0][1] == {"grant_type": "client_credentials"}
    assert posts[0][2] == ("cid", "sec")
    # request autenticado con Bearer
    assert gets[0][2]["Authorization"] == "Bearer TKN"


def test_token_se_cachea(monkeypatch):
    monkeypatch.setenv("BYMADATA_MODE", "rest")
    monkeypatch.setenv("BYMADATA_CLIENT_ID", "cid")
    monkeypatch.setenv("BYMADATA_CLIENT_SECRET", "sec")

    calls = []

    def fake_post(url, data=None, auth=None, timeout=None, verify=None):
        calls.append(url)
        return _FakeResp({"access_token": "TKN", "expires_in": 3600})

    import requests
    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(_http, "http_get_json", lambda *a, **k: {"items": []})

    p = BYMADATAProvider()
    p.fetch_indices()
    p.fetch_turnover()
    assert len(calls) == 1  # token reutilizado entre llamadas
