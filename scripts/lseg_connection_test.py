"""Smoke test de conexión a LSEG Workspace (Eikon Data API).

Verifica end-to-end que la Desktop Session funciona y trae un dato.

PRE-REQUISITOS:
  1. venv AISLADO con lseg-data (lseg-data exige pandas<3, choca con el monitor):
       python -m venv .venv-lseg
       .venv-lseg\\Scripts\\python.exe -m pip install -r requirements-lseg.txt
  2. .env con LSEG_APP_KEY=<tu app key>   (ver .env.example)
  3. LSEG Workspace Desktop ABIERTO y LOGUEADO en esta misma máquina.

Uso (con el python del venv aislado, NO el del sistema):
       .venv-lseg\\Scripts\\python.exe scripts/lseg_connection_test.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Importa settings para que cargue .env -> os.environ (config/settings.py::_load_dotenv).
import config.settings  # noqa: F401
from core.infrastructure.lseg_provider import (
    APP_KEY_ENV,
    LSEGError,
    LSEGWorkspaceProvider,
)

# RICs de muestra: FX spot (siempre permisado) + una acción US.
SAMPLES = [
    ("EUR=", ["BID", "ASK"]),
    ("AAPL.O", ["TR.PriceClose"]),
]


def _print_header():
    print("=" * 64)
    print(" LSEG Workspace — prueba de conexión (Desktop Session)")
    print("=" * 64)


def main() -> int:
    _print_header()

    key = (os.environ.get(APP_KEY_ENV) or "").strip()
    if key:
        masked = f"{key[:6]}…{key[-4:]}" if len(key) > 10 else "(corta)"
        print(f"[1/3] {APP_KEY_ENV}: presente ({masked})")
    else:
        print(f"[1/3] {APP_KEY_ENV}: AUSENTE")
        print("\nFAIL: definí LSEG_APP_KEY en .env (ver .env.example).")
        return 1

    provider = LSEGWorkspaceProvider()

    print("[2/3] Abriendo Desktop Session (handshake localhost:9000)…")
    try:
        provider.open()
        print("      OK — sesión abierta.")
    except LSEGError as e:
        print(f"\nFAIL: {e}")
        print("\n¿Está LSEG Workspace abierto y logueado en esta máquina?")
        return 1

    print("[3/3] Trayendo datos de muestra…")
    ok = False
    for universe, fields in SAMPLES:
        try:
            df = provider.get_data(universe, fields)
            print(f"\n--- {universe} {fields} ---")
            print(df.to_string() if hasattr(df, "to_string") else df)
            if df is not None and getattr(df, "empty", True) is False:
                ok = True
        except Exception as e:  # noqa: BLE001 — reportar cualquier fallo del SDK
            print(f"\n  {universe}: error -> {type(e).__name__}: {e}")

    provider.close()

    print("\n" + "=" * 64)
    if ok:
        print(" OK — conexión a LSEG Workspace verificada.")
        return 0
    print(" FAIL — la sesión abrió pero no se obtuvieron datos.")
    print(" Revisá permisos del producto (Eikon Data API) sobre estos RICs.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
