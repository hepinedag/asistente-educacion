# Instalación y verificación — Backend (Fase 1)

Instrucciones para instalar y arrancar lo ya construido en `codigo/backend/`. Comandos exactos para Windows (PowerShell). Todos los comandos de esta sección 1–3 se ejecutan con `codigo/backend` como directorio de trabajo, salvo que se indique lo contrario.

---

## 1. Crear el entorno virtual de Python

Requiere Python 3.11+ instalado y disponible como `python` en el PATH.

```powershell
cd codigo\backend
python -m venv venv
.\venv\Scripts\Activate.ps1
```

Si PowerShell bloquea la activación por política de ejecución, ejecutar una sola vez en esa terminal:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

El prompt debe mostrar `(venv)` al inicio de la línea una vez activado.

---

## 2. Instalar las dependencias necesarias

Con el entorno virtual activo:

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Instala FastAPI, Uvicorn, SQLAlchemy, psycopg2-binary, PyJWT, passlib, httpx y el resto de paquetes listados en `requirements.txt`.

---

## 3. Configurar el archivo `.env` desde `.env.example`

El archivo de configuración vive en `config/.env` (no dentro de `codigo/backend`). Desde `codigo\backend`:

```powershell
Copy-Item "..\..\config\.env.example" "..\..\config\.env"
```

`JWT_SECRET` viene vacío en el ejemplo y debe tener un valor antes de arrancar el servidor. Generarlo y escribirlo automáticamente en el `.env` recién copiado:

```powershell
$jwtSecret = python -c "import secrets; print(secrets.token_hex(32))"
(Get-Content "..\..\config\.env") -replace '^JWT_SECRET=.*', "JWT_SECRET=$jwtSecret" | Set-Content "..\..\config\.env"
```

Por defecto, `config/.env.example` ya está configurado para el entorno local de desarrollo: `LLM_PROVIDER=ollama`, `OLLAMA_HOST=http://localhost:11434`, `OLLAMA_MODEL=llama3.1:8b`, y `DATABASE_URL=postgresql://postgres:postgres@localhost:5432/asistente_educacion`. No es necesario editar nada más para levantar el entorno local descrito en esta guía.

---

## 4. Levantar PostgreSQL localmente

Este proyecto ya incluye `config/docker-compose.yml` con un servicio `postgres` (imagen `postgres:15`). Requiere Docker Desktop instalado y corriendo. Desde la raíz del proyecto:

```powershell
docker compose -f config\docker-compose.yml up -d postgres
```

Verificar que el contenedor está saludable (puede tardar unos segundos en pasar a `healthy`):

```powershell
docker compose -f config\docker-compose.yml ps
```

> Si no se usa Docker, la alternativa es instalar PostgreSQL 15+ nativo en Windows y crear manualmente una base de datos `asistente_educacion` con usuario `postgres` y contraseña `postgres` (o ajustar `DATABASE_URL` en `config/.env` a las credenciales reales).

No es necesario levantar también el servicio `chromadb` ni el servicio `fastapi` del compose para esta guía: el código construido hasta ahora (auth y `/health/llm`) no usa ChromaDB, y el servidor FastAPI se arranca directamente desde el entorno virtual en el paso 6, no desde el contenedor.

---

## 5. Ejecutar las migraciones de base de datos

Este proyecto **no usa Alembic todavía** — no hay un comando de migración independiente. Las 10 tablas definidas en `app/models/` se crean automáticamente mediante `Base.metadata.create_all()`, que se ejecuta dentro del `lifespan` de la aplicación (`app/main.py`) cada vez que el servidor arranca.

Este paso se cumple automáticamente al ejecutar el paso 6 — no hay nada que correr aquí de forma separada.

---

## 6. Arrancar el servidor FastAPI

Con el entorno virtual activo, PostgreSQL corriendo (paso 4) y `config/.env` configurado (paso 3), desde `codigo\backend`:

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

En el log de arranque no debe aparecer ningún error de conexión a PostgreSQL. Para confirmar que las tablas se crearon, en otra terminal:

```powershell
docker compose -f config\docker-compose.yml exec postgres psql -U postgres -d asistente_educacion -c "\dt"
```

Debe listar las 10 tablas: `users`, `environments`, `sessions`, `conversations`, `student_profiles`, `competencies`, `artifacts`, `corpus_metadata`, `curricula`, `assessments`.

---

## 7. Verificar `/health/llm` con Ollama corriendo

Requiere [Ollama](https://ollama.com) instalado en Windows, con el modelo `llama3.1:8b` descargado:

```powershell
ollama pull llama3.1:8b
```

Ollama expone su API local en `http://localhost:11434` automáticamente al instalarse (se ejecuta como servicio de fondo). Confirmar que responde:

```powershell
Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -Method Get
```

Con el servidor FastAPI del paso 6 corriendo, verificar el endpoint de salud del LLM:

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/health/llm" -Method Get
```

Respuesta esperada:

```json
{ "provider": "ollama", "model": "llama3.1:8b", "available": true }
```

Si `available` es `false`: confirmar que Ollama está corriendo (`ollama list` debe mostrar `llama3.1:8b`) y que `OLLAMA_HOST`/`OLLAMA_MODEL` en `config/.env` coinciden con el host y el nombre exacto del modelo descargado.

También puede verificarse la salud general de la API:

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/health" -Method Get
```
