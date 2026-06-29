"""Paso 1/3 (full): vuelca a JSON las ONs con CUALQUIER campo estructural faltante.

Corre con el Python del monitor (py 3.12):

    py -3.12 scripts/dump_incomplete_ons.py

A diferencia de dump_missing_ons.py (que solo miraba vto/cupón/frecuencia para
el calendario), este vuelca toda ON a la que le falte alguno de los campos que
queremos completar: sector, legislacion, base calculo, isin, fecha_emision,
fecha_vencimiento, cupón, frecuencia, tipo amortizacion. Incluye los valores
actuales de cada fila para que el paso de apply NO pise lo ya cargado.

Salida: data/_ons_incomplete.json  → lo consume scripts/lseg_fetch_ons_full.py
"""
import json
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
XLSX = ROOT / "data" / "instruments_master.xlsx"
OUT = ROOT / "data" / "_ons_incomplete.json"

# Campos que consideramos "estructurales": si falta alguno -> la ON es incompleta.
REQUIRED = ("sector", "legislacion", "base calculo", "isin", "fecha_emision",
            "fecha_vencimiento", "cupon anual %", "frecuencia pagos",
            "tipo amortizacion")

ALL_COLS = ("ticker", "short_name", "tipo", "sector", "legislacion", "isin",
            "fecha_emision", "fecha_vencimiento", "cupon anual %",
            "frecuencia pagos", "base calculo", "tipo amortizacion",
            "amort inicio", "amort cantidad", "amort frec", "amort %",
            "amort cant1", "amort %2")


def _val(v):
    if v is None:
        return None
    if hasattr(v, "isoformat"):
        return v.isoformat()[:10]
    s = str(v).strip()
    return s if s and s.lower() not in ("nan", "none") else None


def main():
    wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
    try:
        ws = wb["ONs"]
        rows = list(ws.iter_rows(values_only=True))
        hdr = [str(c).strip().lower() if c is not None else "" for c in rows[0]]
        idx = {c: hdr.index(c) for c in ALL_COLS}
        out = []
        for r in rows[1:]:
            if not r or r[idx["ticker"]] is None:
                continue
            cur = {c: _val(r[idx[c]]) for c in ALL_COLS}
            missing = [c for c in REQUIRED if cur.get(c) is None]
            if not missing:
                continue
            out.append({
                "ticker": cur["ticker"].upper(),
                "isin_local": cur["isin"],
                "current": cur,
                "missing": missing,
            })
    finally:
        wb.close()
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {len(out)} ONs incompletas -> {OUT}")
    n_empty = sum(1 for o in out if not o["current"]["isin"])
    print(f"  de las cuales {n_empty} sin ISIN (resolver via RIC search)")


if __name__ == "__main__":
    main()
