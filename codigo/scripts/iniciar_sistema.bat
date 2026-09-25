@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

:: ============================================================
:: iniciar_sistema.bat
:: Arranque completo del Asistente de Educacion en Windows:
:: Docker (postgres/chromadb/fastapi) -> backend listo ->
:: servidor de embeddings -> reindexar corpus -> frontend ->
:: navegador -> resumen final.
:: ============================================================

:: ============================================================
:: Parametros configurables
:: ============================================================
for %%I in ("%~dp0..\..") do set "PROJECT_DIR=%%~fI"

set "PILOT_ENVIRONMENT_ID=583a73aa-9c99-491d-9cbe-09064e6c9152"
set "CHROMA_HTTP_HOST=localhost"
set "CHROMA_HTTP_PORT=8001"

set "BACKEND_HEALTH_URL=http://localhost:8000/health"
set "EMBEDDING_HEALTH_URL=http://localhost:8500/health"
set "FRONTEND_URL=http://localhost:5173"

set "MAX_WAIT_SECONDS=60"
set "POLL_INTERVAL_SECONDS=3"

:: Margenes de espera (no pedidos explicitamente, pero necesarios en la
:: practica): dan tiempo a que el servidor de embeddings cargue el modelo
:: de sentence-transformers antes de reindexar, y a que Vite abra su
:: puerto antes de abrir el navegador. Ajustar o poner en 0 si no se necesitan.
set "EMBEDDING_WARMUP_SECONDS=20"
set "FRONTEND_WARMUP_SECONDS=4"

set "INDEXAR_RESULT=no ejecutado"

echo ============================================================
echo  Asistente de Educacion - Inicio del sistema
echo  PROJECT_DIR = %PROJECT_DIR%
echo ============================================================
echo.

:: ============================================================
:: PASO 1 - Verificar que Docker Desktop esta corriendo;
::          si no, abrirlo automaticamente y esperar hasta 90s.
:: ============================================================
set "DOCKER_DESKTOP_EXE=C:\Program Files\Docker\Docker\Docker Desktop.exe"
set "DOCKER_MAX_WAIT=90"
set "DOCKER_POLL=5"

echo [1/8] Verificando que Docker Desktop esta corriendo...
docker info >nul 2>&1
if not errorlevel 1 goto docker_ready

echo       Docker no responde. Abriendo Docker Desktop automaticamente...
if not exist "%DOCKER_DESKTOP_EXE%" (
    echo.
    echo ERROR: No se encontro Docker Desktop en:
    echo        %DOCKER_DESKTOP_EXE%
    echo Instala Docker Desktop o ajusta la ruta DOCKER_DESKTOP_EXE en este script.
    echo.
    pause
    exit /b 1
)
start "" "%DOCKER_DESKTOP_EXE%"
echo       Docker Desktop abierto. Esperando a que el motor responda ^(maximo %DOCKER_MAX_WAIT%s, cada %DOCKER_POLL%s^)...

set "DOCKER_ELAPSED=0"
:wait_docker_loop
set /a "_PING_COUNT=%DOCKER_POLL%+1"
ping -n %_PING_COUNT% 127.0.0.1 >nul
set /a DOCKER_ELAPSED+=%DOCKER_POLL%

docker info >nul 2>&1
if not errorlevel 1 goto docker_ready

if %DOCKER_ELAPSED% geq %DOCKER_MAX_WAIT% (
    echo.
    echo ERROR: Docker Desktop no respondio despues de %DOCKER_MAX_WAIT% segundos.
    echo Abre Docker Desktop manualmente, espera a que termine de iniciar y vuelve a ejecutar este script.
    echo.
    pause
    exit /b 1
)
echo       ... esperando al motor de Docker ^(%DOCKER_ELAPSED%s / %DOCKER_MAX_WAIT%s^)
goto wait_docker_loop

:docker_ready
echo       Docker Desktop esta corriendo.
echo.

:: ============================================================
:: PASO 2 - Levantar los contenedores Docker (config/)
:: ============================================================
echo [2/8] Levantando contenedores Docker desde config\ ^(docker compose up --build -d^)...
pushd "%PROJECT_DIR%\config"
docker compose up --build -d
if errorlevel 1 (
    echo.
    echo ERROR: "docker compose up --build -d" fallo en config\. Revisa el log de arriba.
    popd
    pause
    exit /b 1
)
popd
echo       Contenedores levantados en modo detached.
echo.

