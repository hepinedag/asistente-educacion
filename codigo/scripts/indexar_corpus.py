"""Sube todos los PDF de corpus/fuente/ al entorno piloto via POST /corpus/upload.

Con --purgar, antes vacia el corpus del entorno (DELETE /corpus/environment/{id}),
que elimina tambien su coleccion del indice. Hace falta
cuando el indice tiene la dimension de otro modelo de embeddings: subir sin
purgar falla en todos los documentos ("Collection expecting embedding with
dimension of 1024, got 384"), porque la coleccion conserva la dimension con que
se creo. Lo usa iniciar_sistema.bat cuando el indice no corresponde al modo
configurado.

Uso:
    python codigo/scripts/indexar_corpus.py
    python codigo/scripts/indexar_corpus.py --purgar
"""

import sys
from pathlib import Path

import httpx

BASE_URL = "http://localhost:8000"
ADMIN_EMAIL = "admin@test.com"
ADMIN_PASSWORD = "password123"
ENVIRONMENT_ID = "583a73aa-9c99-491d-9cbe-09064e6c9152"

CORPUS_DIR = Path(__file__).resolve().parents[2] / "corpus" / "fuente"
REQUEST_TIMEOUT = 60.0


def login(client: httpx.Client) -> str:
    response = client.post(
        f"{BASE_URL}/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def purge_environment(client: httpx.Client, token: str) -> dict:
    response = client.request(
        "DELETE",
        f"{BASE_URL}/corpus/environment/{ENVIRONMENT_ID}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=120.0,
    )
    response.raise_for_status()
    return response.json()


def upload_pdf(client: httpx.Client, token: str, pdf_path: Path) -> dict:
    with pdf_path.open("rb") as file_obj:
        response = client.post(
            f"{BASE_URL}/corpus/upload",
            headers={"Authorization": f"Bearer {token}"},
            data={"environment_id": ENVIRONMENT_ID},
            files={"file": (pdf_path.name, file_obj, "application/pdf")},
            timeout=REQUEST_TIMEOUT,
        )
    response.raise_for_status()
    return response.json()


def extract_detail(response: httpx.Response) -> str:
    try:
        return str(response.json().get("detail", response.text))
    except Exception:
        return response.text


def main() -> int:
    purgar = "--purgar" in sys.argv[1:]

    if not CORPUS_DIR.exists():
        print(f"ERROR: no existe el directorio del corpus: {CORPUS_DIR}")
        return 1

    pdf_files = sorted(
        file_path
        for pattern in ("*.pdf", "*.docx", "*.md")
        for file_path in CORPUS_DIR.glob(pattern)
    )
    if not pdf_files:
        print(f"No se encontraron archivos PDF, DOCX o MD en {CORPUS_DIR}")
        return 0

    print(f"Encontrados {len(pdf_files)} archivo(s) en {CORPUS_DIR}")

    with httpx.Client() as client:
        try:
            token = login(client)
        except httpx.HTTPError as exc:
            print(f"ERROR: no se pudo autenticar como {ADMIN_EMAIL}: {type(exc).__name__}: {exc}")
            return 1

        print(f"Autenticado como {ADMIN_EMAIL}")

        if purgar:
            try:
                result = purge_environment(client, token)
                print(f"Corpus del entorno vaciado: {len(result.get('deleted', []))} documento(s), "
                      f"{result.get('total_chunks_deleted', 0)} chunks; coleccion del indice eliminada")
            except httpx.HTTPStatusError as exc:
                print(f"ERROR al purgar -> HTTP {exc.response.status_code}: {extract_detail(exc.response)}")
                return 1
            except httpx.HTTPError as exc:
                print(f"ERROR al purgar -> {type(exc).__name__}: {exc}")
                return 1

        print("-" * 60)

        exitosos = 0
        fallidos = 0
        total_chunks = 0

        for pdf_path in pdf_files:
            try:
                result = upload_pdf(client, token, pdf_path)
                chunks_created = result.get("chunks_created", 0)
                total_chunks += chunks_created
                exitosos += 1
                print(
                    f"OK    {pdf_path.name} -> chunks_created={chunks_created} "
                    f"document_id={result.get('document_id')}"
                )
            except httpx.HTTPStatusError as exc:
                fallidos += 1
                print(f"ERROR {pdf_path.name} -> HTTP {exc.response.status_code}: {extract_detail(exc.response)}")
            except httpx.HTTPError as exc:
                fallidos += 1
                print(f"ERROR {pdf_path.name} -> {type(exc).__name__}: {exc}")
            except Exception as exc:
                fallidos += 1
                print(f"ERROR {pdf_path.name} -> {type(exc).__name__}: {exc}")

    print("-" * 60)
    print(f"Resumen: {exitosos} exitosos, {fallidos} fallidos, {total_chunks} chunks totales creados")

    return 0 if fallidos == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
