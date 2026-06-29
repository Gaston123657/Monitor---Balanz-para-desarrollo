# Captura de tráfico del Add-in de BYMADATA

Objetivo: descubrir host, autenticación y endpoints de datos que usa el Add-in de
Excel (.xll ExcelDNA/.NET) para completar `core/infrastructure/bymadata_provider.py`.

El Add-in .NET usa el proxy **WinINET** y valida TLS contra el **almacén de
certificados de Windows**, así que un proxy local (mitmproxy) con su CA confiada
intercepta el HTTPS. **No requiere admin** (CA en `CurrentUser\Root`, proxy en HKCU).

## Requisitos (ya instalados)
- `.venv-capture` con `mitmproxy` (`py -3.12 -m venv .venv-capture` +
  `.venv-capture\Scripts\python -m pip install mitmproxy`).
- Excel **x64** + el Add-in BYMADATA x64 (`BYMADATA_EXCEL\3.*_x64.xll`).

## Pasos

1. **Setup** (consola PowerShell normal, NO admin):
   ```
   powershell -ExecutionPolicy Bypass -File scripts\bymadata_capture_setup.ps1
   ```
   Aparece un **diálogo de Windows** pidiendo confiar la CA → **Aceptar**.
   Esto activa el proxy 127.0.0.1:8080.

2. **Arrancar la captura** (en OTRA consola; dejala abierta):
   ```
   powershell -ExecutionPolicy Bypass -File scripts\bymadata_capture_run.ps1
   ```

3. **Generar tráfico**: abrí **Excel nuevo** (cerrá los abiertos antes), cargá el
   Add-in BYMADATA, **logueate** (usuario/password) y **refrescá una función BYMA**
   (p. ej. una de precio/profundidad de un ticker como AL30 o GD30). Hacé un par de
   consultas distintas si podés (precio, profundidad, referencia).

4. **Terminar**: volvé a la consola del paso 2 y **Ctrl+C**.

5. **Revertir el sistema** (apaga proxy, quita la CA):
   ```
   powershell -ExecutionPolicy Bypass -File scripts\bymadata_capture_teardown.ps1
   ```

6. **Parsear** (informe REDACTADO, sin credenciales):
   ```
   py -3.12 scripts\bymadata_parse_capture.py %USERPROFILE%\bymadata_capture.jsonl
   ```
   Genera `BYMADATA_EXCEL\CAPTURE-FINDINGS.md`.

## Notas
- El JSONL crudo (`%USERPROFILE%\bymadata_capture.jsonl`) contiene credenciales y
  tokens EN CLARO. Es local, NO lo commitees. El informe del parser los redacta.
- Si la captura sale vacía: el Add-in podría no respetar el proxy WinINET (usar
  `HTTP_PROXY`/`HTTPS_PROXY` o WinHTTP). Avisar para ajustar el método.
- Si hay errores TLS en el Add-in: probablemente **cert pinning** → la captura no es
  viable y queda el camino de contratar la API REST oficial.
