# -*- coding: utf-8 -*-
"""Rompe a proposito cada comportamiento y comprueba que la prueba correspondiente
lo detecta. Una bateria que solo se ha visto en verde no demuestra que mire."""
import sys, io, importlib
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "/app"); sys.path.insert(0, "/app/tests")

import app.services.artifact_generation_engine as motor
import test_artifact_engine as suite

def corre(nombre):
    try:
        getattr(suite, nombre)(); return "pasa"
    except AssertionError:
        return "detecta"
    except Exception as e:
        return f"error {type(e).__name__}"

SIEMBRAS = [
    ("deteccion de tipo",        lambda: setattr(motor, "_TYPE_KEYWORDS", []),                      "test_infer_reconoce_cada_tipo"),
    ("recorte de la consulta",   lambda: setattr(motor, "build_retrieval_query", lambda t: t),      "test_build_retrieval_query_quita_la_peticion"),
    ("validacion de citas",      lambda: setattr(motor, "invalid_citations", lambda t, c: set()),   "test_detecta_cita_de_pagina_que_no_se_entrego"),
    ("catalogo de tipos",        lambda: motor.ARTIFACT_SPECS.pop(motor.ArtifactType.cuestionario), "test_todos_los_tipos_tienen_especificacion"),
]
print("cada linea rompe un comportamiento y comprueba que la prueba lo ve:\n")
ok = 0
for etiqueta, romper, prueba in SIEMBRAS:
    antes = corre(prueba)
    romper()
    importlib.reload(suite)          # la suite reimporta del modulo ya roto
    despues = corre(prueba)
    bien = antes == "pasa" and despues == "detecta"
    ok += bien
    print(f"  {'OK   ' if bien else 'FALLA'} {etiqueta:26} intacto={antes:8} roto={despues}")
    importlib.reload(motor); importlib.reload(suite)   # se restaura para la siguiente
print(f"\ncontroles que la bateria detecta: {ok} de {len(SIEMBRAS)}")
