# Setup de captura de tráfico del Add-in de BYMADATA (NO requiere admin).
#
# Hace 3 cosas reversibles:
#   1. Genera la CA de mitmproxy (corre mitmdump unos segundos).
#   2. Confía esa CA en el almacén CurrentUser\Root (aparecerá un diálogo de
#      Windows pidiendo confirmación — aceptalo; es para poder ver el HTTPS).
#   3. Apunta el proxy WinINET (HKCU) a 127.0.0.1:8080 (lo que usa el Add-in .NET).
#
# Revertir todo: scripts\bymadata_capture_teardown.ps1
#
# Uso:  powershell -ExecutionPolicy Bypass -File scripts\bymadata_capture_setup.ps1

$ErrorActionPreference = "Stop"
$proj = Split-Path -Parent $PSScriptRoot
$mitm = Join-Path $proj ".venv-capture\Scripts\mitmdump.exe"
$ca   = Join-Path $env:USERPROFILE ".mitmproxy\mitmproxy-ca-cert.cer"

if (-not (Test-Path $mitm)) {
    Write-Error "No existe $mitm. Instalá mitmproxy: py -3.12 -m venv .venv-capture; .venv-capture\Scripts\python -m pip install mitmproxy"
    exit 1
}

# 1) Generar la CA si no existe (mitmdump la crea al primer arranque).
if (-not (Test-Path $ca)) {
    Write-Output "Generando CA de mitmproxy..."
    $p = Start-Process -FilePath $mitm -ArgumentList "--listen-port","8080","-q" -PassThru -WindowStyle Hidden
    Start-Sleep -Seconds 5
    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}
if (-not (Test-Path $ca)) { Write-Error "No se generó la CA en $ca"; exit 1 }

# 2) Confiar la CA en CurrentUser\Root (sin admin). Aparece diálogo de Windows.
Write-Output "Confiando la CA de mitmproxy en CurrentUser\Root (aceptá el diálogo)..."
certutil -user -addstore -f Root $ca | Out-Null

# 3) Proxy WinINET → mitmproxy.
$key = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings"
Set-ItemProperty -Path $key -Name ProxyServer -Value "127.0.0.1:8080"
Set-ItemProperty -Path $key -Name ProxyEnable -Value 1 -Type DWord
Write-Output "Proxy WinINET → 127.0.0.1:8080 ACTIVADO."
Write-Output ""
Write-Output "Listo. Ahora, en OTRA consola, arrancá la captura:"
Write-Output "  scripts\bymadata_capture_run.ps1"
Write-Output "Después abrí Excel (NUEVO proceso), cargá el Add-in, logueate y refrescá una función BYMA."
