@echo off
rem Copia el addon de este repositorio al juego para probar cambios sin publicar una version.
rem Haz /reload despues. La proxima actualizacion de WowUp lo deja como en la release.
cd /d "%~dp0"
set "ADDONS=C:\Program Files (x86)\World of Warcraft\_forever_\Interface\AddOns"

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
