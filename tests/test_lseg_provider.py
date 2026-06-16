"""Tests del `LSEGWorkspaceProvider`.

Dos niveles:
  - Sin entorno LSEG (siempre corren): config sin app key, import del SDK ausente.
  - Con entorno LSEG (se SALTEAN si no hay LSEG_APP_KEY o Workspace no responde):
    smoke test real de is_available() + get_data(). Nunca rompe la suite/CI en
    máquinas sin Workspace.
"""
import os

import pytest

from core.infrastructure.lseg_provider import (
    APP_KEY_ENV,
    LSEGConfigError,
    LSEGWorkspaceProvider,
)


def test_app_key_missing_raises(monkeypatch):
    monkeypatch.delenv(APP_KEY_ENV, raising=False)
    with pytest.raises(LSEGConfigError):
        LSEGWorkspaceProvider._app_key()


def test_app_key_present(monkeypatch):
    monkeypatch.setenv(APP_KEY_ENV, "  test-key-123  ")
    assert LSEGWorkspaceProvider._app_key() == "test-key-123"


# ---- smoke test real: requiere app key + Workspace corriendo --------------
_HAS_KEY = bool((os.environ.get(APP_KEY_ENV) or "").strip())


@pytest.mark.skipif(not _HAS_KEY, reason="LSEG_APP_KEY no definido; smoke test omitido")
def test_live_connection_and_sample():
    provider = LSEGWorkspaceProvider()
    if not provider.is_available():
        pytest.skip("LSEG Workspace no disponible (cerrado / sin login).")
    df = provider.get_data("EUR=", ["BID", "ASK"])
    assert df is not None
    provider.close()
