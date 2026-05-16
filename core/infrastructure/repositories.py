import json
import logging
import os
import ssl
import threading
import urllib.request
import warnings

import pandas as pd
from typing import List, Dict, Optional
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta
from core.domain.models import Instrument, Cashflow, MarketSnapshot
from core.domain.interfaces import IInstrumentsRepository, IMarketDataProvider

# Silence unnecessary pandas warnings for cleaner console
warnings.filterwarnings("ignore", category=UserWarning, module="pandas")

logger = logging.getLogger(__name__)


def normalize_symbol(ticker: str, ric: str) -> str:
    """Reduce a Refinitiv RIC (e.g. 'ARAL29D1=BA') to the canonical clean ticker
    used throughout the system ('AL29D'). Falls back to `ticker` if no RIC.
    """
    if not ric or pd.isna(ric):
        return ticker
    norm = str(ric).upper().strip()
    if norm.startswith("AR"):
        norm = norm[2:]
    if "=" in norm:
        norm = norm.split("=")[0]
    if len(norm) > 1 and norm[-2] == "D" and norm[-1].isdigit():
        norm = norm[:-1]
    return norm


class ExcelInstrumentsRepository(IInstrumentsRepository):
    NON_INSTRUMENT_SHEETS = frozenset({"Cashflows", "Cashflows_Fija", "Metadata", "Cotizaciones"})

    def __init__(self, excel_path: str):
        self.excel_path = excel_path
        self._cache_instruments: List[Instrument] = []
        self._by_ticker: Dict[str, Instrument] = {}
        self._load_all()

    def _normalize_symbol(self, ticker: str, ric: str) -> str:
        return normalize_symbol(ticker, ric)

    def _parse_date(self, val) -> Optional[date]:
        """Safely parse date from various formats without warnings."""
        if pd.isna(val) or val is None: return None
        if isinstance(val, (date, datetime)): return val.date() if hasattr(val, 'date') else val
        if isinstance(val, pd.Timestamp): return val.date()

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                dt = pd.to_datetime(val, dayfirst=True, errors='coerce')
                return dt.date() if pd.notna(dt) else None
            except (ValueError, TypeError):
                return None

    def _generate_bond_cashflows(self, row: pd.Series) -> List[Cashflow]:
        """Generates cashflows from bond parameters if sheet is missing them."""
        try:
            vto = None
            for d_cand in ["fecha_vencimiento", "fecha vencimiento", "fecha_pago", "maturity"]:
                if d_cand in row:
                    vto = self._parse_date(row[d_cand])
                    if vto: break
            
            if not vto: return []
            
            # Parameters
            coupon_rate = float(row.get("cupon anual %", row.get("cupon", 0))) / 100.0
            freq = int(float(row.get("frecuencia pagos", row.get("frecuencia", 2))))
            if freq <= 0: freq = 2
            
            # Start date
            start_date = None
            for d_cand in ["fecha_emision", "fecha emision"]:
                if d_cand in row:
                    start_date = self._parse_date(row[d_cand])
                    if start_date: break
            
            if not start_date: start_date = vto - relativedelta(years=1)
            
            cfs = []
            itype = str(row.get("tipo", "")).upper()
            
            # Zero-coupon fallback
            if coupon_rate == 0 or any(t in itype for t in ("LECER", "ZC", "LECAP")):
                cfs.append(Cashflow(date=vto, amortization=100.0, interest=0.0))
                return cfs
            
            # Special case: TX26 amortizing fallback
            if "TX26" in str(row.get("ticker", "")):
                for i in range(5):
                    d = date(2024, 11, 9) + relativedelta(months=i*6)
                    if d > date.today() - timedelta(days=180):
                        cfs.append(Cashflow(date=d, amortization=20.0, interest=1.0))
                return cfs

            # Default: Single payment at maturity
            cfs.append(Cashflow(date=vto, amortization=100.0, interest=coupon_rate * 100 / freq))
            return cfs
            
        except Exception as e:
            logger.debug(f"Could not generate cashflows: {e}")
            return []

    def _load_all(self):
        try:
            # 1. Load Cashflows (Master lists). Rows with no parseable date are
            #    skipped to avoid TypeError when comparing cf.date >= reference downstream.
            df_cf = pd.read_excel(self.excel_path, sheet_name="Cashflows")
            cf_map: Dict[str, List[Cashflow]] = {}
            skipped = 0
            for _, row in df_cf.iterrows():
                t = str(row.get("ticker", "")).upper().strip()
                if not t:
                    continue
                cf_date = self._parse_date(row.get("fecha_pago"))
                if cf_date is None:
                    skipped += 1
                    continue
                cf_map.setdefault(t, []).append(Cashflow(
                    date=cf_date,
                    amortization=float(row.get("amortizacion", 0)),
                    interest=float(row.get("cupon_interes", 0)),
                ))

            try:
                df_cf_fija = pd.read_excel(self.excel_path, sheet_name="Cashflows_Fija")
                for _, row in df_cf_fija.iterrows():
                    t = str(row.get("ticker", "")).upper().strip()
                    if not t:
                        continue
                    cf_date = self._parse_date(row.get("fecha_pago"))
                    if cf_date is None:
                        skipped += 1
                        continue
                    cf_map.setdefault(t, []).append(Cashflow(
                        date=cf_date,
                        amortization=float(row.get("monto", 0)),
                        interest=0.0,
                    ))
            except (FileNotFoundError, ValueError, KeyError) as e:
                logger.debug(f"Cashflows_Fija sheet not loaded: {e}")

            if skipped:
                logger.warning(f"Skipped {skipped} cashflow rows with invalid fecha_pago.")

            self._cache_instruments = []
            xl = pd.ExcelFile(self.excel_path)
            sheet_names = [s for s in xl.sheet_names if s not in self.NON_INSTRUMENT_SHEETS]

            for sheet in sheet_names:
                try:
                    df = xl.parse(sheet)
                    df.columns = [str(c).lower().strip() for c in df.columns]
                    
                    for _, row in df.iterrows():
                        raw_ticker = None
                        for t_cand in ["ticker", "ticker_ref", "symbol"]:
                            if t_cand in row:
                                raw_ticker = str(row[t_cand]).upper().strip()
                                break
                        if not raw_ticker or raw_ticker == "NAN": continue
                        
                        ric = str(row.get("ric", raw_ticker)).upper().strip()
                        clean_ticker = self._normalize_symbol(raw_ticker, ric)
                        short = str(row.get("short_name", row.get("short name", raw_ticker)))
                        itype = str(row.get("tipo", row.get("clase", sheet))).upper().strip()
                        
                        # Load maturity date
                        m_date = None
                        for d_cand in ["fecha_vencimiento", "fecha vencimiento", "fecha_pago", "maturity"]:
                            if d_cand in row:
                                m_date = self._parse_date(row[d_cand])
                                if m_date: break
                        
                        # Link cashflows
                        cfs = cf_map.get(short.upper(), cf_map.get(raw_ticker, cf_map.get(clean_ticker, [])))
                        
                        # Dynamic Generation fallback
                        if not cfs and m_date:
                            cfs = self._generate_bond_cashflows(row)
                        
                        cer_b = float(row.get("cer emision", row.get("cer_emision", 1.0)))
                        lag_val = int(float(row.get("dias habiles previos", row.get("dias_lag", 10))))

                        self._cache_instruments.append(Instrument(
                            ticker=clean_ticker,
                            ric=ric,
                            short_name=short,
                            instrument_type=itype,
                            maturity_date=m_date,
                            cashflows=cfs,
                            cer_base=cer_b,
                            cer_lag=lag_val
                        ))
                except Exception as e:
                    logger.warning(f"Could not load sheet {sheet}: {e}")

            self._by_ticker = {i.ticker: i for i in self._cache_instruments}
            logger.info(f"Repository loaded {len(self._cache_instruments)} instruments.")
        except Exception as e:
            logger.error(f"Error loading Excel repository: {e}")

    def get_all_instruments(self) -> List[Instrument]:
        return self._cache_instruments

    def get_instruments_by_type(self, instrument_type: str) -> List[Instrument]:
        return [i for i in self._cache_instruments if i.instrument_type == instrument_type]

    def get_instrument_by_ticker(self, ticker: str) -> Optional[Instrument]:
        return self._by_ticker.get(ticker)

