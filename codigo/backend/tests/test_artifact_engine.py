# -*- coding: utf-8 -*-
"""Pruebas de las funciones puras del motor de artefactos.

Cada prueba fija un comportamiento observado contra el corpus real, no un caso
hipotetico.

Ninguna llama al modelo ni a la base de datos, asi que no gastan saldo de la API
y corren en menos de un segundo.

COMO EJECUTARLAS. El contenedor solo monta `backend/app`, asi que este directorio
hay que copiarlo dentro antes de correrlo:

    docker cp codigo/backend/tests asistente_fastapi:/app/tests
    docker exec -e PYTHONPATH=/app asistente_fastapi python /app/tests/test_artifact_engine.py

El dia que se anada pytest a requirements.txt, `pytest tests/` las recoge sin
tocar nada: los nombres y las aserciones ya siguen su convencion.
"""
import sys

from app.models.artifact import ArtifactType
from app.services.artifact_generation_engine import (
    ARTIFACT_SPECS,
    MAX_CONTINUATIONS,
    ArtifactGenerationEngine,
    build_retrieval_query,
    infer_artifact_type,
    invalid_citations,
)


def _motor(top_k: int = 3) -> ArtifactGenerationEngine:
    """Motor sin dependencias reales: las pruebas de aqui no llaman a ninguna."""
    return ArtifactGenerationEngine(None, None, None, None, None, top_k=top_k)


# --------------------------------------------------------------------------
# Deteccion del tipo a partir del texto del estudiante
# --------------------------------------------------------------------------

def test_infer_reconoce_cada_tipo():
    casos = {
        "hazme un resumen de lo que vimos hoy": ArtifactType.resumen,
        "quiero un esquema de este tema": ArtifactType.mapa_conceptual,
        "un mapa conceptual del pipeline": ArtifactType.mapa_conceptual,
        "dame ejercicios de aplicacion": ArtifactType.ejercicio_aplicacion,
        "plantea un caso practico": ArtifactType.caso_practico,
        "un glosario de terminos": ArtifactType.glosario,
        "quiero autoevaluarme en esto": ArtifactType.autovaloracion,
        "unas flash cards sobre ETL": ArtifactType.flash_cards,
        "tarjetas de estudio de pandas": ArtifactType.flash_cards,
        "un cuestionario sobre el ETL": ArtifactType.cuestionario,
        "preguntas de opcion multiple del EDA": ArtifactType.cuestionario,
        "un quiz de pandas": ArtifactType.cuestionario,
    }
    for texto, esperado in casos.items():
        assert infer_artifact_type(texto) == esperado, texto


def test_infer_cae_en_resumen_cuando_no_reconoce():
    # El resumen es el artefacto mas neutro: es lo que menos sorprende a quien
    # pidio algo en terminos vagos.
    assert infer_artifact_type("cualquier cosa rara") == ArtifactType.resumen
    assert infer_artifact_type("") == ArtifactType.resumen


def test_todos_los_tipos_tienen_especificacion():
    # Un tipo sin ArtifactSpec cae en el comodin 'otro' y genera algo que no es
    # lo que el estudiante pidio, sin error visible.
    for tipo in ArtifactType:
        assert tipo in ARTIFACT_SPECS, tipo


# --------------------------------------------------------------------------
# Recorte de la consulta: la peticion no es el tema
# --------------------------------------------------------------------------

def test_build_retrieval_query_quita_la_peticion():
    # Medido: "un mapa conceptual de groupby..." recuperaba con -2.90 de score,
    # el peor de todos los casos validos. Sin el preambulo sube a 1.66.
    assert build_retrieval_query("un mapa conceptual de groupby y agregacion en pandas") == (
        "groupby y agregacion en pandas"
    )
    assert build_retrieval_query("hazme un resumen de el proceso ETL") == "el proceso ETL"
    assert build_retrieval_query("glosario de terminos de limpieza") == "terminos de limpieza"


def test_build_retrieval_query_no_recorta_un_tema_normal():
    tema = "la normalizacion y el escalado de variables numericas"
    assert build_retrieval_query(tema) == tema


def test_build_retrieval_query_conserva_el_texto_si_no_queda_nada():
    # Sin esta guarda, "un resumen" se quedaria en cadena vacia y la busqueda
    # fallaria en vez de buscar algo.
    assert build_retrieval_query("un resumen") == "un resumen"


# --------------------------------------------------------------------------
# Citas inventadas
# --------------------------------------------------------------------------

CHUNKS = [
    {"filename": "Presentación Sesión 21.pdf", "page_number": 33, "text": "x"},
    {"filename": "Presentación Sesión 9.pdf", "page_number": 12, "text": "y"},
]


def test_detecta_cita_de_pagina_que_no_se_entrego():
    texto = "Segun el corpus (Presentacion Sesion 21.pdf, p. 7) los datos se limpian."
    assert ("presentacion sesion 21.pdf", 7) in invalid_citations(texto, CHUNKS)


