from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional
import pandas as pd

@dataclass(frozen=True)
class Cashflow:
    date: date
    amortization: float
    interest: float
    
    @property
    def total(self) -> float:
        return self.amortization + self.interest

@dataclass
class Instrument:
    ticker: str
    ric: str
    short_name: str
    instrument_type: str  # CER, LECAP, BONAR, etc.
    maturity_date: Optional[date] = None
    cashflows: List[Cashflow] = field(default_factory=list)
    cer_base: Optional[float] = None
    cer_lag: int = 10  # Default 10 business days for AR CER bonds
    category: Optional[str] = None  # Market-facing label (e.g. "BONCERES CERO CUPON")
    floor_rate_monthly: Optional[float] = None  # DUAL TAMAR: monthly floor rate (decimal)
    
    def get_future_cashflows(self, reference_date: date) -> List[Cashflow]:
        return [cf for cf in self.cashflows if cf.date >= reference_date]

@dataclass
class MarketSnapshot:
    instrument: Instrument
    price: float
    last_update: date
    bid: Optional[float] = None
    ask: Optional[float] = None
    volume: Optional[float] = None   # ARS notional traded today (Data912 "v")
    operations: Optional[int] = None  # number of trades today (Data912 "q_op")
    change_pct: Optional[float] = None

@dataclass
class InstrumentMetrics:
    snapshot: MarketSnapshot
    tir: Optional[float] = None
    duration: Optional[float] = None
    mduration: Optional[float] = None
    technical_value: Optional[float] = None
    parity: Optional[float] = None
    variance_7d: Optional[float] = None
    variance_30d: Optional[float] = None
    variance_1y: Optional[float] = None
