# -*- coding: utf-8 -*-
"""Bloque A - Cuentas.

Todo lo que el sistema no permite hacer con las cuentas y un administrador
necesita: crear docentes y administradores, dar de alta estudiantes de uno en
uno o por lista, mover una cuenta de rol o de entorno, y restablecer una
contrasena.

DOS COSAS QUE ESTE MODULO VALIDA Y EL SISTEMA NO. El registro del sistema acepta
el rol que le manden y no comprueba que el entorno exista; aqui el rol lo pone
la operacion elegida -nadie se da de alta como lo que quiera- y el entorno se
comprueba contra la tabla antes de escribir.

EFECTO INMEDIATO. El sistema relee al usuario y su rol de la base en cada
peticion, asi que un cambio de rol o de entorno se nota en la peticion
siguiente. La excepcion es la contrasena: cambiarla NO cierra las sesiones ya
abiertas, porque la credencial emitida no depende de ella.

Las funciones de este archivo no piden nada por pantalla: reciben lo que
necesitan y devuelven el resultado. La interaccion vive en admin.py.
"""
import csv
import io
import re
import secrets
import string
from datetime import datetime

import contexto
import registro

CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Sin caracteres que se confundan al dictarlos o copiarlos a mano: O/0, l/1, I.
ALFABETO = "".join(c for c in (string.ascii_letters + string.digits) if c not in "O0lI1")

# Minimo para una contrasena escrita por el administrador (ver _valida_password).
MINIMO_PASSWORD = 8


class ErrorCuenta(Exception):
    pass


def genera_password(largo=12):
    return "".join(secrets.choice(ALFABETO) for _ in range(largo))


def _valida_correo(correo):
    """Valida con el MISMO criterio que el sistema, no con uno propio mas laxo.

    El sistema declara el correo como `EmailStr` de Pydantic, que se apoya en
    `email_validator` y rechaza cosas que una expresion regular deja pasar: entre
    ellas los dominios reservados como `.local`. Una cuenta con `@modulo.local`
    se escribiria sin problema en la base y luego NO podria iniciar sesion -el
    sistema responde 422 antes de mirar la contrasena-. Validar distinto que el
    sistema es crear cuentas muertas.
    """
    correo = (correo or "").strip()
    if not correo:
        raise ErrorCuenta("El correo no puede estar vacio")
    try:
        from email_validator import EmailNotValidError, validate_email
    except ImportError:
        if not CORREO.match(correo):
            raise ErrorCuenta("El correo '%s' no tiene forma valida" % correo)
        return correo.lower()
    try:
        datos = validate_email(correo, check_deliverability=False)
    except EmailNotValidError as exc:
        raise ErrorCuenta("El sistema no aceptaria ese correo: %s" % exc)
    return (getattr(datos, "normalized", None) or datos.email).lower()


def _valida_password(password):
    """Comprueba la contrasena que escribe el administrador. Devuelve None si no la dio.

    El sistema NO valida la contrasena -`UserLogin.password` es un `str` sin
    longitud minima-, asi que aqui no se replica un criterio suyo: se pone uno
    propio, y por eso se documenta. Es mas estricto que el del sistema, nunca mas
    laxo, que es la regla de este modulo (ver _valida_correo).

    Ocho caracteres es el minimo; la generada tiene doce. No se exigen mayusculas
    ni simbolos: una regla de complejidad inventada aqui empujaria a escribir
    contrasenas peores y previsibles, y no hay ninguna en el sistema con la que
    ser coherente.
    """
    if password is None:
        return None
    if password != password.strip():
        raise ErrorCuenta("La contrasena no puede empezar ni terminar con espacios: "
                          "se pierden al dictarla o al copiarla")
    if not password:
        return None
    if len(password) < MINIMO_PASSWORD:
        raise ErrorCuenta("La contrasena debe tener al menos %d caracteres" % MINIMO_PASSWORD)
    return password


def _entorno_existe(s, environment_id):
    _, _, Environment, _ = contexto.modelos()
    return s.query(Environment).filter(Environment.id == environment_id).first() is not None


def lista_usuarios(s, texto=None, rol=None):
    """A7 - Usuarios, con filtro opcional por texto (correo o nombre) y por rol."""
    User, UserRole, _, _ = contexto.modelos()
    q = s.query(User)
    if rol:
        q = q.filter(User.role == UserRole(rol))
    if texto:
        patron = "%%%s%%" % texto.lower()
        from sqlalchemy import func, or_
        q = q.filter(or_(func.lower(User.email).like(patron), func.lower(User.full_name).like(patron)))
    return q.order_by(User.role, User.email).all()


def crea_cuenta(s, correo, nombre, rol, environment_id=None, password=None):
    """A1, A2, A3 - Crea una cuenta con el rol que fija la operacion.

    Devuelve (usuario, password_en_claro). La contrasena se devuelve para poder
    entregarla; no se guarda en ningun registro.
    """
    User, UserRole, _, _ = contexto.modelos()
    correo = _valida_correo(correo)

    if not nombre or not nombre.strip():
        raise ErrorCuenta("El nombre no puede estar vacio")

    try:
        rol_enum = UserRole(rol)
    except ValueError:
        raise ErrorCuenta("Rol no valido: %s" % rol)

    if s.query(User).filter(User.email == correo).first():
        raise ErrorCuenta("Ya existe una cuenta con el correo %s" % correo)

    if environment_id and not _entorno_existe(s, environment_id):
        raise ErrorCuenta("El entorno %s no existe" % environment_id)

    if rol_enum == UserRole.student and not environment_id:
        raise ErrorCuenta("Un estudiante necesita un entorno: sin el no ve ningun corpus")

    dada = _valida_password(password)
    clara = dada or genera_password()
    usuario = User(
        email=correo,
        hashed_password=contexto.cifra(clara),
        full_name=nombre.strip(),
        role=rol_enum,
        environment_id=environment_id,
    )
    s.add(usuario)
    s.commit()
    s.refresh(usuario)

    registro.anota("crear_cuenta", {"correo": correo, "rol": rol_enum.value,
                                    "entorno": environment_id,
                                    "password": "dada" if dada else "generada"})
    return usuario, clara


