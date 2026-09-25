# -*- coding: utf-8 -*-
"""Registro de operaciones del modulo.

Cada operacion que cambia algo deja una linea aqui: que se hizo, sobre que, y
cuando. Sirve para dos cosas concretas -saber quien quedo dado de alta y poder
deshacer- y vive DENTRO del modulo, en su propia carpeta.

Por que no se escribe en la base del sistema: porque el modulo no debe dejar
rastro dentro de lo que administra. Si se borrara el modulo, el sistema queda
identico y sin residuos suyos.

Las contrasenas NO entran en el registro, ni en claro ni cifradas. Se registra
que se genero una, no cual.
"""
import io
import json
from datetime import datetime

from contexto import DIR_MODULO

ARCHIVO = DIR_MODULO / "operaciones.jsonl"


def anota(accion, detalle=None, resultado="ok"):
    """Deja constancia de una operacion. Nunca falla el flujo por no poder anotar."""
    linea = {
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "accion": accion,
        "detalle": detalle or {},
        "resultado": resultado,
    }
    try:
        with io.open(ARCHIVO, "a", encoding="utf-8") as f:
            f.write(json.dumps(linea, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return linea


def ultimas(n=20):
    """Las ultimas operaciones, de la mas reciente a la mas antigua."""
    if not ARCHIVO.is_file():
        return []
    with io.open(ARCHIVO, encoding="utf-8") as f:
        lineas = [l.strip() for l in f if l.strip()]
    salida = []
    for l in reversed(lineas[-n:]):
        try:
            salida.append(json.loads(l))
        except json.JSONDecodeError:
            continue
    return salida
