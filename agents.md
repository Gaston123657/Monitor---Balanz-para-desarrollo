# 🤖 AGENTS.md - Guía para IA / Desarrolladores

**Documento maestro para entender, extender y mantener el Monitor de Bonos Argentinos.**

---

## 📋 TABLA DE CONTENIDOS

1. [Visión General](#visión-general)
2. [Pipeline Completo](#pipeline-completo)
3. [Arquitectura](#arquitectura)
4. [Estructura de Archivos](#estructura-de-archivos)
5. [Guía de Código](#guía-de-código)
6. [Configuración Crítica](#configuración-crítica)
7. [Cómo Extender](#cómo-extender)
8. [Troubleshooting](#troubleshooting)
9. [Notas Técnicas](#notas-técnicas)
10. [Roadmap](#roadmap)

---

## 🎯 VISIÓN GENERAL

### Propósito
Monitor automatizado de instrumentos financieros argentinos (Soberanos, LECAPs, CER, Dólar Linked, TAMAR) que obtiene datos de mercado en tiempo real desde Refinitiv, calcula métricas críticas (TIR, Duración, Tasas Implícitas) y centraliza la gestión de instrumentos en un registro maestro de Excel.

### Usuarios Objetivo
- Mesas de trading y analistas de renta fija.
- Risk officers y control de gestión.

### Stack Técnico
- **Lenguaje**: Python 3.12+
- **API Principal**: Refinitiv (Eikon Data API)
- **Registro Maestro**: Excel (`data/instruments_master.xlsx`)
- **Backend Loader**: `config/instruments_db.py` (Singleton + Cache)
- **Cálculos**: SciPy (Newton para TIR), NumPy, Pandas
- **Presentación**: Consola (Tabulate), PNG (Matplotlib), Web (Bottle.py)

---

## 🔄 PIPELINE COMPLETO

### Flujo de Datos de Extremo a Extremo

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. CONFIGURACIÓN - instruments_master.xlsx                      │
│    Única fuente de verdad para Tickers, RICs y Cashflows.       │
└─────────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│ 2. CARGA DINÁMICA - instruments_db.py                           │
│    Lee el Excel maestro y provee mappings tipados a todo el     │
│    proyecto. Evita hardcodeo de especies.                       │
└─────────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│ 3. OBTENCIÓN DE DATOS - core/data_fetcher.py                    │
│    Batch fetching desde Refinitiv usando los RICs de la BD.     │
└─────────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│ 4. MOTOR DE CÁLCULO - core/financial_math.py                    │
│    - TIR (Newton solver)                                        │
│    - Macaulay & Modified Duration                               │
│    - Tasas (TNA, TEA, TEM)                                      │
└─────────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│ 5. MONITORES ESPECÍFICOS - apps/cli/monitors/                   │
│    Cada monitor (CER, Soberanos, Fija) consume el Loader y el   │
│    Motor de Cálculo para generar su panel de datos.             │
└─────────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│ 6. SALIDA MULTIMODAL                                            │
│    - Consola: Visualización tabular rápida.                     │
│    - PNG: Exportación profesional para reportes.                │
│    - Web: Dashboard interactivo (Bottle + JS).                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🏗️ ARQUITECTURA

### Capas del Sistema

```
┌──────────────────────────────────────────┐
│ CAPA DE APLICACIÓN (apps/)                │
│ - CLI: Monitores de mercado en tiempo real│
│ - WEB: Servidor de visualización y API    │
└──────────────────────────────────────────┘
                    ↑
┌──────────────────────────────────────────┐
│ CAPA DE PRESENTACIÓN (presentation/)      │
│ - Exportadores PNG y formateadores CLI    │
└──────────────────────────────────────────┘
                    ↑
┌──────────────────────────────────────────┐
│ CAPA DE LÓGICA CORE (core/)               │
│ - Data Fetchers (API Refinitiv)           │
│ - Motores de Cálculo Financiero           │
│ - Cache Manager (History & Caches)        │
└──────────────────────────────────────────┘
                    ↑
┌──────────────────────────────────────────┐
│ CAPA DE DATOS Y CONFIG (data/ & config/)  │
│ - instruments_master.xlsx (BASE MAESTRA)  │
│ - instruments_db.py (Loader Singleton)    │
│ - settings.py (Timeouts, API Keys)        │
└──────────────────────────────────────────┘
```

---

## 📁 ESTRUCTURA DE ARCHIVOS

```
Monitores - Data912/
├── run.py                       # [ENTRY POINT] Menú principal interactivo
├── agents.md                    # [DOCS] Guía para IA y Developers
│
├── apps/                        # Aplicaciones finales
│   ├── cli/                     # Monitores de consola (Bonares, CER, etc.)
│   └── web/                     # Servidor Dashboard Web
│
├── config/                      # Configuración y Bases de Datos
│   ├── instruments_db.py        # LOADER del Excel Maestro
│   └── settings.py              # Parámetros de conexión y visualización
│
├── core/                        # El "motor" del sistema
│   ├── data_fetcher.py          # Comunicación batch con Refinitiv
│   └── financial_math.py        # Fórmulas de TIR, Duración y Tasas
│
├── data/                        # Datos estáticos y dinámicos
│   ├── instruments_master.xlsx  # [BASE MAESTRA] Tickers y mappings
│   ├── feriados_ar.xlsx         # Calendario de feriados local
│   └── history/                 # Series históricas para variaciones
│
└── presentation/                # Formateo de salida (Tablas, PNG)
```

---

## 💻 GUÍA DE CÓDIGO

### Entrada Principal: main.py

```python
if __name__ == "__main__":
    # 1. Cargar API key de variable de entorno
    api_key = os.getenv("EIKON_APP_KEY")  # ← CRÍTICO: debe estar definida
    
    # 2. Abrir sesión Refinitiv
    rd.open_session(app_key=api_key)
    
    # 3. Loop principal
    while True:
        # Iterar sobre TICKERS (desde config.py)
        for ticker in TICKERS:
            df = get_dynamic_data(ticker)  # ← Llamada clave
            
        # Mostrar tabla en consola + CSV
        display_monitor(data_list, TICKERS)
        
        # Esperar
        time.sleep(REFRESH_INTERVAL_SEC)  # 30 segundos (configurable)
```

**Puntos clave:**
- `TICKERS` viene de `config.py` (lista completa de tickers)
- `get_dynamic_data()` es el corazón: obtiene todos los datos para 1 ticker
- `display_monitor()` consolida todos los tickers en tabla CSV
- Loop corre indefinidamente (Ctrl+C para detener)

---

## 💻 GUÍA DE CÓDIGO

### El Cargador Central: config/instruments_db.py

Este es el archivo más importante para el mantenimiento. Utiliza `pandas` para leer el Excel maestro y provee funciones como:
- `get_soberano_rics()`: Devuelve lista de RICs para la API.
- `load_cashflows()`: Carga la tabla de flujos futuros.
- `get_tasa_fija_lecap_boncap()`: Configuración para el monitor de Lecaps.

**Regla de Oro:** Si un monitor necesita datos de un instrumento, debe pedírselos a este módulo. No se permiten listas `[]` de tickers en los scripts de `apps/`.

---

### Cálculo de TIR: core/financial_math.py

La TIR se calcula resolviendo el NPV (Net Present Value):
```python
def xirr(flows, dates):
    # Usa scipy.optimize.newton para encontrar la raíz
    # NPV = Σ [CF_i / (1 + TIR)^(t_i)] = 0
```

**Punto clave:** Los flujos de caja se obtienen filtrando la hoja `Cashflows` del Excel maestro por el `short_name` del instrumento y la fecha actual.

---

### Caché de Datos

Para optimizar el rendimiento y no saturar la API ni el disco:
1. **Instrumentos**: `instruments_db.py` cachea las hojas del Excel en el diccionario `_CACHE`.
2. **Feriados**: `core/holiday_engine.py` utiliza un archivo JSON local para evitar recalcular feriados de BYMA en cada ciclo.
3. **Precios Históricos**: `core/cache_manager.py` gestiona el acceso a `data/history/precio_historico.csv` para las variaciones de 7D/30D.

---

## 🚨 TROUBLESHOOTING

### Error: "No se encontró instruments_master.xlsx"
**Causa:** El archivo Excel fue movido o renombrado.
**Solución:** Asegurarse que el archivo esté en `data/instruments_master.xlsx`.

### Error: "Invalid API key"
**Causa:** La variable de entorno `EIKON_APP_KEY` no está configurada.
**Solución:** `$env:EIKON_APP_KEY = "tu_key"` en PowerShell antes de correr `run.py`.

### TIR reporta valores incoherentes
**Causa:** Los flujos de caja en el Excel maestro para esa especie están desactualizados o la fecha de vencimiento es pasada.
**Solución:** Revisar las hojas `Cashflows` y `Soberanos` en el Excel.

---

## ✅ CHECKLIST PARA DESARROLLADORES

- [ ] ¿Agregaste una especie? Hazlo en `data/instruments_master.xlsx`.
- [ ] ¿Cambió un flujo de caja? Actualiza la hoja `Cashflows` del Excel.
- [ ] ¿Nuevo cálculo financiero? Agrégalo a `core/financial_math.py`.
- [ ] ¿Nueva vista en el dashboard? Crea el monitor en `apps/cli/monitors/` y regístralo en `run.py`.

---

**Última actualización:** 2026-05-13
**Versión:** 3.0 (Arquitectura Centralizada)
**Mantenedor:** Antigravity AI
