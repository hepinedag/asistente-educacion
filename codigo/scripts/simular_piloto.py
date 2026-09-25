"""Piloto simulado del Asistente de Educacion.

Genera interacciones REALES con el sistema (login real, POST /conversation/message
real, respuestas reales de Claude/Cohere/reranker) para Ana Garcia, Carlos Lopez y
Maria Torres, con un componente aleatorio (numero de sesiones y de mensajes por
sesion) que determina, como consecuencia y no por asignacion previa, la
clasificacion profundiza/superficial que ya calcula GET /teacher/dashboard.

Los mensajes de seguimiento dentro de una sesion se eligen entre los chips de
`suggestions` devueltos por la respuesta anterior -- no hay banco de
seguimiento propio porque el script habla con el sistema real.

Al final de la Fase 1 se re-fechan retroactivamente las marcas de tiempo a una
ventana de 3 semanas ISO terminando hoy. El contenido conversacional es real;
solo la metadata temporal se desplaza. Ver disclosure en la propuesta aprobada.
"""

import random
from datetime import datetime, timedelta, timezone

import httpx
import psycopg2

BASE_URL = "http://localhost:8000"
ENVIRONMENT_ID = "583a73aa-9c99-491d-9cbe-09064e6c9152"
SEED = 20260710

DB_DSN = "dbname=asistente_educacion user=postgres password=postgres host=localhost port=5432"

STUDENTS = [
    {"name": "Ana García", "email": "estudiante1@test.com", "password": "password123",
     "id": "f6f7649d-7841-452f-9980-c9833392a22d"},
    {"name": "Carlos López", "email": "estudiante2@test.com", "password": "password123",
     "id": "c687bdc7-3c64-4819-aa4d-7c876d12826d"},
    {"name": "María Torres", "email": "estudiante3@test.com", "password": "password123",
     "id": "66b5dc52-5fee-45b2-94e3-75ef7f209abb"},
]

QUESTION_BANK = [
    "¿Qué es un DataFrame en pandas?",
    "¿Qué es una Serie en pandas?",
    "¿Cómo se usan dropna y fillna en pandas para manejar valores faltantes?",
    "¿Para qué sirve la función groupby de pandas?",
    "¿Qué es la validación cruzada k-fold y por qué se prefiere sobre una sola partición train/test?",
    "¿Qué es el overfitting y cómo se detecta?",
    "¿Cuáles son las formas de escalar variables antes de entrenar un modelo?",
    "¿Qué son los índices en bases de datos relacionales y cuándo usarlos?",
    "¿Cómo funcionan los joins en SQL?",
    "¿Qué es el modelado dimensional y cuál es su principal desventaja?",
    "¿Cómo funciona el algoritmo Random Forest?",
]

# Pregunta deliberada fuera de corpus -- no aleatoria, un solo caso, asignada a
# la ultima sesion de Maria Torres (evidencia real de below_threshold).
OFF_CORPUS_QUESTION = "¿Cómo se prepara un café espresso perfecto?"
OFF_CORPUS_STUDENT_EMAIL = "estudiante3@test.com"

MIN_SESSIONS, MAX_SESSIONS = 1, 4
MIN_MESSAGES, MAX_MESSAGES = 1, 8

WEEK_ANCHORS = [
    datetime(2026, 6, 22, tzinfo=timezone.utc),
    datetime(2026, 6, 29, tzinfo=timezone.utc),
    datetime(2026, 7, 6, tzinfo=timezone.utc),
]


def login(client: httpx.Client, email: str, password: str) -> str:
    resp = client.post(f"{BASE_URL}/auth/login", json={"email": email, "password": password})
    resp.raise_for_status()
    return resp.json()["access_token"]


