================================================================================
 INTEGRACIÓN LSEG WORKSPACE (Eikon Data API) — Monitor de Renta Fija Balanz
================================================================================
 Estado: ENLAZADA Y PROBADA. Todavía NO integrada a paneles del dashboard.
 Fecha: 2026-06-16
================================================================================


--------------------------------------------------------------------------------
1. QUÉ ES Y CÓMO FUNCIONA
--------------------------------------------------------------------------------

Se conectó la Eikon Data API de LSEG Workspace al proyecto usando la librería
oficial de Python `lseg-data`.

PUNTO CLAVE (modo "Desktop Session"):
La librería NO se conecta directo a internet. Hace un "handshake" contra un
proxy local en http://localhost:9000 que levanta la aplicación de escritorio
LSEG WORKSPACE DESKTOP mientras está ABIERTA y LOGUEADA en la misma máquina.
El dato sale por Workspace; el App Key es solo la credencial.

CONSECUENCIAS:
  - Funciona SOLO en una PC con LSEG Workspace Desktop instalado y abierto.
  - El navegador (workspace.refinitiv.com) NO sirve: no expone localhost:9000.
  - NO funciona en un servidor headless (sin Workspace). Para eso se necesita
    la API "Platform / RDP" con credenciales de máquina, que es OTRA licencia
    distinta al "Eikon Data API" que tenemos hoy.


--------------------------------------------------------------------------------
2. POR QUÉ UN ENTORNO (VENV) AISLADO  ← decisión importante
--------------------------------------------------------------------------------

`lseg-data` exige pandas < 3.0, pero el monitor corre sobre pandas == 3.0.3.
Son incompatibles en el mismo entorno (pip da error de conflicto).

Para NO degradar el monitor en producción, LSEG vive en un venv separado:

        .venv-lseg/          <- entorno virtual solo para LSEG (pandas 2.3.3)
        requirements-lseg.txt <- dependencias de ese entorno

El entorno principal del monitor queda intacto (pandas 3.0.3). Por eso
`requirements.txt` (el del monitor) NO incluye `lseg-data`.


--------------------------------------------------------------------------------
3. ARCHIVOS QUE SE CREARON / MODIFICARON
--------------------------------------------------------------------------------

NUEVOS:
  core/infrastructure/lseg_provider.py   Provider genérico. Clase
                                         LSEGWorkspaceProvider con métodos
                                         open(), close(), is_available(),
                                         get_data(), get_history().
  scripts/lseg_connection_test.py        Prueba de conexión end-to-end.
  tests/test_lseg_provider.py            Tests (config + live skippeable).
  requirements-lseg.txt                  Deps del venv aislado (lseg-data).
  .env.example                           Plantilla del App Key.
  .env                                   App Key real (NO se commitea).
  LSEG-WORKSPACE-README.txt              Este documento.

MODIFICADOS:
  requirements.txt                       Nota: LSEG va aparte (conflicto pandas).
  .gitignore                             Ignora .venv-lseg/ y .env.
  agents.md                              Documentado el provider y la excepción.


--------------------------------------------------------------------------------
4. SETUP (una sola vez, en la PC con Workspace)
--------------------------------------------------------------------------------

  a) Crear el venv aislado e instalar lseg-data:
         python -m venv .venv-lseg
         .venv-lseg\Scripts\python.exe -m pip install -r requirements-lseg.txt

  b) Crear el archivo .env en la raíz con el App Key (ya está hecho):
         LSEG_APP_KEY=<tu app key del AppKey Generator>

  c) Tener LSEG Workspace Desktop ABIERTO y LOGUEADO.


