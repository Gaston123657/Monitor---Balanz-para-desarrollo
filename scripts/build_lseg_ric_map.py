"""Genera el mapa semilla ticker->panel para el backfill histórico de LSEG.

Corre en el ENTORNO PRINCIPAL (py 3.12):

    py -3.12 scripts/build_lseg_ric_map.py

Escribe data/history/lseg_ric_map.json con una entrada por bono de los paneles,
en el formato que consume scripts/lseg_fetch_history.py:

    { "AL30D": {"panel": "bonares", "isin_local": "US040114HS26"}, ... }

NO resuelve RICs acá (eso necesita LSEG y se hace en el venv aislado): el fetch
completa "universe_id" vía búsqueda GovCorp si falta. Si el instrumento tiene ISIN
en el master, lo incluimos como `isin_local` (resolución más confiable).

Replica la asignación panel<-tipos de `bond_panels` (server.py), incluyendo los
filtros MEP (sufijo D) para bonares/bopreales/ons y el split de ONs por legislación.

DUAL (DUAL/DUAL_CER_TAMAR) se OMITEN a propósito: en el panel live no aparecen con
su ticker sino como filas sintéticas revaluadas (_TAM en TAMAR, _TF en tasa fija),
así que mapearlos 1:1 confundiría la curva. Quedan para una segunda iteración.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apps.cli.monitors._common import get_repository
from core.domain.instrument_groups import (
    BOPREALES, CER, DOLAR_LINKED, ONS, SOBERANOS, TAMAR, TASA_FIJA,
)

OUT = ROOT / "data" / "history" / "lseg_ric_map.json"
ONS_CACHE = ROOT / "data" / "lseg_ons_cache.json"


def _ons_resolved_universe():
    """{ticker -> universe_id} ya resueltos en el cache de ONs (trabajo previo).
    Evita re-resolver vía búsqueda en el fetch."""
    if not ONS_CACHE.is_file():
        return {}
    try:
        rows = json.loads(ONS_CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for r in rows:
        tk = (r.get("ticker") or "").strip()
        uid = r.get("universe_id")
        if tk and uid and r.get("status") in ("ok", "resolved"):
            out[tk] = uid
    return out

# panel -> (tipos, requiere_sufijo_D, legislacion_filter)
PANELS = [
    ("bonares",      set(SOBERANOS),    True,  None),
    ("bopreales",    set(BOPREALES),    True,  None),
    ("cer",          set(CER),          False, None),
    ("tasa_fija",    set(TASA_FIJA),    False, None),
    ("dolar_linked", set(DOLAR_LINKED), False, None),
    ("tamar",        set(TAMAR),        False, None),  # solo PURO; duales omitidos
    ("ons_ny",       set(ONS),          True,  "NY"),
    ("ons_ar",       set(ONS),          True,  "AR"),
]


def main():
    repo = get_repository()
    insts = repo.get_all_instruments()
    ons_uids = _ons_resolved_universe()
    ric_map = {}

    for panel, types, needs_d, leg_filter in PANELS:
        for inst in insts:
            if (inst.instrument_type or "") not in types:
                continue
            ticker = (inst.ticker or "").strip()
            if not ticker:
                continue
            if needs_d and not ticker.upper().endswith("D"):
                continue
            if leg_filter and (getattr(inst, "legislacion", None) or "").upper() != leg_filter:
                continue
            entry = {"panel": panel}
            isin = getattr(inst, "isin", None)
            if isin:
                entry["isin_local"] = isin
            if ticker in ons_uids:           # ON ya resuelta antes -> reusar RIC/ISIN
                entry["universe_id"] = ons_uids[ticker]
            ric_map[ticker] = entry

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(ric_map, indent=2, ensure_ascii=False), encoding="utf-8")

    from collections import Counter
    by_panel = Counter(v["panel"] for v in ric_map.values())
    with_isin = sum(1 for v in ric_map.values() if "isin_local" in v)
    with_uid = sum(1 for v in ric_map.values() if "universe_id" in v)
    print(f"Mapa semilla escrito: {OUT}")
    print(f"  {len(ric_map)} tickers · {with_isin} con ISIN · {with_uid} con RIC ya resuelto (cache ONs)")
    for p, n in sorted(by_panel.items()):
        print(f"    {p:14s} {n}")
    print("\nSiguiente paso (con LSEG Workspace abierto):")
    print("  .venv-lseg\\Scripts\\python.exe scripts/lseg_fetch_history.py --days 120")
    print("  py -3.12 scripts/backfill_history.py")


if __name__ == "__main__":
    main()
