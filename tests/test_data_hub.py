"""Tests del DataHub (facade de fuentes de datos). Sin red: usa fakes en memoria.

Verifica:
- Delegación de precios al provider Data912 (Pilar 4) + métodos extra vía __getattr__.
- Routing de capacidades: gateo por is_available, primera respuesta no vacía gana,
  errores y faltantes degradan a default (None/{}).
"""
from datetime import date

import pytest

from core.infrastructure.data_hub import DataHub


# --------------------------------------------------------------------------- fakes
class FakePriceProvider:
    """Imita a Data912MarketDataProvider (interfaz + métodos extra usados por server)."""
    def __init__(self):
        self.invalidated = 0
        self.snap_calls = []

    def fetch_snapshots(self, tickers):
        self.snap_calls.append(list(tickers))
        return {t: f"snap:{t}" for t in tickers}

    def fetch_historical_prices(self, ticker, days):
        return {date(2026, 1, 1): 100.0}

    def fetch_stock_history(self, ticker):
        return {"ticker": ticker, "ohlc": []}

    def invalidate_cache(self):
        self.invalidated += 1


class FakeCapProvider:
    """Provider complementario configurable (disponibilidad + respuestas)."""
    def __init__(self, name, available=True, depth=None, refdata=None, raises=False):
        self._name = name
        self._available = available
        self._depth = depth
        self._refdata = refdata
        self._raises = raises
        self.depth_calls = []

    def is_available(self):
        return self._available

    def fetch_depth(self, ticker):
        self.depth_calls.append(ticker)
        if self._raises:
            raise RuntimeError("boom")
        return self._depth

    def fetch_reference_data(self, tickers):
        return self._refdata


# --------------------------------------------------------------- delegación precios
def test_fetch_snapshots_delega_a_precios():
    px = FakePriceProvider()
    hub = DataHub(price_provider=px)
    out = hub.fetch_snapshots(["AL30", "GD30"])
    assert out == {"AL30": "snap:AL30", "GD30": "snap:GD30"}
    assert px.snap_calls == [["AL30", "GD30"]]


def test_fetch_historical_delega_a_precios():
    hub = DataHub(price_provider=FakePriceProvider())
    assert hub.fetch_historical_prices("AL30", 365) == {date(2026, 1, 1): 100.0}


def test_getattr_delega_metodos_extra():
    px = FakePriceProvider()
    hub = DataHub(price_provider=px)
    # fetch_stock_history e invalidate_cache no están en DataHub → __getattr__
    assert hub.fetch_stock_history("GGAL") == {"ticker": "GGAL", "ohlc": []}
    hub.invalidate_cache()
    assert px.invalidated == 1


def test_getattr_atributo_inexistente_lanza():
    hub = DataHub(price_provider=FakePriceProvider())
    with pytest.raises(AttributeError):
        _ = hub.metodo_que_no_existe


# ----------------------------------------------------------------- routing capacidades
def test_capacidad_sin_providers_degrada():
    hub = DataHub(price_provider=FakePriceProvider())
    assert hub.fetch_depth("AL30") is None
    assert hub.fetch_reference_data(["AL30"]) == {}
    assert hub.fetch_indices() == {}


def test_capacidad_servida_por_provider_disponible():
    cap = FakeCapProvider("byma", available=True, depth={"bid": 1, "ask": 2})
    hub = DataHub(price_provider=FakePriceProvider(), providers=[cap])
    assert hub.fetch_depth("AL30") == {"bid": 1, "ask": 2}
    assert cap.depth_calls == ["AL30"]


def test_provider_no_disponible_se_saltea():
    cap = FakeCapProvider("byma", available=False, depth={"bid": 1})
    hub = DataHub(price_provider=FakePriceProvider(), providers=[cap])
    assert hub.fetch_depth("AL30") is None
    assert cap.depth_calls == []  # ni se llamó al método


def test_primera_respuesta_no_vacia_gana():
    vacio = FakeCapProvider("a", available=True, depth=None)
    lleno = FakeCapProvider("b", available=True, depth={"bid": 9})
    hub = DataHub(price_provider=FakePriceProvider(), providers=[vacio, lleno])
    assert hub.fetch_depth("AL30") == {"bid": 9}
    assert vacio.depth_calls == ["AL30"] and lleno.depth_calls == ["AL30"]


def test_error_en_provider_degrada():
    cap = FakeCapProvider("byma", available=True, raises=True)
    hub = DataHub(price_provider=FakePriceProvider(), providers=[cap])
    assert hub.fetch_depth("AL30") is None  # excepción capturada → default


def test_provider_sin_capacidad_se_saltea():
    # FakePriceProvider no tiene fetch_depth → no debe romper si se registra como complementario
    sin_cap = FakePriceProvider()
    hub = DataHub(price_provider=FakePriceProvider(), providers=[sin_cap])
    assert hub.fetch_depth("AL30") is None


def test_available_sources():
    a = FakeCapProvider("a", available=True)
    b = FakeCapProvider("b", available=False)
    hub = DataHub(price_provider=FakePriceProvider(), providers=[a, b])
    assert hub.available_sources() == ["FakeCapProvider"]  # solo el disponible