--------------------------------------------------------------------------------
5. CÓMO PROBAR LA CONEXIÓN
--------------------------------------------------------------------------------

  Con Workspace abierto, correr (OJO: el python del venv aislado):

         .venv-lseg\Scripts\python.exe scripts/lseg_connection_test.py

  Resultado esperado (verificado el 2026-06-16):

         [2/3] Abriendo Desktop Session (handshake localhost:9000)…  OK
         --- EUR= ['BID', 'ASK'] ---      EUR=  1.1611  1.1612
         --- AAPL.O ['TR.PriceClose'] --- AAPL.O  296.42
         OK — conexión a LSEG Workspace verificada.

  Si Workspace está cerrado -> mensaje FAIL pidiendo abrirlo.


--------------------------------------------------------------------------------
6. CÓMO CONSULTAR DATOS (API del provider)
--------------------------------------------------------------------------------

  Siempre con el python del venv aislado. Ejemplo:

      from core.infrastructure.lseg_provider import LSEGWorkspaceProvider

      p = LSEGWorkspaceProvider()

      # ¿Está Workspace disponible? (no lanza excepción)
      if not p.is_available():
          ...  # degradar: Workspace cerrado o sin login

      # --- Snapshot de campos (precios/datos actuales) ---
      df = p.get_data("EUR=", ["BID", "ASK"])
      df = p.get_data(["AAPL.O", "MSFT.O"], ["TR.PriceClose", "TR.Volume"])

      # --- Serie histórica / time series ---
      df = p.get_history("AAPL.O", interval="daily", count=30)
      df = p.get_history("EUR=", start="2026-01-01", end="2026-06-01")

      p.close()  # cierra la sesión al terminar

  Devuelve un pandas.DataFrame (el del venv, pandas 2.3.3).

  NOMENCLATURA: LSEG identifica instrumentos por RIC (Reuters Instrument Code),
  no por el ticker local del monitor. Ej:
      EUR=        -> FX spot EUR/USD
      AAPL.O      -> Apple (Nasdaq)
      US10YT=RR   -> Treasury 10Y
      .SPX        -> índice S&P 500
  Los campos (fields) pueden ser de tiempo real (BID, ASK, ...) o de la base
  de contenido (TR.*, ej. TR.PriceClose). Buscar RICs/fields en Workspace con
  la herramienta "Data Item Browser" (DIB) o "Formula Builder".


--------------------------------------------------------------------------------
7. QUÉ FALTA PARA USARLO EN EL DASHBOARD (próxima fase)
--------------------------------------------------------------------------------

El provider está listo y es genérico, pero vive en el venv aislado: NO puede
importarse dentro del proceso del monitor (chocaría pandas). Para alimentar un
panel hay que PUENTEAR los dos entornos. Plan sugerido:

  PASO 1 — Definir qué dato concreto se quiere mostrar (qué RICs, qué campos,
           cada cuánto se refresca: snapshot vs histórico).

  PASO 2 — Microservicio puente. Un script chico que corre en .venv-lseg y
           expone los datos por HTTP local (ej. FastAPI/Flask en un puerto, o
           el http.server que ya usa el proyecto). Mantiene la sesión LSEG
           abierta y responde JSON con los datos pedidos.
           (Alternativa: subproceso on-demand que devuelve JSON por stdout,
           más simple pero re-abre sesión en cada llamada -> más lento.)

  PASO 3 — Consumir desde el monitor. En el entorno principal, un provider que
           le pega al puente vía core/infrastructure/_http.py::http_get_json
           (mismo patrón de retry/cache que el resto de las fuentes).

  PASO 4 — Si va a un panel de instrumentos, envolver en un adaptador que
           implemente core/domain/interfaces.py::IMarketDataProvider
           (fetch_snapshots / fetch_historical_prices) y wirearlo en
           core/use_cases/generate_report.py. Respetar el mapeo ticker local
           <-> RIC de LSEG.

  PASO 5 — Caché + degradación: TTL acorde al refresh del panel; si Workspace
           está cerrado, el panel debe seguir andando con las fuentes actuales
           (Data912, etc.). LSEG es complemento, no reemplazo de Data912
           (pilar de arquitectura: precios locales = Data912).

