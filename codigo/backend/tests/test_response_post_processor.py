# -*- coding: utf-8 -*-
"""Pruebas del post-procesado de la respuesta.

Cada caso reproduce una forma de respuesta observada en el sistema, en modo local
y en modo nube, no un caso hipotetico.

No llaman al modelo ni a la base de datos.

COMO EJECUTARLAS, igual que test_artifact_engine.py:

    docker cp codigo/backend/tests asistente_fastapi:/app/tests
    docker exec -e PYTHONPATH=/app asistente_fastapi python /app/tests/test_response_post_processor.py
"""
import sys

from app.services.prompt_builder import SUGGESTIONS_BLOCK_END, SUGGESTIONS_BLOCK_START
from app.services.response_post_processor import ResponsePostProcessor

CHUNKS = [
    {"chunk_id": "c1", "filename": "Presentacion Sesion 13.pdf", "page_number": 16, "score": 0.81},
]


def procesa(bruta: str) -> dict:
    return ResponsePostProcessor().process(bruta, CHUNKS, False)


# --------------------------------------------------- lo que ya funcionaba

def test_bloque_bien_formado_se_extrae_y_no_ensucia_la_respuesta():
    """El camino de Claude. Esta prueba es la regresion: no puede cambiar."""
    bruta = (
        "Pandas es una biblioteca de Python para manipulacion de datos "
        "(Presentacion Sesion 13.pdf, pagina 16).\n\n"
        f"{SUGGESTIONS_BLOCK_START}\n"
        "Que es un DataFrame?\n"
        "Como se carga un CSV con pandas?\n"
        "Que diferencia hay con NumPy?\n"
        f"{SUGGESTIONS_BLOCK_END}"
    )
    r = procesa(bruta)
    assert r["answer"] == (
        "Pandas es una biblioteca de Python para manipulacion de datos "
        "(Presentacion Sesion 13.pdf, pagina 16)."
    )
    assert r["suggestions"] == [
        "Que es un DataFrame?",
        "Como se carga un CSV con pandas?",
        "Que diferencia hay con NumPy?",
    ]


def test_sin_bloque_la_respuesta_queda_intacta():
    bruta = "Una clave foranea es una restriccion referencial entre dos tablas."
    r = procesa(bruta)
    assert r["answer"] == bruta
    assert r["suggestions"] == []


def test_numeracion_y_guiones_se_limpian_de_las_sugerencias():
    bruta = (
        "Respuesta con fundamento suficiente para el estudiante.\n\n"
        f"{SUGGESTIONS_BLOCK_START}\n"
        "1. Primera pregunta?\n"
        "- Segunda pregunta?\n"
        "2) Tercera pregunta?\n"
        f"{SUGGESTIONS_BLOCK_END}"
    )
    assert procesa(bruta)["suggestions"] == [
        "Primera pregunta?", "Segunda pregunta?", "Tercera pregunta?"
    ]


def test_nunca_devuelve_mas_de_tres_sugerencias():
    bruta = (
        "Respuesta.\n\n" + SUGGESTIONS_BLOCK_START + "\n"
        + "\n".join(f"Pregunta {i}?" for i in range(1, 8)) + "\n"
        + SUGGESTIONS_BLOCK_END
    )
    assert len(procesa(bruta)["suggestions"]) == 3


# ------------------------------------- el marcador que llegaba al estudiante

def test_apertura_sin_cierre_no_deja_el_marcador_a_la_vista():
    """Medido en modo local: 3 de 15 respuestas mostraban la etiqueta."""
    bruta = (
        f"{SUGGESTIONS_BLOCK_START}\n\n"
        "La desnormalizacion es un proceso de transformar los datos para "
        "consultarlos mas rapido."
    )
    r = procesa(bruta)
    assert SUGGESTIONS_BLOCK_START not in r["answer"]
    assert r["answer"].startswith("La desnormalizacion")
    assert r["suggestions"] == []


def test_cierre_sin_apertura_tampoco():
    bruta = f"{SUGGESTIONS_BLOCK_END}\n\nLa limpieza de datos elimina duplicados y nulos."
    r = procesa(bruta)
    assert SUGGESTIONS_BLOCK_END not in r["answer"]
    assert r["answer"] == "La limpieza de datos elimina duplicados y nulos."


def test_etiqueta_al_principio_no_se_lleva_la_respuesta_por_delante():
    """El modelo pequeno la pone al PRINCIPIO, no al final.

    Cortar desde una etiqueta sin pareja hasta el final -que es la regla
    intuitiva- borraria la respuesta entera.
    """
    bruta = f"{SUGGESTIONS_BLOCK_START}\n\n" + "A" * 400
    r = procesa(bruta)
    assert len(r["answer"]) == 400


def test_etiquetas_repetidas_en_un_dialogo_inventado():
    """Caso real de llama3.2:1b: se inventa los turnos de los dos lados."""
    bruta = (
        "Una clave foranea es una restriccion entre tablas.\n"
        f"Estudiante: {SUGGESTIONS_BLOCK_START}\n\n"
        f"Sistema: {SUGGESTIONS_BLOCK_START}\n\n"
        "La regularizacion es un enfoque de entrenamiento."
    )
    r = procesa(bruta)
    assert "[[" not in r["answer"]
    assert "Una clave foranea" in r["answer"]
    assert "La regularizacion" in r["answer"]


