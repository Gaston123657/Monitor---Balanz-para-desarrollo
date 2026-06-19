"""Paso 1/3 del pipeline LSEG→ONs: vuelca a JSON las ONs sin datos suficientes.

Corre con el Python del monitor (py 3.12), porque el venv aislado .venv-lseg
no tiene openpyxl:

    py -3.12 scripts/dump_missing_ons.py

Escribe data/_ons_missing.json con las ONs de la hoja `ONs` que el calendario
de pagos NO puede estimar (les falta vto, cupón o frecuencia) — mismo criterio
que apps/web/server.py::_serve_ons_cashflows. Ese JSON lo consume
scripts/lseg_fetch_ons.py (paso 2, en .venv-lseg).

Pipeline completo:
  1) py -3.12 scripts/dump_missing_ons.py
  2) .venv-lseg\\Scripts\\python.exe scripts/lseg_fetch_ons.py   (Workspace abierto)
  3) py -3.12 scripts/apply_lseg_ons.py --apply
"""
import json
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
XLSX = ROOT / "data" / "instruments_master.xlsx"
OUT = ROOT / "data" / "_ons_missing.json"


def main():
    wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
    try:
        ws = wb["ONs"]
        rows = list(ws.iter_rows(values_only=True))
        hdr = [str(c).strip().lower() if c is not None else "" for c in rows[0]]
        ci = {k: hdr.index(k) for k in
              ("ticker", "isin", "fecha_vencimiento", "cupon anual %",
               "frecuencia pagos", "short_name", "sector")}
        out = []
        for r in rows[1:]:
            if not r or r[ci["ticker"]] is None:
                continue
            vto = r[ci["fecha_vencimiento"]]
            cup = r[ci["cupon anual %"]]
            frq = r[ci["frecuencia pagos"]]
            if (vto is None) or (cup in (None, "")) or (frq in (None, "", 0)):
                isin = r[ci["isin"]]
                nm = r[ci["short_name"]]
                sec = r[ci["sector"]]
                out.append({
                    "ticker": str(r[ci["ticker"]]).strip().upper(),
                    "isin_local": str(isin).strip() if isin else None,
                    "short_name": str(nm).strip() if nm else None,
                    "sector": str(sec).strip() if sec else None,
                })
    finally:
        wb.close()
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {len(out)} ONs sin datos -> {OUT}")


if __name__ == "__main__":
    main()
