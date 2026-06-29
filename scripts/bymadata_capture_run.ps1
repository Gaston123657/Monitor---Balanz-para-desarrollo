# Arranca la captura de tráfico de BYMADATA con mitmdump + el addon de filtrado.
# Correr DESPUÉS de scripts\bymadata_capture_setup.ps1, en su propia consola.
# Cortá con Ctrl+C cuando hayas refrescado una función BYMA en Excel.
#
# Uso:  powershell -ExecutionPolicy Bypass -File scripts\bymadata_capture_run.ps1

$ErrorActionPreference = "Stop"
$proj  = Split-Path -Parent $PSScriptRoot
$mitm  = Join-Path $proj ".venv-capture\Scripts\mitmdump.exe"
$addon = Join-Path $proj "scripts\bymadata_capture_addon.py"
$out   = Join-Path $env:USERPROFILE "bymadata_capture.jsonl"

if (-not (Test-Path $mitm)) { Write-Error "Falta mitmdump en $mitm"; exit 1 }

$env:BYMADATA_CAPTURE_OUT = $out
if (Test-Path $out) { Remove-Item $out -Force }

Write-Output "Capturando en: $out"
Write-Output "Proxy escuchando en 127.0.0.1:8080. Abrí Excel (proceso NUEVO), logueate y"
Write-Output "refrescá una función BYMA. Cuando termines, Ctrl+C acá."
Write-Output ""
& $mitm --listen-port 8080 -s $addon
