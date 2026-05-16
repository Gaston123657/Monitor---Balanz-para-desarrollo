# AGENTS.md — Guía para IA / Desarrolladores

**Monitor de instrumentos de renta fija argentinos. Documento maestro de arquitectura.**

---

## VISIÓN GENERAL

Monitor automatizado de los principales segmentos de renta fija en Argentina (Soberanos, Bopreales, Tasa Fija, CER, Dólar Linked) que obtiene precios en tiempo real desde **Data912** (`https://data912.com/live/*`), calcula TIR / Duración / Valor Técnico / Paridad de forma centralizada, y presenta los resultados en consola, PNG y un dashboard web.

### Stack técnico
- Python 3.12+
- **Precios de mercado**: Data912 (`arg_notes`, `arg_bonds`, `arg_corp`)
- **Índice CER**: BCRA API v4.0 — única excepción a la regla "todo desde Data912" (es dato de referencia, no de mercado)
- **Histórico de precios**: `data/history/precio_historico.csv` (TSV, columnas = RICs)
- **Master de instrumentos**: `data/instruments_master.xlsx`
- Matemática: SciPy (Newton + Brentq para XIRR), NumPy, Pandas
- Salida: Tabulate (consola), Matplotlib (PNG), `http.server` (web)

---

## LOS 4 PILARES ARQUITECTÓNICOS

| Pilar | Implementación | Regla |
|---|---|---|
| **1. Un script por curva** | `apps/cli/monitors/*.py` | Cada curva (Soberanos, Bopreales, CER, etc.) tiene exactamente un script CLI. |
| **2. Excel central como única fuente de instrumentos** | `core/infrastructure/repositories.py::ExcelInstrumentsRepository` | Nadie más lee `instruments_master.xlsx`. Sin listas hardcodeadas de tickers. |
| **3. IRR/TIR centralizado** | `core/domain/services.py::FinancialEngine` | Única implementación de `xirr` y `calculate_tir`. Nadie reimplementa fórmulas financieras. |
| **4. Datos puramente Data912** | `core/infrastructure/repositories.py::Data912MarketDataProvider` | Único provider de precios. BCRA queda permitido solo para CER (índice de referencia). |

---

## PIPELINE

```
instruments_master.xlsx ──► ExcelInstrumentsRepository ──┐
                                                          │
Data912 (live) ─────────► Data912MarketDataProvider ──┐  │
                                                       ▼  ▼
                                      GenerateMonitorReport.execute(types)
                                                       │
                                                       ▼
                                        FinancialEngine.calculate_tir / duration / theoretical_price
                                                       │
                                                       ▼
                            apps/cli/monitors/<curva>.py ──► consola + PNG
                            apps/web/server.py ──► dashboard JSON
```

---

## ESTRUCTURA DE ARCHIVOS

```
Monitores - Data912/
├── run.py                              # Menú interactivo CLI
├── agents.md                           # Este documento
│
├── apps/
│   ├── cli/monitors/
│   │   ├── _common.py                  # bootstrap singleton + formatters + run_monitor()
│   │   ├── bonares.py                  # SOBERANOS (BONAR + GLOBAL)
│   │   ├── bopreales.py                # BOPREALES
│   │   ├── cer.py                      # Bonos CER
│   │   ├── dolar_linked.py             # Bonos Dólar Linked
│   │   ├── tasa_fija.py                # LECAP / BONCAP / DUAL / BONOFIJA / PURO
│   │   └── comparacion_tirs.py         # Escenarios de sensibilidad
│   └── web/
│       └── server.py                   # Dashboard interactivo + API JSON
│
├── config/
│   ├── settings.py                     # Paths, setup_logging(), constantes
│   └── theme.py                        # Paleta y geometría de los PNG
│
├── core/
│   ├── domain/
│   │   ├── models.py                   # Instrument, Cashflow, MarketSnapshot, InstrumentMetrics
│   │   ├── interfaces.py               # IInstrumentsRepository, IMarketDataProvider, IMetricsCalculator
│   │   ├── services.py                 # FinancialEngine (xirr, tir, duration, theoretical_price)
│   │   └── instrument_groups.py        # SOBERANOS, BOPREALES, TASA_FIJA, CER, DOLAR_LINKED
│   ├── infrastructure/
│   │   ├── repositories.py             # ExcelInstrumentsRepository + Data912MarketDataProvider
│   │   └── indices_provider.py         # BCRAIndicesProvider (excepción CER)
│   ├── use_cases/
│   │   └── generate_report.py          # GenerateMonitorReport.execute(types) -> [InstrumentMetrics]
│   └── holiday_engine.py               # Calendario BYMA + feriados AR (settlement T+0/T+1)
│
├── data/
│   ├── instruments_master.xlsx         # FUENTE DE VERDAD: hojas por tipo + Cashflows + Cashflows_Fija
│   ├── feriados_ar.xlsx                # Feriados argentinos cacheados
│   └── history/precio_historico.csv    # Histórico TSV para variaciones 7D/30D/1Y
│
└── presentation/
    ├── console_printer.py              # print_monitor(title, df)
    └── png_exporter.py                 # draw_monitor_png(df, path, title)
```

