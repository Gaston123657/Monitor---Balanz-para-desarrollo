"""Canonical groupings of instrument_type values used by every monitor.

Single source of truth: changing a curve's universe means editing this file,
never a monitor or the web schema. Values must match the `instrument_type`
column in `data/instruments_master.xlsx` (uppercased, stripped).
"""

SOBERANOS = ["BONAR", "GLOBAL"]
BOPREALES = ["BOPREAL"]
TASA_FIJA = ["LECAP", "BONCAP", "BONOFIJA"]
CER = ["CER", "LECER", "BONCER", "BONCER ZC", "CON CUPON", "STEP-UP"]
DOLAR_LINKED = ["DOLAR_LINKED"]
TAMAR = ["PURO"]            # TAMAR-linked: pay accrued TAMAR rate at maturity
DUAL_TAMAR = ["DUAL", "DUAL_CER_TAMAR"]  # Dual TAMAR (fixed-floor) + Dual CER/TAMAR (new TXMJ* series)
ONS = ["ON"]  # Obligaciones Negociables — corporativos AR cotizando en arg_corp; filtran NY/AR vía Instrument.legislacion

# Todas las acciones disponibles vía Data912 /arg_stocks (Panel Líder + Panel General).
# No son instrumentos del Excel; sólo se cotizan vía Data912.
PANEL_LIDER = [
    "AGRO", "ALUA", "AUSO", "BBAR", "BHIP", "BMA",  "BOLT", "BPAT", "BYMA",
    "CADO", "CAPX", "CARC", "CECO2", "CELU", "CEPU", "CGPA2", "COME", "CRES",
    "CTIO", "CVH",  "DGCU2", "DOME", "DYCA", "EDN",  "FERR", "FIPL", "GAMI",
    "GARO", "GBAN", "GCDI", "GCLA",  "GGAL", "GRIM", "HARG", "HAVA", "HSAT",
    "INTR", "INVJ", "IRSA", "LEDE",  "LOMA", "LONG", "METR", "MIRG", "MOLA",
    "MOLI", "MORI", "MTR",  "OEST",  "PAMP", "PATA", "POLL", "RICH", "RIGO",
    "ROSE", "SAMI", "SEMI", "SUPV",  "TECO2", "TGNO4", "TGSU2", "TRAN",
    "TXAR", "VALO", "YPFD",
]

# Panel principal (Panel Líder S&P Merval) — subconjunto de PANEL_LIDER.
# Distingue las acciones del índice líder del resto (panel general). Lo usa el
# cierre para privilegiar acciones del panel principal en ganadores/perdedores.
# La composición la fija BYMA trimestralmente: actualizar al rebalanceo.
PANEL_PRINCIPAL = {
    "ALUA", "BBAR", "BMA",  "BYMA", "CEPU", "COME", "CRES", "EDN", "GGAL",
    "LOMA", "METR", "MIRG", "PAMP", "SUPV", "TECO2", "TGNO4", "TGSU2",
    "TRAN", "TXAR", "VALO", "YPFD",
}
