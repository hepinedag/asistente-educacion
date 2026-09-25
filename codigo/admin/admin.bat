@echo off
REM Lanzador del modulo de administracion del Asistente de Educacion.
REM Abre la interfaz web en el navegador. Usa el interprete del backend porque
REM el modulo reutiliza sus definiciones de tablas y su funcion de cifrado, y
REM porque de ahi salen fastapi, uvicorn y jinja2. No instala nada propio.
REM
REM Escucha solo en 127.0.0.1:8010. No es alcanzable desde la red.
REM Para la consola de siempre, que se conserva: admin_consola.bat
cd /d "%~dp0..\.."
set PY=codigo\backend\venv\Scripts\python.exe
if not exist "%PY%" (
  echo No se encuentra el interprete del backend.
  echo Esperado en: %PY%
  pause
  exit /b 1
)
"%PY%" "codigo\admin\servidor.py"
REM La ventana solo espera una tecla si hubo un problema que leer.
REM Al cerrar la consola normalmente no deja nada flotando.
if errorlevel 1 (
  echo.
  pause
)
