@echo off
REM ============================================================
REM  capture_daily.bat - Captura el snapshot diario al historico
REM  SIN abrir el monitor, y commitea+pushea los datos nuevos al
REM  repo. Pensado para Windows Task Scheduler (cada dia habil a
REM  las 15:00). Loguea a data/history/capture_daily.log (append).
REM  Solo escribe en dias habiles BYMA (el script lo valida); en
REM  dias no habiles no hay cambios y no se commitea nada.
REM ============================================================
setlocal
cd /d "%~dp0"

if not exist "data\history" mkdir "data\history"
set "LOG=data\history\capture_daily.log"

echo ============================================================ >> "%LOG%"
echo [%date% %time%] capture_daily START >> "%LOG%"

REM --- 1) Capturar el snapshot del dia al history_store ---
py -3.12 scripts\capture_daily_snapshot.py >> "%LOG%" 2>&1
set "RC=%errorlevel%"
echo [%date% %time%] captura exit %RC% >> "%LOG%"

REM --- 2) Commit + push de los datos nuevos (solo si hubo cambios) ---
git add data/history >> "%LOG%" 2>&1
git diff --cached --quiet
if errorlevel 1 (
  git commit -m "datos historicos automaticos %date%" >> "%LOG%" 2>&1
  git push >> "%LOG%" 2>&1
  echo [%date% %time%] commit+push hecho >> "%LOG%"
) else (
  echo [%date% %time%] sin cambios en data/history, no se commitea >> "%LOG%"
)

echo [%date% %time%] capture_daily END >> "%LOG%"
