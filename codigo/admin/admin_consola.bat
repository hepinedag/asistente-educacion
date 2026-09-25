@echo off
REM Acceso de consola al modulo de administracion: la misma logica, sin navegador.
REM Se conserva a proposito como red de seguridad y para cuando no hay navegador
REM a mano. La interfaz web es admin.bat.
cd /d "%~dp0..\.."
set PY=codigo\backend\venv\Scripts\python.exe
if not exist "%PY%" (
  echo No se encuentra el interprete del backend.
  echo Esperado en: %PY%
  pause
  exit /b 1
)
"%PY%" "codigo\admin\admin.py"
REM La ventana solo espera una tecla si hubo un problema que leer.
REM Al cerrar la consola normalmente no deja nada flotando.
if errorlevel 1 (
  echo.
  pause
)
