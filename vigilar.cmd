@echo off
rem Lee los datos del addon cada vez que WoW los guarda (/reload o salir del juego).
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" -m motor vigilar
pause
