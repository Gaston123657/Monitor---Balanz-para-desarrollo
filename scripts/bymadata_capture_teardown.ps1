# Revierte los cambios de scripts\bymadata_capture_setup.ps1.
# Apaga el proxy WinINET y (opcional) quita la CA de mitmproxy del almacén CurrentUser.
#
# Uso:  powershell -ExecutionPolicy Bypass -File scripts\bymadata_capture_teardown.ps1

$ErrorActionPreference = "SilentlyContinue"
$key = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings"
Set-ItemProperty -Path $key -Name ProxyEnable -Value 0 -Type DWord
Write-Output "Proxy WinINET DESACTIVADO."

# Quitar la CA de mitmproxy del almacén CurrentUser\Root (best effort).
certutil -user -delstore Root mitmproxy | Out-Null
Write-Output "CA de mitmproxy removida de CurrentUser\Root (si estaba)."
Write-Output "Listo: el sistema volvió al estado previo."