CONSIDERACIONES OPERATIVAS:
  - El puente solo trae datos si Workspace Desktop está abierto en esa máquina.
  - Si el monitor corre 24x7 en un server sin Workspace, esta vía no aplica:
    habría que evaluar la API Platform/RDP (otra licencia).
  - Verificar límites/permisos del producto Eikon Data API sobre los RICs que
    se quieran consultar (algunos contenidos requieren entitlements).

--------------------------------------------------------------------------------
8. PRIMERA INTEGRACIÓN CONCRETA — CALENDARIO DE PAGOS DE ONs (2026-06-19)
--------------------------------------------------------------------------------

OBJETIVO: completar las ONs que el calendario de pagos (/ons-calendar) marcaba
como "sin datos suficientes" usando reference data + schedule de cashflows de
LSEG, GUARDAR esos datos en el master Excel y NO depender más de la API en
runtime (el monitor lee del Excel como siempre; LSEG es solo carga offline).

PIPELINE (3 pasos, idempotente y re-ejecutable):

  1) py -3.12 scripts/dump_missing_ons.py
       Lee la hoja ONs del master y vuelca a data/_ons_missing.json las ONs sin
       vto/cupón/frecuencia (mismo criterio que server._serve_ons_cashflows).
       (Se corre con el py del monitor porque el venv aislado no tiene openpyxl.)

  2) .venv-lseg\Scripts\python.exe scripts/lseg_fetch_ons.py   (Workspace ABIERTO)
       Resuelve cada ticker local -> instrumento LSEG y baja datos a
       data/lseg_ons_cache.json. Detalles de resolución:
         - El ticker local Balanz (ej. AERBD) NO es identificador LSEG. La línea
           BA-listada tiene RIC 'AR<root><clase>=...' con root = ticker sin el
           sufijo de moneda (D). Se filtra startswith(RIC,'AR<root>') en la vista
           GovCorpInstruments. El root de 4 chars devuelve la serie exacta.
         - Reference data: vto, cupón, frecuencia, emisión, emisor, moneda, ISIN.
         - SCHEDULE de cashflows EXACTO vía IPA (financial_contracts.bond,
           notional=100). CLAVE: TR.FiAmortizationType viene vacío incluso para
           bonos amortizing — NO es fiable. El schedule de IPA captura
           amortización/zero-coupon/step-up sin adivinar. IPA precia a hoy =>
           devuelve solo flujos FUTUROS (justo lo que el calendario necesita).
         - No estimables: FRN/cupón variable y ARS se marcan "floating"; los que
           no matchean ningún RIC quedan "no_match" (carga manual).

  3) py -3.12 scripts/apply_lseg_ons.py [--apply]
       Lee el cache y completa la hoja ONs + hoja Cashflows del master vía
       instruments_abm (único escritor sancionado: atomic .tmp + os.replace).
       Sin --apply es dry-run. Una sola transacción atómica (evita el churn de
       N os.replace sobre el Excel en OneDrive, que gatilla PermissionError).
       NO pisa sector/legislacion existentes. Lista al final las no aplicadas.

RESULTADO (corrida 2026-06-19): de 122 ONs sin datos, 108 completadas con
schedule exacto; estimables del calendario 152 -> 254; "sin datos" 116 -> 14
(12 sin match en LSEG + 2 FRN en ARS) para carga manual.

OJO OPERATIVO: el server carga el repo (Excel) UNA vez al startup y NO hace
hot-reload. Tras correr el pipeline hay que REINICIAR el dashboard (run.bat)
para que el calendario muestre los datos nuevos.

LIMITACIÓN: el schedule guardado es un snapshot a la fecha de fetch (solo
flujos futuros). Para refrescar (bonos que amortizan, ONs nuevas), re-correr
el pipeline con Workspace abierto.

================================================================================
 FIN
================================================================================
