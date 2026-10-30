@echo off
rem Qué craftear, qué recetas aprender y qué vender. También queda guardado en datos\informe.md.
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" -m motor leer
"%PY%" -m motor datos-juego
"%PY%" -m motor informe
pause
