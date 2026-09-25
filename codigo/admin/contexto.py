# -*- coding: utf-8 -*-
"""Contexto de ejecucion del modulo de administracion.

Resuelve tres cosas y ninguna mas: donde esta el proyecto, como se habla con la
base de datos, y si estan dadas las condiciones para operar.

POR QUE IMPORTA DEL BACKEND Y NO DUPLICA. El modulo necesita saber como son las
tablas y como se cifra una contrasena. Son dos cosas de FORMATO, no de logica:
si cifrara distinto, el login del sistema fallaria. Importarlas no afecta al
sistema -es leer definiciones- y evita el riesgo real de duplicarlas, que es que
el esquema cambie y este modulo siga escribiendo con la forma vieja sin que
nadie se entere.

LO QUE NUNCA HACE. No llama a la API del sistema, no importa sus routers ni su
logica de negocio, y no necesita que el backend este corriendo. Escribe en
PostgreSQL, que es el almacen que el sistema lee en cada peticion.
"""
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
BACKEND = RAIZ / "codigo" / "backend"
ENV_PATH = RAIZ / "config" / ".env"
COMPOSE_PATH = RAIZ / "config" / "docker-compose.yml"
DIR_MODULO = Path(__file__).resolve().parent
DIR_RESPALDOS = DIR_MODULO / "respaldos"
DIR_SALIDAS = DIR_MODULO / "salidas"

# El backend entra al path para poder importar sus modelos y su cifrado. Es la
# unica relacion con el sistema, y es de solo lectura de definiciones.
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


class RequisitoFaltante(Exception):
    """Falta algo para operar. Se dice antes de empezar, no a mitad."""


def comprueba_requisitos():
    """Devuelve la lista de problemas encontrados. Vacia es que todo esta listo."""
    problemas = []

    if not ENV_PATH.is_file():
        problemas.append("No se encuentra config/.env; sin el no hay datos de conexion.")

    try:
        import sqlalchemy  # noqa: F401
    except ImportError:
        problemas.append(
            "Falta SQLAlchemy. Ejecutar este modulo con el interprete del backend:\n"
            "       codigo/backend/venv/Scripts/python.exe codigo/admin/admin.py"
        )

    try:
        import passlib  # noqa: F401
    except ImportError:
        problemas.append("Falta passlib, que es lo que cifra las contrasenas igual que el sistema.")

    if not BACKEND.is_dir():
        problemas.append("No se encuentra codigo/backend; el modulo lee de ahi sus definiciones.")

    return problemas


def ajustes():
    """La configuracion del sistema, leida de config/.env por el propio backend."""
    from app.core.config import settings
    return settings


def sesion():
    """Una sesion de base de datos propia del modulo.

    No se reutiliza `SessionLocal` del backend a proposito: el modulo abre y
    cierra la suya, y asi su ciclo de vida no depende de nada del sistema.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(ajustes().database_url, pool_pre_ping=True)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def base_alcanzable():
    """(True, '') si se puede consultar la base; (False, motivo) si no."""
    try:
        from sqlalchemy import text
        s = sesion()
        try:
            s.execute(text("SELECT 1"))
            return True, ""
        finally:
            s.close()
    except Exception as exc:
        return False, str(exc).splitlines()[0][:200]


def modelos():
    """Las definiciones del sistema que el modulo necesita para escribir bien."""
    from app.models.user import User, UserRole
    from app.models.environment import Environment, EnvironmentStatus
    return User, UserRole, Environment, EnvironmentStatus


def cifra(password):
    """El mismo cifrado del sistema. Si esto cambiara, el login fallaria.

    Va por `app.core.security.hash_password`, que es lo que usa el sistema. Si esa
    llamada falla, cae a bcrypt directo, y el motivo es concreto: `passlib` 1.7.4
    -la version que usa el proyecto- se rompe al arrancar con `bcrypt` 4.1 o
    posterior, porque intenta detectar un defecto antiguo cifrando una cadena de
    mas de 72 bytes y las versiones nuevas de bcrypt rechazan eso en vez de
    truncarlo. Con bcrypt 5.x falla; con la 4.0.x del contenedor funciona.

    El respaldo produce EL MISMO formato -bcrypt, `$2b$`, coste 12-, que es
    exactamente lo que passlib genera y lo que `verify_password` del sistema
    acepta. No es un cifrado distinto: es la misma funcion sin el envoltorio que
    se rompe con bcrypt reciente.
    """
    try:
        from app.core.security import hash_password
        return hash_password(password)
    except Exception:
        import bcrypt
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")


def prepara_directorios():
    for d in (DIR_RESPALDOS, DIR_SALIDAS):
        d.mkdir(parents=True, exist_ok=True)


def docker_disponible():
    """(True, version) si docker responde; (False, motivo) si no."""
    import subprocess
    try:
        r = subprocess.run(["docker", "--version"], capture_output=True, text=True, timeout=15)
        if r.returncode == 0:
            return True, r.stdout.strip()
        return False, (r.stderr or r.stdout).strip().splitlines()[0][:160]
    except FileNotFoundError:
        return False, "docker no esta en el PATH"
    except Exception as exc:
        return False, str(exc).splitlines()[0][:160]
