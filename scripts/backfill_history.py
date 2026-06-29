"""Recálculo as-of del histórico a partir de precios LSEG -> store de snapshots.

Corre en el ENTORNO PRINCIPAL (py 3.12), NO en el venv aislado:

    py -3.12 scripts/backfill_history.py

QUÉ HACE
--------
Lee data/history/_lseg_prices_raw.json (generado por scripts/lseg_fetch_history.py
en el venv aislado) y, para cada (ticker, fecha, precio), RECALCULA TIR / valor
técnico / paridad / duration *as-of esa fecha* reusando FinancialEngine y los
índices CER/TAMAR/A3500 que el monitor ya persiste (BCRAIndicesProvider los busca
por fecha). Escribe las filas resultantes al mismo store que la captura live
(core/infrastructure/history_store.py) con source="lseg_backfill".

No inventa matemática: usa exactamente las mismas funciones que el panel live, y
arma la fila con `_base_bond_row` para garantizar idéntica escala de unidades
(TIR/paridad en %, etc.).

LÍMITE CONOCIDO (sin truncado silencioso)
-----------------------------------------
La profundidad del recálculo de bonos CER/DL queda acotada por la profundidad de
los CSV de índices (cer_diario / a3500_diario): si no hay índice as-of una fecha,
el TIR sale None y esa fila se SALTEA. El resumen final imprime cuántas filas se
saltearon y por qué. Soberanos sufijo D (hard-dollar) no dependen de índices.
"""
import json
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apps.cli.monitors._common import get_repository
from apps.web.server import _base_bond_row
from core.domain.models import InstrumentMetrics, MarketSnapshot
from core.domain.services import FinancialEngine
from core.infrastructure import history_store
from core.infrastructure.fx_provider import DolarAPIProvider
from core.infrastructure.indices_provider import BCRAIndicesProvider

RAW = ROOT / "data" / "history" / "_lseg_prices_raw.json"


def main():
    if not RAW.is_file():
        raise SystemExit(f"Falta {RAW}. Corré primero scripts/lseg_fetch_history.py en el venv aislado.")
    raw = json.loads(RAW.read_text(encoding="utf-8"))

    repo = get_repository()
    indices = BCRAIndicesProvider(excel_repo=repo)
    fx = DolarAPIProvider()

    rows_by_fecha = defaultdict(list)
    skipped = Counter()
    n_ok = 0

    for ticker, info in raw.items():
        panel = info.get("panel")
        inst = repo.get_instrument_by_ticker(ticker)
        if inst is None:
            skipped["instrumento_no_encontrado"] += len(info.get("prices", []))
            print(f"  {ticker}: instrumento no está en el master — salteado")
            continue
        # Globales NY-law que resuelven a un RIC por CUSIP (universe_id arranca con
        # dígito, ej GD30D -> "040114HS2=") cotizan en convención INTERNACIONAL:
        # precio per-100 de CAPITAL RESIDUAL VIGENTE (outstanding), no per-100 de VN
        # original como la escala "D" de Data912. Para los que ya amortizaron capital
        # (GD30D residual 72, GD29D 70) hay que reescalar por el pool factor as-of la
        # fecha; si no, la paridad da >100% y la TIR NEGATIVA (imposible en hard-dollar).
        # No-op mientras el bono está en gracia/bullet (residual=100: GD35D/38/41/46).
        # Los AL* (Bonares) usan RIC "AR<root>=" evaluated, ya per-original: NO tocar.
        uid = info.get("universe_id")
        cusip_global = panel == "bonares" and bool(uid) and uid[0].isdigit()
        for p in info.get("prices", []):
            fecha = p["fecha"]
            close = p.get("close")
            if close is None or close <= 0:
                skipped["precio_invalido"] += 1
                continue
            fdate = date.fromisoformat(fecha)
            if cusip_global:
                close = float(close) * FinancialEngine.residual_nominal(inst, fdate) / 100.0
            snap = MarketSnapshot(instrument=inst, price=float(close),
                                  last_update=fdate, volume=p.get("volume"))
            try:
                tir = FinancialEngine.tir_from_price(snap, float(close), indices, fx, settle_date=fdate)
            except Exception:
                tir = None
            if tir is None:
                skipped["tir_none (sin índice as-of / no converge)"] += 1
                continue
            # Guard de sanidad: una TIR absurda (|TIR| > 1000% = 10.0 decimal) es un XIRR
            # degenerado, no un punto de curva válido. Pasa cuando el precio choca contra
            # un valor técnico inconsistente: cerca del vencimiento o en una transición de
            # amortización cuyo timing en el Excel no coincide con el rebase de LSEG
            # (ej. TX26 2026-05-08 post-amort: 3.4M%). El máximo legítimo observado es ~51%.
            if abs(tir) > 10.0:
                skipped["tir_absurda (>1000%, XIRR degenerado)"] += 1
                print(f"  {ticker} {fecha}: TIR absurda {tir*100:.1f}% (px={close}) — salteado")
                continue
            # Guard de escala: un hard-dollar (bonares/globales) NO puede rendir
            # negativo. Si sale tir<0 es señal de precio en escala equivocada
            # (per-outstanding sin reescalar, RIC mal resuelto, etc.): no persistir.
            if panel == "bonares" and tir < 0:
                skipped["tir_negativa_bonares (escala de precio sospechosa)"] += 1
                print(f"  {ticker} {fecha}: TIR negativa {tir*100:.1f}% en hard-dollar (px={close}) — salteado")
                continue
            try:
                tvalue = FinancialEngine.calculate_technical_value(snap, indices, fx, ref_date=fdate)
            except Exception:
                tvalue = None
            parity = (float(close) / tvalue) if tvalue else None
            try:
                dur = FinancialEngine.calculate_duration(snap, tir, settle_date=fdate)
            except Exception:
                dur = None
            m = InstrumentMetrics(snapshot=snap, tir=tir, duration=dur,
                                  technical_value=tvalue, parity=parity)
            row = _base_bond_row(m, today=fdate)
            row["panel"] = panel
            rows_by_fecha[fecha].append(row)
            n_ok += 1

    for fecha, rows in sorted(rows_by_fecha.items()):
        history_store.append_snapshot(fecha, rows, source="lseg_backfill")

    print(f"\nBackfill completo: {n_ok} filas escritas en {len(rows_by_fecha)} fechas.")
    if skipped:
        print("Salteadas:")
        for reason, n in skipped.most_common():
            print(f"  {n:5d}  {reason}")


if __name__ == "__main__":
    main()
