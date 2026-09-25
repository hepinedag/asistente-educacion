"""Elimina los registros duplicados de corpus_metadata en PostgreSQL para un
environment_id especifico, generados por ejecutar indexar_corpus.py mas de
una vez contra el mismo entorno piloto. Primero borra las filas de
corpus_versions que referencian esos registros (por la FK
corpus_versions.corpus_metadata_id -> corpus_metadata.id) y luego borra los
registros de corpus_metadata. NO toca ChromaDB: los chunks ya indexados en la
coleccion correspondiente de ChromaDB no se modifican.

Uso: python codigo/scripts/limpiar_corpus.py
"""

import sys
from pathlib import Path

import psycopg2

ENVIRONMENT_ID = "583a73aa-9c99-491d-9cbe-09064e6c9152"

ENV_PATH = Path(__file__).resolve().parents[2] / "config" / ".env"


def read_database_url(env_path: Path) -> str:
    if not env_path.exists():
        raise FileNotFoundError(f"No existe el archivo de entorno: {env_path}")

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        if key.strip() == "DATABASE_URL":
            return value.strip()

    raise ValueError(f"DATABASE_URL no esta definida en {env_path}")


def main() -> int:
    try:
        database_url = read_database_url(ENV_PATH)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1

    try:
        conn = psycopg2.connect(database_url)
    except psycopg2.OperationalError as exc:
        print(f"ERROR: no se pudo conectar a PostgreSQL ({database_url}): {exc}")
        return 1

    try:
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM corpus_versions
                WHERE corpus_metadata_id IN (
                    SELECT id FROM corpus_metadata WHERE environment_id = %s
                )
                """,
                (ENVIRONMENT_ID,),
            )
            deleted_versions = cur.rowcount

            cur.execute(
                "DELETE FROM corpus_metadata WHERE environment_id = %s",
                (ENVIRONMENT_ID,),
            )
            deleted = cur.rowcount
        conn.commit()
    except Exception as exc:
        conn.rollback()
        print(f"ERROR al eliminar registros: {type(exc).__name__}: {exc}")
        return 1
    finally:
        conn.close()

    print(f"Eliminados {deleted_versions} registro(s) de corpus_versions para environment_id={ENVIRONMENT_ID}")
    print(f"Eliminados {deleted} registro(s) de corpus_metadata para environment_id={ENVIRONMENT_ID}")
    print("ChromaDB no fue modificado en esta operacion (solo se tocó PostgreSQL).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
