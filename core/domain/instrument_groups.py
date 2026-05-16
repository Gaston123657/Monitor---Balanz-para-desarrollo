"""Canonical groupings of instrument_type values used by every monitor.

Single source of truth: changing a curve's universe means editing this file,
never a monitor or the web schema. Values must match the `instrument_type`
column in `data/instruments_master.xlsx` (uppercased, stripped).
"""

SOBERANOS = ["BONAR", "GLOBAL"]
BOPREALES = ["BOPREAL"]
TASA_FIJA = ["LECAP", "BONCAP", "DUAL", "BONOFIJA", "PURO"]
CER = ["CER", "LECER", "BONCER", "BONCER ZC", "CON CUPON", "STEP-UP"]
DOLAR_LINKED = ["DOLAR_LINKED"]
