@echo off
rem Enlaza el addon dentro de WoW Forever. Vuelve a ejecutarlo si reinstalas el juego.
cd /d "%~dp0"
set "ADDONS=C:\Program Files (x86)\World of Warcraft\_forever_\Interface\AddOns"
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

if not exist "%ADDONS%" (
  echo No encuentro la carpeta de addons de WoW Forever:
  echo   %ADDONS%
  echo Abre el juego una vez para que se cree y vuelve a ejecutar este archivo.
  pause
  exit /b 1
)
if exist "%ADDONS%\PitiGolds" (
  echo PitiGolds ya esta instalado en %ADDONS%
) else (
  mklink /J "%ADDONS%\PitiGolds" "%~dp0addon\PitiGolds"
)
if not exist "addon\PitiGolds\Generated.lua" "%PY%" -m motor leer
pause
