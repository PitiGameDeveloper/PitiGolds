@echo off
rem Prepara el motor para WoW Forever. El addon lo instala WowUp. Vuelve a ejecutarlo si reinstalas el juego.
cd /d "%~dp0"
set "ADDONS=C:\Program Files (x86)\World of Warcraft\_forever_\Interface\AddOns"
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

if not exist "%ADDONS%" (
  echo No encuentro la carpeta de addons de WoW Forever:
  echo   "%ADDONS%"
  echo Abre el juego una vez para que se cree y vuelve a ejecutar este archivo.
  pause
  exit /b 1
)

rem Antes el addon era un enlace a este repositorio. WowUp necesita una carpeta de verdad.
rem rmdir sobre un enlace quita solo el enlace, no lo que hay al otro lado.
dir /AL /B "%ADDONS%" 2>nul | findstr /X /I PitiGolds >nul && (
  rmdir "%ADDONS%\PitiGolds"
  echo He quitado el enlace antiguo de PitiGolds.
)

"%PY%" -m motor datos-juego

if exist "%ADDONS%\PitiGolds\PitiGolds.toc" (
  if not exist "%ADDONS%\PitiGolds\Generated.lua" "%PY%" -m motor leer
) else (
  echo.
  echo Falta instalar el addon. En WowUp, con WoW Forever elegido: Obtener addons,
  echo Instalar desde URL, y pega https://github.com/PitiGameDeveloper/PitiGolds
)
pause