def alta_por_lista(s, ruta_csv, environment_id):
    """A4 - Alta de estudiantes desde un archivo con columnas correo y nombre.

    No aborta el lote por una fila mala: registra el motivo y sigue. Devuelve
    (creados, fallidos), donde creados son tuplas (correo, nombre, password).
    """
    if not _entorno_existe(s, environment_id):
        raise ErrorCuenta("El entorno %s no existe" % environment_id)

    creados, fallidos = [], []
    with io.open(ruta_csv, encoding="utf-8-sig", newline="") as f:
        muestra = f.read(4096)
        f.seek(0)
        try:
            dialecto = csv.Sniffer().sniff(muestra, delimiters=",;\t")
        except csv.Error:
            dialecto = csv.excel
        lector = csv.DictReader(f, dialect=dialecto)
        columnas = {c.strip().lower(): c for c in (lector.fieldnames or [])}
        col_correo = columnas.get("correo") or columnas.get("email")
        col_nombre = columnas.get("nombre") or columnas.get("full_name")
        if not col_correo or not col_nombre:
            raise ErrorCuenta("El archivo debe tener columnas 'correo' y 'nombre'")

        for fila in lector:
            correo = (fila.get(col_correo) or "").strip()
            nombre = (fila.get(col_nombre) or "").strip()
            try:
                _, clara = crea_cuenta(s, correo, nombre, "student", environment_id)
                creados.append((correo.lower(), nombre, clara))
            except ErrorCuenta as exc:
                s.rollback()
                fallidos.append((correo, str(exc)))

    registro.anota("alta_por_lista", {"archivo": str(ruta_csv), "entorno": environment_id,
                                      "creados": len(creados), "fallidos": len(fallidos)})
    return creados, fallidos


def exporta_credenciales(creados, etiqueta="altas"):
    """Deja las credenciales generadas en un archivo, para poder entregarlas.

    El archivo lleva contrasenas en claro: es su motivo de existir y por eso se
    avisa al crearlo. Vive en salidas/ del propio modulo, no en el proyecto.
    """
    contexto.prepara_directorios()
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    destino = contexto.DIR_SALIDAS / ("credenciales_%s_%s.csv" % (etiqueta, marca))
    with io.open(destino, "w", encoding="utf-8", newline="") as f:
        escritor = csv.writer(f)
        escritor.writerow(["correo", "nombre", "password"])
        for correo, nombre, clara in creados:
            escritor.writerow([correo, nombre, clara])
    registro.anota("exportar_credenciales", {"archivo": str(destino), "cuentas": len(creados)})
    return destino


def cambia_rol_o_entorno(s, user_id, rol=None, environment_id=None, quitar_entorno=False):
    """A5 - Mueve una cuenta de rol, de entorno, o de los dos. Efecto inmediato."""
    User, UserRole, _, _ = contexto.modelos()
    usuario = s.query(User).filter(User.id == user_id).first()
    if not usuario:
        raise ErrorCuenta("No existe la cuenta indicada")

    antes = {"rol": usuario.role.value, "entorno": usuario.environment_id}

    if rol:
        try:
            usuario.role = UserRole(rol)
        except ValueError:
            raise ErrorCuenta("Rol no valido: %s" % rol)

    if quitar_entorno:
        usuario.environment_id = None
    elif environment_id:
        if not _entorno_existe(s, environment_id):
            raise ErrorCuenta("El entorno %s no existe" % environment_id)
        usuario.environment_id = environment_id

    if usuario.role == UserRole.student and not usuario.environment_id:
        raise ErrorCuenta("Un estudiante no puede quedar sin entorno")

    s.commit()
    s.refresh(usuario)
    registro.anota("cambiar_rol_o_entorno", {"correo": usuario.email, "antes": antes,
                                             "despues": {"rol": usuario.role.value,
                                                         "entorno": usuario.environment_id}})
    return usuario


def restablece_password(s, user_id, password=None):
    """A6 - Escribe una contrasena nueva con el mismo cifrado del sistema.

    Devuelve (usuario, password_en_claro). No cierra las sesiones abiertas: la
    credencial ya emitida no depende de la contrasena y sigue valiendo hasta
    caducar. Para expulsar a todos hay que cambiar el secreto (bloque C).
    """
    User, _, _, _ = contexto.modelos()
    usuario = s.query(User).filter(User.id == user_id).first()
    if not usuario:
        raise ErrorCuenta("No existe la cuenta indicada")

    dada = _valida_password(password)
    clara = dada or genera_password()
    usuario.hashed_password = contexto.cifra(clara)
    s.commit()
    registro.anota("restablecer_password", {"correo": usuario.email,
                                            "password": "dada" if dada else "generada"})
    return usuario, clara
