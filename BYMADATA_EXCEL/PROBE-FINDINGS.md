# BYMADATA — informe de spike del backend

Generado por `scripts/bymadata_probe.py` (read-only). Determina cómo habla el Add-in de Excel con BYMADATA para elegir el modo del provider.


## `2.BYMADATA_Excel_Addin-AddIn_1.8.19.4_bymadata_x86.xll` (1,878,184 bytes)

- Framework ExcelDNA/.NET detectado: **True**
- Hosts/URLs reales en texto plano: **ninguno**
- Candidatos (host/endpoint/auth, filtrado de ruido): 10
  - `.config`
  - `</BymaDataExcelAddin.Properties.Settings>`
  - `<BymaDataExcelAddin.Properties.Settings>`
  - `AppSettingsFlag`
  - `BYMADATAEXCELADDIN`
  - `Review the other add-ins that are loaded, or ensure that the .Net 2.0 runtime loads by setting an approriate 'supportedRuntime' entry in a configuration file (Excel.exe.config).`
  - `get_AppSettings`
  - `http://`
  - `https://`
  - `xlfLoginv`

## `3.BYMADATA_Excel_Addin-AddIn_1.8.19.4_bymadata_x64.xll` (1,792,680 bytes)

- Framework ExcelDNA/.NET detectado: **True**
- Hosts/URLs reales en texto plano: **ninguno**
- Candidatos (host/endpoint/auth, filtrado de ruido): 10
  - `.config`
  - `</BymaDataExcelAddin.Properties.Settings>`
  - `<BymaDataExcelAddin.Properties.Settings>`
  - `AppSettingsFlag`
  - `BYMADATAEXCELADDIN`
  - `Review the other add-ins that are loaded, or ensure that the .Net 2.0 runtime loads by setting an approriate 'supportedRuntime' entry in a configuration file (Excel.exe.config).`
  - `get_AppSettings`
  - `http://`
  - `https://`
  - `xlfLoginv`

## Conclusión

El add-in es **ExcelDNA (.NET)**: el código que llama al backend vive en un **assembly .NET empaquetado** dentro del .xll (ExcelDNA lo comprime) y/o lee el host de un `.config`/AppSettings en runtime (`get_AppSettings`, `xlfLogin`). Por eso los endpoints NO aparecen en texto plano. Con lo contratado (solo Add-in), el acceso programático fiable hoy es el **puente Excel/COM** (`BYMADATA_MODE=excel`). El modo `rest` queda como scaffold inerte hasta obtener credenciales de la API REST o confirmar el backend por captura de tráfico.

### Próximos pasos para confirmar el backend en vivo (opcional)

1. **Captura de tráfico**: abrir Excel con el Add-in, loguearse y refrescar una función BYMA con Fiddler/mitmproxy escuchando HTTPS. El host + endpoints + flujo de auth quedan a la vista. Si es replicable con las credenciales del usuario, completar el modo `rest` del provider.
2. **Config en runtime**: buscar el `.config`/AppSettings que el add-in lee (`%APPDATA%`/junto al .xll) — suele tener el host base.
3. **API REST oficial**: si se contrata, usar `client_id`/`client_secret` del portal de desarrolladores contra `api-mgr.byma.com.ar` (modo `rest` directo).
