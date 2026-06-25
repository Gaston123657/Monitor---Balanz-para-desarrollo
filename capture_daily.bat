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

REM --- 2) Commit + push SOLO de los datos capturados (snapshots), nunca otros
REM     archivos en progreso. Stage acotado a data/history/snapshots/ a proposito:
REM     no toca scripts, ni otros CSV de data/history (lseg_ric_map, cer_diario, etc).
git add data/history/snapshots >> "%LOG%" 2>&1
git diff --cached --quiet -- data/history/snapshots
if errorlevel 1 (
  REM commit ACOTADO por pathspec: solo data/history/snapshots, aunque el usuario
  REM tenga otros cambios staged/sin terminar (esos quedan intactos, sin commitear).
  git -c user.name="updater de historico" -c user.email="updater@historico.local" commit -m "datos historicos automaticos %date%" -- data/history/snapshots >> "%LOG%" 2>&1
  git push >> "%LOG%" 2>&1
  echo [%date% %time%] commit+push de snapshots hecho >> "%LOG%"
) else (
  echo [%date% %time%] sin cambios en snapshots, no se commitea >> "%LOG%"
)

echo [%date% %time%] capture_daily END >> "%LOG%"
