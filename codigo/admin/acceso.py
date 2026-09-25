# -*- coding: utf-8 -*-
"""La puerta del modulo cuando deja de ser una consola.

POR QUE AHORA SI Y ANTES NO. Mientras el modulo fue una consola no pedia
contrasena, y estaba bien: lo ejecutaba quien ya estaba sentado en la maquina, y
llegar hasta el era la credencial. Al pasar a servidor web la pregunta cambia de
forma -aunque escuche solo en 127.0.0.1 y no sea alcanzable desde fuera-, porque
este modulo restaura bases de datos y repone claves de API.

COMO SE FIJA. En el primer arranque el modulo la pide y la guarda cifrada. No la
elige nadie mas, no viene con un valor inicial, y no pasa por ningun archivo del
repositorio: si alguien clona el proyecto no obtiene una puerta abierta, obtiene
un modulo que pide que se le fije una contrasena.

Se cifra con `contexto.cifra`, el mismo mecanismo del sistema, para no inventar
aqui una forma distinta de guardar una contrasena.
"""
import io
import os
import secrets
import stat

import contexto

ARCHIVO = contexto.DIR_MODULO / ".acceso"

MINIMO = 8


class ErrorAcceso(Exception):
    pass


def esta_fijada():
    return ARCHIVO.is_file() and ARCHIVO.stat().st_size > 0


def fija(password, repeticion):
    """Primer arranque: guarda la contrasena cifrada. Solo si no habia una."""
    if esta_fijada():
        raise ErrorAcceso("La contrasena del modulo ya estaba fijada")
    if password != repeticion:
        raise ErrorAcceso("Las dos contrasenas no coinciden")
    if len(password or "") < MINIMO:
        raise ErrorAcceso("La contrasena necesita al menos %d caracteres" % MINIMO)

    with io.open(ARCHIVO, "w", encoding="ascii") as f:
        f.write(contexto.cifra(password))

    # Solo el dueno puede leerla. En Windows no siempre aplica, y por eso el
    # archivo esta ademas en el .gitignore del modulo: no basta con un permiso.
    try:
        os.chmod(ARCHIVO, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return True


def verifica(password):
    """True si la contrasena es la fijada."""
    if not esta_fijada():
        return False
    with io.open(ARCHIVO, encoding="ascii") as f:
        cifrada = f.read().strip()
    if not cifrada:
        return False

    # Mismo desvio que `contexto.cifra`, y por el mismo motivo: passlib 1.7.4 se
    # rompe al arrancar con bcrypt 5, que es el que tiene el venv de esta
    # maquina. El formato es identico, asi que comprobar con bcrypt directo
    # valida exactamente lo que passlib genero.
    try:
        from app.core.security import verify_password
        return bool(verify_password(password, cifrada))
    except Exception:
        try:
            import bcrypt
            return bcrypt.checkpw((password or "").encode("utf-8"),
                                  cifrada.encode("ascii"))
        except Exception:
            return False


def cambia(actual, nueva, repeticion):
    """Cambia la contrasena, exigiendo la vigente."""
    if not verifica(actual):
        raise ErrorAcceso("La contrasena actual no es correcta")
    if nueva != repeticion:
        raise ErrorAcceso("Las dos contrasenas nuevas no coinciden")
    if len(nueva or "") < MINIMO:
        raise ErrorAcceso("La contrasena necesita al menos %d caracteres" % MINIMO)
    with io.open(ARCHIVO, "w", encoding="ascii") as f:
        f.write(contexto.cifra(nueva))
    return True


# --------------------------------------------------------------------------
# Sesiones abiertas
# --------------------------------------------------------------------------
# Viven en memoria y mueren con el proceso: cerrar el modulo cierra la sesion.
# No hay nada que caducar ni que limpiar en disco, y reiniciar el servidor deja
# fuera a cualquiera que tuviera una pestana abierta.

_ABIERTAS = set()

COOKIE = "admin_sesion"


def abre_sesion():
    testigo = secrets.token_urlsafe(32)
    _ABIERTAS.add(testigo)
    return testigo


def sesion_valida(testigo):
    return bool(testigo) and testigo in _ABIERTAS


def cierra_sesion(testigo):
    _ABIERTAS.discard(testigo)


def cierra_todas():
    _ABIERTAS.clear()
