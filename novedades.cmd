@echo off
rem Mira las fuentes (canales de YouTube, Wowhead, Reddit, la carpeta fuentes\) y baja la transcripcion
rem de cada video nuevo a fuentes\youtube\. Despues, el asesor decide que meter en el conocimiento.
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" -c "import youtube_transcript_api" 2>nul || "%PY%" -m pip install -q -r requirements.txt
"%PY%" -m motor fuentes
echo.
where claude >nul 2>nul && (
  cd asesor
  claude "Investiga: busca metodos nuevos en las novedades de las fuentes"
  goto :eof
)
echo Para meterlo en el conocimiento: abre el asesor en Claude Code y pidele "Investiga".
pause