:: ============================================================
:: PASO 3 - Esperar que FastAPI este disponible (polling a /health)
:: ============================================================
echo [3/8] Esperando que el backend responda en %BACKEND_HEALTH_URL% ^(maximo %MAX_WAIT_SECONDS%s, cada %POLL_INTERVAL_SECONDS%s^)...
set "ELAPSED=0"

:wait_backend_loop
set "HEALTH_STATUS="
for /f %%i in ('curl -s -o nul -w "%%{http_code}" "%BACKEND_HEALTH_URL%"') do set "HEALTH_STATUS=%%i"

if "%HEALTH_STATUS%"=="200" goto backend_ready

if %ELAPSED% geq %MAX_WAIT_SECONDS% (
    echo.
    echo ERROR: el backend no respondio HTTP 200 en %BACKEND_HEALTH_URL% despues de %MAX_WAIT_SECONDS% segundos.
    echo Revisa los logs con: docker compose logs fastapi ^(desde config\^)
    pause
    exit /b 1
)

echo       ... esperando al backend ^(%ELAPSED%s / %MAX_WAIT_SECONDS%s^)
set /a "_PING_COUNT=%POLL_INTERVAL_SECONDS%+1"
ping -n %_PING_COUNT% 127.0.0.1 >nul
set /a ELAPSED+=%POLL_INTERVAL_SECONDS%
goto wait_backend_loop

:backend_ready
echo       Backend disponible ^(HTTP 200^).
echo.

:: ============================================================
:: PASO 4 - Servidor de embeddings (codigo/, nueva ventana)
::          Si ya estaba abierto y sirve el modelo que pide la
::          configuracion, se reutiliza; si sirve otro, se cierra y se
::          relanza. Uno nuevo no podria tomar el puerto 8500.
:: ============================================================
echo [4/8] Servidor de embeddings...
python "%PROJECT_DIR%\codigo\scripts\comprueba_arranque.py" embeddings
if errorlevel 1 goto embeddings_lanzar
goto embeddings_listo

:embeddings_lanzar
echo       Levantando el servidor de embeddings en una nueva ventana...
start "Embedding Server" /D "%PROJECT_DIR%\codigo" cmd /k uvicorn pipeline.embedding_server:app --host 0.0.0.0 --port 8500
echo       Ventana "Embedding Server" abierta. Esperando %EMBEDDING_WARMUP_SECONDS%s a que cargue el modelo...
set /a "_PING_COUNT=%EMBEDDING_WARMUP_SECONDS%+1"
ping -n %_PING_COUNT% 127.0.0.1 >nul

:embeddings_listo
echo.

:: ============================================================
:: PASO 5 - Comprobar el indice del entorno piloto y, solo si hace
::          falta, reindexar. Compara la dimension del indice con la
::          del modelo configurado y, si no corresponde, reindexa
::          PURGANDO, porque la coleccion conserva la dimension con que
::          se creo.
:: ============================================================
echo [5/8] Comprobando el indice del entorno piloto...
python "%PROJECT_DIR%\codigo\scripts\comprueba_arranque.py" indice %PILOT_ENVIRONMENT_ID% %CHROMA_HTTP_PORT%
set "INDICE_ESTADO=%errorlevel%"

if "%INDICE_ESTADO%"=="0" goto indice_omitir
if "%INDICE_ESTADO%"=="3" goto indice_sin_comprobar

echo       Reindexando el corpus del entorno piloto, purgando antes...
python "%PROJECT_DIR%\codigo\scripts\indexar_corpus.py" --purgar
if errorlevel 1 goto indice_con_fallos
echo       Corpus reindexado correctamente.
set "INDEXAR_RESULT=OK - reindexado para el modo configurado"
goto indice_listo

:indice_con_fallos
echo       ADVERTENCIA: indexar_corpus.py termino con al menos un archivo fallido. Revisa el resumen impreso arriba.
set "INDEXAR_RESULT=con advertencias - ver salida arriba"
goto indice_listo