---

## CÓMO AGREGAR UNA NUEVA CURVA

1. **Agregar el tipo** al `instrument_type` correspondiente en `instruments_master.xlsx`.
2. **Agregar el tipo** a la constante adecuada en [`core/domain/instrument_groups.py`](core/domain/instrument_groups.py) (o crear una nueva constante si es una curva nueva).
3. **Crear el script** en `apps/cli/monitors/<curva>.py` usando `run_monitor(...)` del módulo `_common.py`. Mirá `dolar_linked.py` como referencia: ~30 líneas.
4. **Registrar** la función en `run.py` (lista `monitors`).
5. **Opcional**: agregar columnas en `apps/web/server.py::_get_columns` si querés exponerla en el dashboard.

**Nunca**:
- Hardcodear listas de tickers en un monitor (usar `instrument_groups.py`).
- Crear un cliente HTTP nuevo para precios (usar `Data912MarketDataProvider`).
- Reimplementar TIR / duration / NPV (usar `FinancialEngine`).
- Leer el Excel maestro fuera de `ExcelInstrumentsRepository`.

---

## CÓMO EXTENDER LA MATEMÁTICA FINANCIERA

Todo va en [`core/domain/services.py::FinancialEngine`](core/domain/services.py) como `@staticmethod`. Métodos existentes:

| Método | Devuelve |
|---|---|
| `xirr(flows, dates)` | TIR de un flujo de caja (decimal fraction; 0.30 = 30%) |
| `calculate_tir(snapshot, indices_provider=None)` | TIR del instrumento; ajusta por CER si corresponde |
| `calculate_duration(snapshot, tir)` | Modified Duration |
| `calculate_technical_value(snapshot, indices_provider)` | Valor Técnico (Valor Par) — 100 si no es CER |
| `calculate_theoretical_price(instrument, tir, ref_date)` | Precio implícito al descontar al TIR dado |
| `calculate_pct_change(current, previous)` | Variación porcentual (None-safe) |

---

## CACHE Y PERFORMANCE

- **Repositorio Excel**: singleton vía [`apps/cli/monitors/_common.py::get_repository`](apps/cli/monitors/_common.py). El Excel se carga **una sola vez** por sesión, no por monitor.
- **Snapshots Data912**: `Data912MarketDataProvider._cache` se rellena en cada `fetch_snapshots`. No es cross-call; cada llamada refetchea (porque son precios live).
- **Histórico**: el CSV se lee una vez por instancia de `Data912MarketDataProvider`.
- **Índice CER**: `BCRAIndicesProvider._instance_cache` es class-level + thread-safe; persiste durante el día.
- **Feriados**: `core/holiday_engine.py` cachea en `data/feriados_ar_cache.json`.

---

## TROUBLESHOOTING

| Error | Causa probable | Solución |
|---|---|---|
| `No se encontró instruments_master.xlsx` | El Excel se movió | Restaurarlo en `data/instruments_master.xlsx` |
| Variaciones 7D/30D/1Y todas `-` | El CSV histórico no tiene el RIC del instrumento | Refrescar `data/history/precio_historico.csv` |
| TIR muestra `nan` o números absurdos | Cashflows del Excel desactualizados o vencidos | Revisar hoja `Cashflows` / `Cashflows_Fija` |
| CER no funciona | BCRA API caída o sin conectividad | Verificar `https://api.bcra.gob.ar/estadisticas/v4.0/Monetarias/30` |
| Aparece menos instrumentos de los esperados | Filtro de tipos en `instrument_groups.py` no incluye el tipo del Excel | Agregar el `instrument_type` al grupo correspondiente |

---

## CHECKLIST PARA DESARROLLADORES

- [ ] ¿Agregaste un instrumento? Solo en `data/instruments_master.xlsx`.
- [ ] ¿Cambió un flujo? Hoja `Cashflows` (o `Cashflows_Fija`).
- [ ] ¿Nuevo cálculo financiero? `FinancialEngine` en `core/domain/services.py`.
- [ ] ¿Nuevo monitor? Script en `apps/cli/monitors/`, tipo en `instrument_groups.py`, registro en `run.py`.
- [ ] ¿Nueva fuente de datos? Justificar por qué no se puede hacer con Data912; si es índice/referencia, modelo análogo a `BCRAIndicesProvider`.

---

**Última actualización:** 2026-05-16
**Versión:** 4.0 (Post-audit arquitectónico, Data912-pure + Excel-pure)