class Data912MarketDataProvider(IMarketDataProvider):
    ENDPOINTS = {
        "notes": "https://data912.com/live/arg_notes",
        "bonds": "https://data912.com/live/arg_bonds",
        "corp":  "https://data912.com/live/arg_corp",
    }
    UA = "balanz-monitor/1.0"

    # Historical prices live on disk (CSV). Data912 has no historical endpoint;
    # the CSV is refreshed out-of-band. Kept tab-separated with RIC headers.
    _HISTORY_CSV = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "data", "history", "precio_historico.csv",
    )

    def __init__(self):
        self._cache: Dict[str, dict] = {}
        self._history: Optional[Dict[str, Dict[date, float]]] = None
        self._history_lock = threading.Lock()

    def _fetch_all_endpoints(self):
        all_data = {}
        ctx = ssl._create_unverified_context()
        for name, url in self.ENDPOINTS.items():
            try:
                req = urllib.request.Request(url, headers={"User-Agent": self.UA})
                with urllib.request.urlopen(req, timeout=10, context=ctx) as r:
                    payload = json.loads(r.read().decode("utf-8"))
                    for row in payload:
                        sym = row.get("symbol")
                        if sym: all_data[sym.upper()] = row
            except Exception as e:
                logger.error(f"Error fetching Data912 endpoint {name}: {e}")
        self._cache = all_data

    def fetch_snapshots(self, tickers: List[str]) -> Dict[str, MarketSnapshot]:
        self._fetch_all_endpoints()
        snapshots = {}
        for ticker in tickers:
            t = str(ticker).upper()
            row = self._cache.get(t)
            if not row: continue
            try:
                snapshots[ticker] = MarketSnapshot(
                    instrument=None,
                    price=float(row.get("c", 0.0)),
                    last_update=date.today(),
                    bid=float(row["px_bid"]) if row.get("px_bid") else None,
                    ask=float(row["px_ask"]) if row.get("px_ask") else None,
                    change_pct=float(row["pct_change"]) if row.get("pct_change") else None,
                )
            except (TypeError, ValueError) as e:
                logger.warning(f"Error parsing row for {ticker}: {e}")
        return snapshots

    def _load_history(self) -> Dict[str, Dict[date, float]]:
        # Double-checked locking: cheap read first, then lock only on miss.
        if self._history is not None:
            return self._history
        with self._history_lock:
            if self._history is not None:
                return self._history
            self._history = self._read_history_csv()
            return self._history

    def _read_history_csv(self) -> Dict[str, Dict[date, float]]:
        history: Dict[str, Dict[date, float]] = {}
        if not os.path.isfile(self._HISTORY_CSV):
            logger.info(f"No historical CSV at {self._HISTORY_CSV}; variances unavailable.")
            self._history = history
            return history
        try:
            df = pd.read_csv(self._HISTORY_CSV, sep="\t")
            ts_col = df.columns[0]
            df[ts_col] = pd.to_datetime(df[ts_col], format="%m/%d/%Y", errors="coerce")
            for col in df.columns[1:]:
                # Column header is a RIC (e.g. 'ARAL29D1=BA'); normalise to the
                # repo's canonical ticker so callers can use either form.
                clean = normalize_symbol(col, col)
                series: Dict[date, float] = {}
                for ts, val in zip(df[ts_col], df[col]):
                    if pd.isna(ts) or pd.isna(val):
                        continue
                    try:
                        series[ts.date()] = float(val)
                    except (TypeError, ValueError):
                        continue
                if series:
                    history[clean] = series
                    history[col.upper()] = series  # also indexable by raw RIC
            logger.info(f"Loaded historical prices for {len({id(v) for v in history.values()})} tickers.")
        except Exception as e:
            logger.warning(f"Could not load historical CSV: {e}")
        return history

    def fetch_historical_prices(self, ticker: str, days: int) -> Dict[date, float]:
        history = self._load_history()
        series = history.get(str(ticker).upper())
        if not series or days <= 0:
            return series or {}
        cutoff = date.today() - timedelta(days=days)
        return {d: p for d, p in series.items() if d >= cutoff}
