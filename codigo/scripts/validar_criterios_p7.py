"""Ejecuta CT-1, CT-2, CT-3 y un proxy etiquetado "CT-5" contra POST /conversation/message real.

IMPORTANTE - leer antes de interpretar el reporte: estos son criterios automatizados
simplificados, no la metodologia formal completa de P7_Criterios_Validacion.md:

  - CT-1 real exige evaluacion MANUAL de pertinencia sobre 20 consultas (juzgar si el
    top-5 de chunks responde la pregunta). Aqui se aproxima con el flag automatico
    `below_threshold` sobre las 10 CONSULTAS_CORPUS. below_threshold=False no garantiza
    que el contenido recuperado sea realmente pertinente, solo que supero el umbral de
    score de SemanticValidator.
  - CT-2 y CT-3 si siguen de cerca la metodologia y los umbrales reales de P7 (CT-3 usa
    20 mediciones en este lote, no las 50 que recomienda P7).
  - La etiqueta "CT-5" usada aqui NO es el CT-5 real de P7 (que mide persistencia del
    historial de sesion entre reconexiones, Fase 4, via SessionContextManager /
    LongTermMemoryManager - componentes que todavia no existen en el codigo). Lo que
    se mide aqui (fuentes citadas no vacias en CONSULTAS_CORPUS) es un proxy de
    fundamentacion de la respuesta, mas cercano a CP-2 ("Respuestas fundamentadas
    exclusivamente en el corpus") que a cualquier CT formal.

Uso: python codigo/scripts/validar_criterios_p7.py
"""

import sys
import time
from dataclasses import dataclass

import httpx

BASE_URL = "http://localhost:8000"
STUDENT_EMAIL = "student@test.com"
STUDENT_PASSWORD = "password123"
ENVIRONMENT_ID = "583a73aa-9c99-491d-9cbe-09064e6c9152"

REQUEST_TIMEOUT = 120.0

CONSULTAS_CORPUS = [
    "Que es el analisis exploratorio de datos?",
    "Como se hace una consulta SELECT con JOIN en SQL?",
    "Que diferencia hay entre aprendizaje supervisado y no supervisado?",
    "Para que sirve la libreria pandas en Python?",
    "Como se calcula la matriz de confusion en un modelo de clasificacion?",
    "Que es el sobreajuste (overfitting) en machine learning?",
    "Como se normalizan los datos antes de entrenar un modelo?",
    "Que es una clave foranea en una base de datos relacional?",
    "Para que se usa la validacion cruzada (cross-validation)?",
    "Como se interpreta un coeficiente de correlacion?",
]

CONSULTAS_FUERA = [
    "Cual es la receta tradicional de la paella valenciana?",
    "Quien gano el mundial de futbol de 2018?",
    "Que causo la caida del Imperio Romano de Occidente?",
    "Cuales son los ingredientes de un buen tiramisu?",
    "Que reglas tiene el ajedrez para el enroque?",
    "Como se cultivan tomates en una huerta casera?",
    "Cuales fueron las causas de la Primera Guerra Mundial?",
    "Que diferencia hay entre el yoga y el pilates?",
    "Como se entrena un perro para que se sienta?",
    "Que dinastia gobernaba Francia durante la Edad Media?",
]


@dataclass
class ResultadoConsulta:
    pregunta: str
    grupo: str
    ok: bool
    below_threshold: bool | None = None
    sources_count: int = 0
    tiempo_segundos: float = 0.0
    error: str | None = None


