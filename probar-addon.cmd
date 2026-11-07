@echo off
rem Copia el addon de este repositorio al juego para probar cambios sin publicar una version.
rem Haz /reload despues. La proxima actualizacion de WowUp lo deja como en la release.
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
rem La carpeta del juego es la del motor (config.json si existe).
for /f "usebackq delims=" %%i in (`call "%PY%" -c "from motor.config import load_config; print(load_config().wow_dir)"`) do set "ADDONS=%%i\Interface\AddOns"

if not exist "%ADDONS%\PitiGolds\PitiGolds.toc" (
  echo Primero instala el addon con WowUp: no lo encuentro en
  echo   "%ADDONS%\PitiGolds"
  pause
  exit /b 1
)
rem Generated.lua se queda como esta: lo escribe el motor directamente en el juego.
robocopy "addon\PitiGolds" "%ADDONS%\PitiGolds" /E /XF Generated.lua Generated.tmp /NFL /NDL /NJH /NJS
if errorlevel 8 (
  echo No se ha podido copiar el addon.
) else (
  echo Addon copiado. Haz /reload en el juego.
)
pause
