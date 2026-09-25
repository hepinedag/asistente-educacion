"""Prueba del criterio CT-7 ("Control de acceso por rol (RBAC)") contra
el backend real: intentos de acceso con rol incorrecto o sin token a endpoints protegidos.

Uso: python codigo/scripts/validar_ct7.py
"""

import sys

import httpx

BASE_URL = "http://localhost:8000"
ADMIN_EMAIL = "admin@test.com"
ADMIN_PASSWORD = "password123"
STUDENT_EMAIL = "student@test.com"
STUDENT_PASSWORD = "password123"

ENVIRONMENT_ID = "583a73aa-9c99-491d-9cbe-09064e6c9152"
REQUEST_TIMEOUT = 30.0


def login(client: httpx.Client, email: str, password: str) -> str:
    response = client.post(
        f"{BASE_URL}/auth/login",
        json={"email": email, "password": password},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def describir(response: httpx.Response) -> str:
    try:
        body = response.json()
    except Exception:
        return response.text[:200]
    if isinstance(body, dict):
        return str(body.get("detail", body))[:200]
    return str(body)[:200]


def evaluar(response: httpx.Response, esperado: int) -> tuple[bool, str]:
    ok = response.status_code == esperado
    detalle = f"esperado={esperado} obtenido={response.status_code} body={describir(response)}"
    return ok, detalle


def prueba_1_student_lista_usuarios(client: httpx.Client, student_token: str) -> tuple[bool, str]:
    response = client.get(
        f"{BASE_URL}/auth/users",
        headers={"Authorization": f"Bearer {student_token}"},
        timeout=REQUEST_TIMEOUT,
    )
    return evaluar(response, 403)


def prueba_2_student_sube_corpus(client: httpx.Client, student_token: str) -> tuple[bool, str]:
    response = client.post(
        f"{BASE_URL}/corpus/upload",
        headers={"Authorization": f"Bearer {student_token}"},
        data={"environment_id": ENVIRONMENT_ID},
        files={"file": ("test.pdf", b"%PDF-fake-content", "application/pdf")},
        timeout=REQUEST_TIMEOUT,
    )
    return evaluar(response, 403)


def prueba_3_sin_token_me(client: httpx.Client) -> tuple[bool, str]:
    response = client.get(f"{BASE_URL}/auth/me", timeout=REQUEST_TIMEOUT)
    return evaluar(response, 401)


def prueba_4_sin_token_mensaje(client: httpx.Client) -> tuple[bool, str]:
    response = client.post(
        f"{BASE_URL}/conversation/message",
        json={"message": "Una consulta de prueba", "environment_id": ENVIRONMENT_ID},
        timeout=REQUEST_TIMEOUT,
    )
    return evaluar(response, 401)


def prueba_5_admin_envia_mensaje(client: httpx.Client, admin_token: str) -> tuple[bool, str]:
    response = client.post(
        f"{BASE_URL}/conversation/message",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"message": "Una consulta de prueba", "environment_id": ENVIRONMENT_ID},
        timeout=REQUEST_TIMEOUT,
    )
    return evaluar(response, 403)


def main() -> int:
    print("=" * 70)
    print("VALIDACION CT-7 - Control de acceso por rol (RBAC)")
    print("=" * 70)

    with httpx.Client() as client:
        print(f"\nAutenticando como admin ({ADMIN_EMAIL}) y student ({STUDENT_EMAIL})...")
        try:
            admin_token = login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
            student_token = login(client, STUDENT_EMAIL, STUDENT_PASSWORD)
        except httpx.HTTPError as exc:
            print(f"ERROR: no se pudo autenticar: {type(exc).__name__}: {exc}")
            return 1
        print("Autenticado.")

        pruebas = [
            ("Prueba 1: student -> GET /auth/users (esperado 403)",
             lambda: prueba_1_student_lista_usuarios(client, student_token)),
            ("Prueba 2: student -> POST /corpus/upload (esperado 403)",
             lambda: prueba_2_student_sube_corpus(client, student_token)),
            ("Prueba 3: sin token -> GET /auth/me (esperado 401)",
             lambda: prueba_3_sin_token_me(client)),
            ("Prueba 4: sin token -> POST /conversation/message (esperado 401)",
             lambda: prueba_4_sin_token_mensaje(client)),
            ("Prueba 5: admin -> POST /conversation/message (esperado 403)",
             lambda: prueba_5_admin_envia_mensaje(client, admin_token)),
        ]

        resultados = []
        for nombre, fn in pruebas:
            print(f"\n--- {nombre} ---")
            ok, detalle = fn()
            print(f"  {'PASS' if ok else 'FAIL'} - {detalle}")
            resultados.append((nombre, ok, detalle))

    print("\n" + "=" * 70)
    print("REPORTE FINAL")
    print("=" * 70)
    for nombre, ok, _ in resultados:
        print(f"  {'PASS' if ok else 'FAIL'}  {nombre}")

    aprobadas = sum(1 for _, ok, _ in resultados if ok)
    veredicto = "PASS" if aprobadas == len(resultados) else "FAIL"
    print(f"\nCT-7: {aprobadas}/{len(resultados)} controles de acceso correctos -> {veredicto}")
    print("=" * 70)

    return 0 if veredicto == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