def test_detecta_cita_de_documento_que_no_se_entrego():
    texto = "- Presentacion Sesion 20.pdf, pagina 33"
    assert ("presentacion sesion 20.pdf", 33) in invalid_citations(texto, CHUNKS)


def test_acepta_las_citas_validas_con_y_sin_tildes():
    texto = (
        "(Presentacion Sesion 21.pdf, p. 33) y ademas\n"
        "- Presentación Sesión 9.pdf, página 12"
    )
    assert invalid_citations(texto, CHUNKS) == set()


def test_el_guion_de_lista_no_convierte_una_cita_valida_en_inventada():
    # Falso positivo real: el nombre del archivo arrastraba el guion de la lista
    # y el mismo documento se comparaba como dos distintos.
    texto = "- Presentacion Sesion 21.pdf, paginas 33"
    assert invalid_citations(texto, CHUNKS) == set()


def test_texto_sin_citas_no_produce_falsos_positivos():
    assert invalid_citations("Un texto normal, sin ninguna referencia.", CHUNKS) == set()


# --------------------------------------------------------------------------
# Bloque de temas de continuacion
# --------------------------------------------------------------------------

def test_separa_el_bloque_de_continuacion_del_documento():
    texto = (
        "## Un resumen\n\ncuerpo del artefacto\n\n"
        "[[CONTINUACION]]\ntema uno\ntema dos\ntema tres\n[[/CONTINUACION]]"
    )
    cuerpo, temas = ArtifactGenerationEngine._split_continuations(texto)
    assert temas == ["tema uno", "tema dos", "tema tres"]
    assert "[[CONTINUACION]]" not in cuerpo
    assert cuerpo.startswith("## Un resumen")


def test_recorta_a_tres_temas_como_maximo():
    lineas = "\n".join(f"tema {i}" for i in range(10))
    texto = f"cuerpo\n[[CONTINUACION]]\n{lineas}\n[[/CONTINUACION]]"
    _, temas = ArtifactGenerationEngine._split_continuations(texto)
    assert len(temas) == MAX_CONTINUATIONS


def test_sin_bloque_devuelve_el_texto_intacto():
    # Nunca romper el artefacto por un bloque ausente o mal formado.
    texto = "## Un resumen\n\nsolo cuerpo"
    cuerpo, temas = ArtifactGenerationEngine._split_continuations(texto)
    assert cuerpo == texto and temas == []


def test_bloque_sin_cierre_no_mutila_el_artefacto():
    texto = "cuerpo importante\n[[CONTINUACION]]\ntema uno"
    cuerpo, temas = ArtifactGenerationEngine._split_continuations(texto)
    assert cuerpo == texto and temas == []


# --------------------------------------------------------------------------
# Anclaje al documento que motivo la propuesta
# --------------------------------------------------------------------------

def test_el_anclaje_antepone_el_documento_de_la_propuesta():
    chunks = [
        {"filename": "Sesion 9.pdf", "page_number": 12, "score": -1.0},
        {"filename": "Sesion 6.pdf", "page_number": 6, "score": -2.0},
        {"filename": "Sesion 21.pdf", "page_number": 33, "score": -3.9},
    ]
    anclados = _motor(top_k=3)._anchor(chunks, "Sesion 21.pdf")
    assert anclados[0]["filename"] == "Sesion 21.pdf"
    assert len(anclados) == 3


def test_el_anclaje_es_preferencia_y_no_filtro():
    # Si el documento anclado no aporta bastante, el resto completa: un artefacto
    # pobre pero "fiel" seria peor que uno completo.
    chunks = [
        {"filename": "Sesion 9.pdf", "page_number": 12, "score": -1.0},
        {"filename": "Sesion 6.pdf", "page_number": 6, "score": -2.0},
    ]
    anclados = _motor(top_k=3)._anchor(chunks, "Sesion 21.pdf")
    assert len(anclados) == 2


def test_sin_anclaje_solo_recorta_a_top_k():
    chunks = [{"filename": f"{i}.pdf", "page_number": i, "score": -1.0} for i in range(9)]
    assert len(_motor(top_k=3)._anchor(chunks, None)) == 3


# --------------------------------------------------------------------------
# Limpieza de la respuesta cruda
# --------------------------------------------------------------------------

def test_clean_quita_las_vallas_de_codigo():
    # Sin esto, un .md descargado se ve como un bloque de codigo en vez de como
    # documento.
    assert ArtifactGenerationEngine._clean("```markdown\n# Titulo\n\ntexto\n```") == (
        "# Titulo\n\ntexto"
    )


def test_clean_no_toca_un_artefacto_normal():
    texto = "# Titulo\n\ntexto con `codigo en linea` dentro"
    assert ArtifactGenerationEngine._clean(texto) == texto


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
