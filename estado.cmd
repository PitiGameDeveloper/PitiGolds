@echo off
rem Resumen de personajes, oro, profesiones y subasta.
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" -m motor leer
"%PY%" -m motor estado
pause