# ------------------------------- los corchetes desbalanceados

def test_cierre_con_un_corchete_de_menos_se_extrae_igual():
    """Caso literal observado en una prueba por la interfaz, en modo local.

    El modelo cierra con "[/SUGERENCIAS]]". Si el bloque no casara, el
    estudiante veria el marcador y las tres preguntas se quedarian dentro del
    texto de la respuesta.
    """
    bruta = (
        "La normalizacion escala las variables a un rango de 0 a 1 "
        "(Presentacion Sesion 19.pdf, pagina 21).\n\n"
        f"{SUGGESTIONS_BLOCK_START}\n"
        "Cual es la diferencia entre normalizacion y estandarizacion?\n"
        "Como se implementa con MinMaxScaler?\n"
        "Que pasa si un modelo es sensible a la escala?\n"
        "[/SUGERENCIAS]]"
    )
    r = procesa(bruta)
    assert "SUGERENCIAS" not in r["answer"]
    assert r["answer"].startswith("La normalizacion escala")
    assert len(r["suggestions"]) == 3
    assert r["suggestions"][0] == "Cual es la diferencia entre normalizacion y estandarizacion?"


def test_apertura_con_un_solo_corchete_tampoco_deja_marcador():
    bruta = (
        "[SUGERENCIAS]\n"
        "Que es un DataFrame?\n"
        "Como se carga un CSV?\n"
        "Que diferencia hay con NumPy?\n"
        f"{SUGGESTIONS_BLOCK_END}"
    )
    r = procesa(bruta)
    assert "SUGERENCIAS" not in r["answer"]
    assert len(r["suggestions"]) == 3


def test_una_etiqueta_suelta_mal_cerrada_se_limpia_sin_cortar_la_respuesta():
    bruta = "[/SUGERENCIAS]]\n\nLa matriz de correlacion muestra la relacion entre variables."
    r = procesa(bruta)
    assert "SUGERENCIAS" not in r["answer"]
    assert r["answer"] == "La matriz de correlacion muestra la relacion entre variables."


def test_la_palabra_en_minusculas_entre_corchetes_no_se_toca():
    """El limite del patron: solo se reconoce la etiqueta en MAYUSCULAS.

    Sin esta barrera, limpiar por la palabra borraria texto legitimo.
    """
    bruta = "El docente puede escribir [sugerencias] en el campo de observaciones."
    assert procesa(bruta)["answer"] == bruta


# ------------------------------------------- la burbuja vacia y el codigo

def test_bloque_que_es_toda_la_respuesta_no_deja_al_estudiante_sin_nada():
    """Medido en modo local: 'para que sirve pandas' llego con 0 caracteres."""
    bruta = (
        f"{SUGGESTIONS_BLOCK_START}\n"
        "Que es un DataFrame?\n"
        "Como se carga un CSV?\n"
        "Que diferencia hay con NumPy?\n"
        f"{SUGGESTIONS_BLOCK_END}"
    )
    r = procesa(bruta)
    assert r["answer"], "el estudiante no puede recibir una respuesta vacia"
    assert "[[" not in r["answer"]


def test_el_codigo_con_dobles_corchetes_sobrevive():
    """`data[['columna']]` de pandas aparece en respuestas reales del corpus.

    Limpiar por "[[" en vez de por la etiqueta literal lo destrozaria.
    """
    bruta = (
        "Para normalizar una variable:\n\n"
        "```python\n"
        "scaler = MinMaxScaler()\n"
        "data_scaled = scaler.fit_transform(data[['variable_numerica']])\n"
        "```\n\n"
        "(Presentacion Sesion 16.pdf, pagina 21)"
    )
    r = procesa(bruta)
    assert "data[['variable_numerica']]" in r["answer"]


def test_respuesta_vacia_o_nula_no_revienta():
    assert procesa("")["answer"] == ""
    assert ResponsePostProcessor().process(None, CHUNKS, False)["answer"] is None


# ---------------------------------------------------- el resto del contrato

def test_las_fuentes_y_el_umbral_pasan_tal_cual():
    r = ResponsePostProcessor().process("Respuesta cualquiera.", CHUNKS, True)
    assert r["below_threshold"] is True
    assert r["sources"] == [
        {"chunk_id": "c1", "filename": "Presentacion Sesion 13.pdf", "page_number": 16, "score": 0.81}
    ]


# --------------------------------------------------------------------------

def _ejecutar():
    pruebas = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    fallos = []
    for nombre, prueba in pruebas:
        try:
            prueba()
            print(f"  OK    {nombre}")
        except AssertionError as exc:
            fallos.append(nombre)
            print(f"  FALLA {nombre}  {exc}")
        except Exception as exc:  # noqa: BLE001
            fallos.append(nombre)
            print(f"  ERROR {nombre}  {type(exc).__name__}: {exc}")
    print(f"\n{len(pruebas) - len(fallos)} de {len(pruebas)} pruebas correctas")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(_ejecutar())