def send_message(client: httpx.Client, token: str, message: str) -> dict:
    resp = client.post(
        f"{BASE_URL}/conversation/message",
        json={"message": message, "environment_id": ENVIRONMENT_ID},
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    return resp.json()


def close_active_session(conn, student_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sessions SET status='closed', ended_at=now() "
            "WHERE student_id=%s AND environment_id=%s AND status='active'",
            (student_id, ENVIRONMENT_ID),
        )
    conn.commit()


def run_fase1():
    random.seed(SEED)
    conn = psycopg2.connect(DB_DSN)
    log = []

    with httpx.Client(timeout=60.0) as client:
        for student in STUDENTS:
            token = login(client, student["email"], student["password"])
            num_sessions = random.randint(MIN_SESSIONS, MAX_SESSIONS)
            print(f"\n=== {student['name']} ({student['email']}) -> {num_sessions} sesion(es) ===")

            for session_index in range(1, num_sessions + 1):
                num_messages = random.randint(MIN_MESSAGES, MAX_MESSAGES)
                is_last_session = session_index == num_sessions
                inject_off_corpus = (
                    student["email"] == OFF_CORPUS_STUDENT_EMAIL and is_last_session
                )
                print(f"  Sesión {session_index}: {num_messages} mensaje(s) planificado(s)"
                      + (" + 1 fuera de corpus" if inject_off_corpus else ""))

                last_response = None
                for turn in range(1, num_messages + 1):
                    if turn == 1:
                        message = random.choice(QUESTION_BANK)
                    else:
                        suggestions = (last_response or {}).get("suggestions") or []
                        message = random.choice(suggestions) if suggestions else random.choice(QUESTION_BANK)

                    result = send_message(client, token, message)
                    last_response = result
                    below = result.get("below_threshold")
                    n_sources = len(result.get("sources") or [])
                    n_suggestions = len(result.get("suggestions") or [])
                    print(f"    [{turn}] \"{message[:70]}\" -> below_threshold={below}, "
                          f"sources={n_sources}, suggestions={n_suggestions}")
                    log.append({
                        "student": student["name"], "session": session_index, "turn": turn,
                        "message": message, "below_threshold": below,
                        "sources": n_sources, "suggestions": n_suggestions,
                    })

                if inject_off_corpus:
                    result = send_message(client, token, OFF_CORPUS_QUESTION)
                    below = result.get("below_threshold")
                    print(f"    [fuera de corpus] \"{OFF_CORPUS_QUESTION}\" -> below_threshold={below}")
                    log.append({
                        "student": student["name"], "session": session_index, "turn": "fuera_de_corpus",
                        "message": OFF_CORPUS_QUESTION, "below_threshold": below,
                        "sources": len(result.get("sources") or []), "suggestions": 0,
                    })

                close_active_session(conn, student["id"])

    conn.close()
    return log


def refechar_retroactivamente():
    """Desplaza cada sesion (y sus conversaciones) generada en esta corrida a una
    semana aleatoria de WEEK_ANCHORS, preservando el orden relativo interno."""
    conn = psycopg2.connect(DB_DSN)
    student_ids = tuple(s["id"] for s in STUDENTS)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, started_at FROM sessions "
            "WHERE student_id IN %s AND environment_id = %s "
            "AND started_at >= now() - interval '2 hours'",
            (student_ids, ENVIRONMENT_ID),
        )
        sessions = cur.fetchall()

    print(f"\nRe-fechando {len(sessions)} sesion(es) generadas en esta corrida...")
    for session_id, started_at in sessions:
        week_anchor = random.choice(WEEK_ANCHORS)
        day_offset = random.randint(0, 6)
        hour_offset = random.randint(8, 21)
        minute_offset = random.randint(0, 59)
        new_anchor = week_anchor + timedelta(days=day_offset, hours=hour_offset, minutes=minute_offset)
        shift = new_anchor - started_at

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE conversations SET created_at = created_at + %s WHERE session_id = %s",
                (shift, session_id),
            )
            cur.execute(
                "UPDATE sessions SET started_at = started_at + %s, "
                "ended_at = CASE WHEN ended_at IS NOT NULL THEN ended_at + %s ELSE ended_at END "
                "WHERE id = %s",
                (shift, shift, session_id),
            )
        conn.commit()
        print(f"  sesión {session_id[:8]}... -> nueva fecha ancla {new_anchor.date()}")

    conn.close()


if __name__ == "__main__":
    resultado = run_fase1()
    refechar_retroactivamente()
    print(f"\nFase 1 completada. {len(resultado)} mensajes de estudiante enviados en total.")