def login(client: httpx.Client) -> str:
    response = client.post(
        f"{BASE_URL}/auth/login",
        json={"email": STUDENT_EMAIL, "password": STUDENT_PASSWORD},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def extract_detail(response: httpx.Response) -> str:
    try:
        return str(response.json().get("detail", response.text))
    except Exception:
        return response.text


def enviar_consulta(client: httpx.Client, token: str, pregunta: str, grupo: str) -> ResultadoConsulta:
    inicio = time.perf_counter()
    try:
        response = client.post(
            f"{BASE_URL}/conversation/message",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": pregunta, "environment_id": ENVIRONMENT_ID},
            timeout=REQUEST_TIMEOUT,
        )
        tiempo = time.perf_counter() - inicio
        response.raise_for_status()
        data = response.json()
        return ResultadoConsulta(
            pregunta=pregunta,
            grupo=grupo,
            ok=True,
            below_threshold=data.get("below_threshold"),
            sources_count=len(data.get("sources") or []),
            tiempo_segundos=tiempo,
        )
    except httpx.HTTPStatusError as exc:
        return ResultadoConsulta(
            pregunta=pregunta,
            grupo=grupo,
            ok=False,
            tiempo_segundos=time.perf_counter() - inicio,
            error=f"HTTP {exc.response.status_code}: {extract_detail(exc.response)}",
        )
    except httpx.HTTPError as exc:
        return ResultadoConsulta(
            pregunta=pregunta,
            grupo=grupo,
            ok=False,
            tiempo_segundos=time.perf_counter() - inicio,
            error=f"{type(exc).__name__}: {exc}",
        )


def percentil(valores: list[float], p: float) -> float:
    if not valores:
        return 0.0
    ordenados = sorted(valores)
    k = (len(ordenados) - 1) * (p / 100)
    f = int(k)
    c = min(f + 1, len(ordenados) - 1)
    if f == c:
        return ordenados[f]
    return ordenados[f] + (ordenados[c] - ordenados[f]) * (k - f)


def imprimir_resultado(r: ResultadoConsulta) -> None:
    if not r.ok:
        print(f"  ERROR ({r.tiempo_segundos:.2f}s) {r.pregunta!r} -> {r.error}")
        return
    print(
        f"  OK    ({r.tiempo_segundos:.2f}s) below_threshold={r.below_threshold} "
        f"sources={r.sources_count} | {r.pregunta!r}"
    )


def generar_reporte(resultados: list[ResultadoConsulta]) -> int:
    corpus = [r for r in resultados if r.grupo == "corpus"]
    fuera = [r for r in resultados if r.grupo == "fuera"]

    ct1_count = sum(1 for r in corpus if r.ok and r.below_threshold is False)
    ct1_total = len(corpus)
    ct1_pass = ct1_count >= 8

    ct2_count = sum(1 for r in fuera if r.ok and r.below_threshold is True)
    ct2_total = len(fuera)
    ct2_pass = ct2_count >= 9

    tiempos = [r.tiempo_segundos for r in resultados if r.ok]
    p50 = percentil(tiempos, 50)
    p95 = percentil(tiempos, 95)
    ct3_pass = p50 < 5.0 and p95 < 10.0

    ct5_count = sum(1 for r in corpus if r.ok and r.sources_count > 0)
    ct5_total = len(corpus)
    ct5_pass = ct5_count >= 9

    print("=" * 64)
    print("REPORTE DE CRITERIOS TECNICOS (ver P7_Criterios_Validacion.md)")
    print("=" * 64)
    print(f"CT-1: {ct1_count}/{ct1_total} >= 8   -> {'PASS' if ct1_pass else 'FAIL'}")
    print(f"CT-2: {ct2_count}/{ct2_total} >= 9   -> {'PASS' if ct2_pass else 'FAIL'}")
    print(f"CT-3: p50={p50:.2f}s p95={p95:.2f}s (umbral p50<5s, p95<10s) -> {'PASS' if ct3_pass else 'FAIL'}")
    print(f"CT-5: {ct5_count}/{ct5_total} >= 9   -> {'PASS' if ct5_pass else 'FAIL'}  [proxy, NO es el CT-5 real de P7]")
    print("=" * 64)

    fallidas = [r for r in resultados if not r.ok]
    if fallidas:
        print(f"\n{len(fallidas)} consulta(s) con error de transporte/HTTP (excluidas de los conteos):")
        for r in fallidas:
            print(f"  - {r.pregunta!r}: {r.error}")

    print(
        "\nNOTA: ver el docstring de este script para el detalle de en que se aparta cada\n"
        "criterio de aqui de la metodologia formal de P7_Criterios_Validacion.md. En resumen:\n"
        "CT-1 es un proxy automatico (no evaluacion manual); CT-3 usa 20 mediciones, no 50;\n"
        "la etiqueta 'CT-5' aqui NO corresponde al CT-5 real de P7 (persistencia de sesion,\n"
        "Fase 4) - mide presencia de fuentes citadas, un proxy de fundamentacion (CP-2)."
    )

    return 0 if (ct1_pass and ct2_pass and ct3_pass and ct5_pass) else 1


def main() -> int:
    print(f"Autenticando como {STUDENT_EMAIL}...")
    with httpx.Client() as client:
        try:
            token = login(client)
        except httpx.HTTPError as exc:
            print(f"ERROR: no se pudo autenticar: {type(exc).__name__}: {exc}")
            return 1

        print("Autenticado. Ejecutando consultas...\n")
        resultados: list[ResultadoConsulta] = []

        print("--- CONSULTAS_CORPUS ---")
        for pregunta in CONSULTAS_CORPUS:
            r = enviar_consulta(client, token, pregunta, "corpus")
            resultados.append(r)
            imprimir_resultado(r)

        print("\n--- CONSULTAS_FUERA ---")
        for pregunta in CONSULTAS_FUERA:
            r = enviar_consulta(client, token, pregunta, "fuera")
            resultados.append(r)
            imprimir_resultado(r)

    print()
    return generar_reporte(resultados)


if __name__ == "__main__":
    sys.exit(main())
