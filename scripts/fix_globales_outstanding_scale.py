"""Corrige el histórico de globales amortizantes mal escalados (GD29D, GD30D...).

CONTEXTO DEL BUG
----------------
El backfill LSEG resuelve los GLOBALES NY-law a un RIC por CUSIP
(ej. GD30D -> "040114HS2="). Ese RIC cotiza en convención INTERNACIONAL:
precio per-100 de CAPITAL RESIDUAL VIGENTE (outstanding), NO per-100 de
valor nominal ORIGINAL como la escala "D" (MEP) de Data912.

Mientras el global está en gracia/bullet (residual ~ 100, ej. GD35D/GD38D/
GD41D/GD46D en 2026) ambas escalas coinciden y el backfill quedó bien.
Pero para los que YA AMORTIZARON capital (GD30D residual 72, GD29D residual 70)
el precio LSEG (~87) es per-outstanding y, al recalcular TIR/paridad contra un
valor técnico per-original (~72), da paridad > 100% y TIR NEGATIVA — imposible
en un hard-dollar. Los AL* (Bonares) NO sufren esto: su RIC es "AR<root>="
(evaluated), ya per-original.

CONVERSIÓN CORRECTA
-------------------
    precio_per_original = precio_per_outstanding * (residual_nominal / 100)

donde residual_nominal(inst, fecha) = suma de amortizaciones futuras per-100
original = capital vigente (pool factor x100). Es un no-op cuando residual=100,
así que es seguro aplicarlo a todos los globales con RIC CUSIP.

QUÉ HACE
--------
Recorre los snapshots mensuales y, para las filas de globales con RIC CUSIP cuyo
TIR almacenado es NEGATIVO (la firma inequívoca del bug), reescala el precio por
el pool factor as-of la fecha y RECALCULA TIR/valor técnico/paridad/duration con
las MISMAS funciones del backfill (FinancialEngine + _base_bond_row). Upsert
idempotente: tras corregir, el TIR queda positivo, así que re-correr no toca nada.

    py -3.12 scripts/fix_globales_outstanding_scale.py            # aplica
    py -3.12 scripts/fix_globales_outstanding_scale.py --dry-run  # solo reporta
"""
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd

from apps.cli.monitors._common import get_repository
from apps.web.server import _base_bond_row
from core.domain.models import InstrumentMetrics, MarketSnapshot
from core.domain.services import FinancialEngine
from core.infrastructure import history_store
from core.infrastructure.fx_provider import DolarAPIProvider
from core.infrastructure.indices_provider import BCRAIndicesProvider

RIC_MAP = ROOT / "data" / "history" / "lseg_ric_map.json"


def _cusip_ric(uid: str | None) -> bool:
    """RIC internacional por CUSIP (per-outstanding) vs evaluated 'AR...=' (per-original)."""
    return bool(uid) and uid[0].isdigit()


def cusip_global_tickers() -> set[str]:
    full = json.loads(RIC_MAP.read_text(encoding="utf-8"))
    return {
        tk for tk, info in full.items()
        if info.get("panel") == "bonares" and _cusip_ric(info.get("universe_id"))
    }


def main():
    dry = "--dry-run" in sys.argv

    targets = cusip_global_tickers()
    repo = get_repository()
    indices = BCRAIndicesProvider(excel_repo=repo)
    fx = DolarAPIProvider()

    snap_dir = Path(history_store.HISTORY_SNAPSHOTS_DIR)
    rows_by_fecha: dict[str, list[dict]] = defaultdict(list)
    n_fixed = 0

    for csv_path in sorted(snap_dir.glob("*.csv")):
        df = pd.read_csv(csv_path, dtype={"fecha": str, "ticker": str, "source": str})
        # Firma del bug: global CUSIP con TIR almacenado negativo (en %).
        broken = df[df["ticker"].isin(targets) & (df["tir"].astype(float) < 0)]
        for _, r in broken.iterrows():
            ticker = r["ticker"]
            fecha = r["fecha"]
            inst = repo.get_instrument_by_ticker(ticker)
            if inst is None:
                continue
            fdate = date.fromisoformat(fecha)
            residual = FinancialEngine.residual_nominal(inst, fdate)
            factor = residual / 100.0
            old_price = float(r["price"])
            new_price = old_price * factor
            snap = MarketSnapshot(instrument=inst, price=new_price, last_update=fdate,
                                  volume=(None if pd.isna(r.get("volume")) else r.get("volume")))
            tir = FinancialEngine.tir_from_price(snap, new_price, indices, fx, settle_date=fdate)
            if tir is None:
                print(f"  {ticker} {fecha}: TIR None tras corregir — salteado")
                continue
            tvalue = FinancialEngine.calculate_technical_value(snap, indices, fx, ref_date=fdate)
            parity = (new_price / tvalue) if tvalue else None
            dur = FinancialEngine.calculate_duration(snap, tir, settle_date=fdate)
            m = InstrumentMetrics(snapshot=snap, tir=tir, duration=dur,
                                  technical_value=tvalue, parity=parity)
            row = _base_bond_row(m, today=fdate)
            row["panel"] = "bonares"
            rows_by_fecha[fecha].append(row)
            n_fixed += 1
            if dry:
                print(f"  {ticker} {fecha}: px {old_price:.4f} -> {new_price:.4f} "
                      f"(x{factor:.2f}) · TIR {float(r['tir']):.2f}% -> {tir*100:.2f}% "
                      f"· paridad {parity*100:.1f}%")

    if dry:
        print(f"\n[DRY-RUN] {n_fixed} filas se corregirían (sin escribir).")
        return

    for fecha, rows in sorted(rows_by_fecha.items()):
        history_store.append_snapshot(fecha, rows, source="lseg_backfill")
    print(f"\nCorrección aplicada: {n_fixed} filas reescaladas en {len(rows_by_fecha)} fechas.")


if __name__ == "__main__":
    main()