:indice_sin_comprobar
echo       No se reindexa: sin poder comprobar el indice, no se toca.
set "INDEXAR_RESULT=sin comprobar - ver advertencia arriba"
goto indice_listo

:indice_omitir
echo       Se omite el reindexado.
set "INDEXAR_RESULT=omitido - el indice ya corresponde al modo configurado"

:indice_listo
echo.

:: ============================================================
:: PASO 6 - Frontend (codigo/frontend/, nueva ventana)
::          Si ya estaba abierto, se reutiliza: otro mas se abriria en el
::          puerto 5174.
:: ============================================================
echo [6/8] Frontend...
set "FRONTEND_PREVIO="
for /f %%i in ('curl -s -o nul -w "%%{http_code}" "%FRONTEND_URL%"') do set "FRONTEND_PREVIO=%%i"
if "%FRONTEND_PREVIO%"=="200" goto frontend_abierto

echo       Levantando el frontend en una nueva ventana, npm run dev...
start "Frontend Vite" /D "%PROJECT_DIR%\codigo\frontend" cmd /k npm run dev
echo       Ventana "Frontend Vite" abierta. Esperando %FRONTEND_WARMUP_SECONDS%s a que Vite abra el puerto...
set /a "_PING_COUNT=%FRONTEND_WARMUP_SECONDS%+1"
ping -n %_PING_COUNT% 127.0.0.1 >nul
goto frontend_listo

:frontend_abierto
echo       El frontend ya estaba abierto en %FRONTEND_URL%: se reutiliza.

:frontend_listo
echo.

:: ============================================================
:: PASO 7 - Abrir el navegador
:: ============================================================
echo [7/8] Abriendo el navegador en %FRONTEND_URL% ...
start "" "%FRONTEND_URL%"
echo.

:: ============================================================
:: PASO 8 - Resumen del estado de todos los servicios
:: ============================================================
echo [8/8] Resumen del estado de los servicios:
echo.
echo ------------------------------------------------------------
echo  Contenedores Docker
echo ------------------------------------------------------------
pushd "%PROJECT_DIR%\config"
docker compose ps
popd

echo.
echo ------------------------------------------------------------
echo  Servicios HTTP
echo ------------------------------------------------------------

set "BACKEND_FINAL="
for /f %%i in ('curl -s -o nul -w "%%{http_code}" "%BACKEND_HEALTH_URL%"') do set "BACKEND_FINAL=%%i"
if "%BACKEND_FINAL%"=="200" (
    echo  Backend FastAPI   [OK]   %BACKEND_HEALTH_URL%
) else (
    echo  Backend FastAPI   [FALLO - HTTP %BACKEND_FINAL%]   %BACKEND_HEALTH_URL%
)

set "EMBEDDING_FINAL="
for /f %%i in ('curl -s -o nul -w "%%{http_code}" "%EMBEDDING_HEALTH_URL%"') do set "EMBEDDING_FINAL=%%i"
if "%EMBEDDING_FINAL%"=="200" (
    echo  Servidor embeddings [OK]   %EMBEDDING_HEALTH_URL%
) else (
    echo  Servidor embeddings [FALLO - HTTP %EMBEDDING_FINAL%]   %EMBEDDING_HEALTH_URL%   ^(revisa la ventana "Embedding Server"^)
)

set "FRONTEND_FINAL="
for /f %%i in ('curl -s -o nul -w "%%{http_code}" "%FRONTEND_URL%"') do set "FRONTEND_FINAL=%%i"
if "%FRONTEND_FINAL%"=="200" (
    echo  Frontend Vite     [OK]   %FRONTEND_URL%
) else (
    echo  Frontend Vite     [FALLO - HTTP %FRONTEND_FINAL%]   %FRONTEND_URL%   ^(revisa la ventana "Frontend Vite"^)
)

echo.
echo  Reindexado del corpus: %INDEXAR_RESULT%
echo.
echo ============================================================
echo  Sistema iniciado.
echo ============================================================
echo.

endlocal
echo  Esta ventana se cierra sola en 30 segundos.
timeout /t 30 >nul
exit /b 0
