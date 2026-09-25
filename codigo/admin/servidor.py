# -*- coding: utf-8 -*-
"""Interfaz web del modulo de administracion.

Es la cara nueva del modulo, no un modulo nuevo: las operaciones siguen siendo
las de `cuentas.py`, `entornos.py`, `configuracion.py` y `operacion.py`, que no
se tocan. Esos seis modulos no imprimen ni preguntan nada -devuelven datos-, y
por eso admiten una consola y una pagina web sin enterarse de cual los llama.

`admin.py` sigue existiendo y funcionando: son dos puertas a la misma logica.
La consola es la red de seguridad cuando no hay navegador a mano.

DONDE ESCUCHA. Solo en 127.0.0.1, puerto 8010. No es alcanzable desde la red:
esto administra el sistema, no forma parte de el. Y aun asi pide contrasena, que
se fija en el primer arranque (ver `acceso.py`).

Uso:
    codigo\\admin\\admin.bat
    codigo/backend/venv/Scripts/python.exe codigo/admin/servidor.py
"""
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from typing import List  # noqa: E402

from fastapi import FastAPI, Form, Request, UploadFile, File  # noqa: E402
from fastapi.responses import RedirectResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from fastapi.templating import Jinja2Templates  # noqa: E402

import acceso  # noqa: E402
import contexto  # noqa: E402
import configuracion  # noqa: E402
import cuentas  # noqa: E402
import entornos  # noqa: E402
import operacion  # noqa: E402
import registro  # noqa: E402

AQUI = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PUERTO = 8010

app = FastAPI(title="Modulo de administracion", docs_url=None, redoc_url=None,
              openapi_url=None)
app.mount("/estaticos", StaticFiles(directory=str(AQUI / "estaticos")),
          name="estaticos")
plantillas = Jinja2Templates(directory=str(AQUI / "plantillas"))


# --------------------------------------------------------------------------
# Avisos: lo que una operacion deja dicho para la pagina siguiente
# --------------------------------------------------------------------------
# No viajan por la URL a proposito. Algunas operaciones devuelven una contrasena
# recien generada, y una contrasena en la barra de direcciones queda en el
# historial del navegador. Se guardan en memoria contra el testigo de sesion y
# se consumen al mostrarlos.

_AVISOS = {}


def avisa(testigo, tipo, texto, clave=None, detalle=None, accion=None):
    """`accion` es lo que el cambio arrastra, ofrecido como boton.

    Es la regla del modulo llevada a la interfaz: si un cambio necesita
    reiniciar, no se avisa y se deja al usuario buscar donde — se le ofrece
    hacerlo en el mismo sitio donde se le dice.
    """
    _AVISOS[testigo] = {"tipo": tipo, "texto": texto, "clave": clave,
                        "detalle": detalle, "accion": accion}


def toma_aviso(testigo):
    return _AVISOS.pop(testigo, None)


# --------------------------------------------------------------------------
# Los dos semaforos de la barra lateral
# --------------------------------------------------------------------------
# Se consultan en cada pagina, asi que se guardan unos segundos: comprobar la
# base y llamar a docker en cada clic haria la interfaz lenta sin dar nada.

_ESTADO = {"cuando": 0.0, "datos": None}
VIGENCIA = 10.0


def semaforos():
    ahora = time.time()
    if _ESTADO["datos"] and ahora - _ESTADO["cuando"] < VIGENCIA:
        return _ESTADO["datos"]
    base_ok, base_motivo = contexto.base_alcanzable()
    docker_ok, docker_detalle = contexto.docker_disponible()
    datos = {"base_ok": base_ok, "base_motivo": base_motivo,
             "docker_ok": docker_ok, "docker_detalle": docker_detalle}
    _ESTADO.update(cuando=ahora, datos=datos)
    return datos


def olvida_semaforos():
    _ESTADO["datos"] = None


# --------------------------------------------------------------------------
# Andamiaje de cada peticion
# --------------------------------------------------------------------------

def testigo_de(request):
    return request.cookies.get(acceso.COOKIE)


def entrado(request):
    return acceso.sesion_valida(testigo_de(request))


def a_la_entrada():
    return RedirectResponse("/entrada", status_code=303)


def pinta(request, plantilla, **contexto_extra):
    testigo = testigo_de(request)
    datos = {"aviso": toma_aviso(testigo), "semaforo": semaforos(),
             "seccion": contexto_extra.pop("seccion", "")}
    datos.update(contexto_extra)
    # Starlette 1.3 pide el request como primer argumento; la firma vieja
    # -(plantilla, contexto)- toma el diccionario como nombre de plantilla.
    return plantillas.TemplateResponse(request, plantilla, datos)


class SinBase(Exception):
    """La base no esta. Se dice, no se deja reventar."""


class Sesion:
    """Abre y cierra una sesion de base por operacion, como hace la consola.

    Si la base no esta -los contenedores parados, que es un estado normal y no
    una averia-, levanta SinBase para que la pantalla lo explique en vez de
    devolver una traza. El modulo dice lo que falta antes de empezar; eso vale
    igual para la interfaz web.
    """

    def __enter__(self):
        try:
            self.s = contexto.sesion()
            return self.s
        except Exception as exc:
            raise SinBase(str(exc).splitlines()[0][:200])

    def __exit__(self, *_):
        s = getattr(self, "s", None)
        if s is not None:
            s.close()
        return False


def vuelve(destino):
    return RedirectResponse(destino, status_code=303)


# --------------------------------------------------------------------------
# Entrada
# --------------------------------------------------------------------------

@app.get("/entrada")
def entrada(request: Request):
    if entrado(request):
        return vuelve("/")
    return pinta(request, "entrada.html", primera_vez=not acceso.esta_fijada())


@app.post("/entrada")
def entra(request: Request, password: str = Form(""), repeticion: str = Form("")):
    primera = not acceso.esta_fijada()
    try:
        if primera:
            acceso.fija(password, repeticion)
            registro.anota("fijar_password_modulo", {}, "ok")
        elif not acceso.verifica(password):
            raise acceso.ErrorAcceso("Contrasena incorrecta")
    except acceso.ErrorAcceso as exc:
        respuesta = pinta(request, "entrada.html", primera_vez=primera,
                          error=str(exc))
        return respuesta

    testigo = acceso.abre_sesion()
    respuesta = vuelve("/")
    respuesta.set_cookie(acceso.COOKIE, testigo, httponly=True, samesite="lax")
    if primera:
        avisa(testigo, "ok", "Contrasena del modulo fijada. Se pedira a partir "
                             "de ahora, y no queda escrita en el repositorio.")
    return respuesta


@app.post("/salir")
def sale(request: Request):
    acceso.cierra_sesion(testigo_de(request))
    respuesta = a_la_entrada()
    respuesta.delete_cookie(acceso.COOKIE)
    return respuesta


# --------------------------------------------------------------------------
# Inicio
# --------------------------------------------------------------------------

@app.get("/")
def inicio(request: Request):
    if not entrado(request):
        return a_la_entrada()

    servicios, problemas = [], []
    try:
        servicios, problemas = operacion.estado_servicios()
    except Exception as exc:
        problemas = [str(exc).splitlines()[0][:160]]

    salud = []
    try:
        salud = operacion.salud()
    except Exception as exc:
        salud = [("(no se pudo consultar)", None, str(exc).splitlines()[0][:160])]

    recuento = {}
    try:
        with Sesion() as s:
            todos = cuentas.lista_usuarios(s)
            recuento = {
                "docentes": sum(1 for u in todos if u.role.value == "teacher"),
                "administradores": sum(1 for u in todos if u.role.value == "admin"),
                "estudiantes": sum(1 for u in todos if u.role.value == "student"),
                "total": len(todos),
            }
            lista = entornos.lista_entornos(s)
            recuento["entornos"] = len(lista)
            recuento["documentos"] = sum(e["documentos"] for e in lista)
    except Exception as exc:
        recuento = {"error": str(exc).splitlines()[0][:200]}

    return pinta(request, "inicio.html", seccion="inicio", servicios=servicios,
                 problemas=problemas, salud=salud, recuento=recuento,
                 modo=_modo(), ultimas=registro.ultimas(8))


# --------------------------------------------------------------------------
# Cuentas
# --------------------------------------------------------------------------

ROLES = (("teacher", "docente"), ("admin", "administrador"),
         ("student", "estudiante"))


@app.get("/cuentas")
def ver_cuentas(request: Request, q: str = "", rol: str = ""):
    if not entrado(request):
        return a_la_entrada()
    try:
        with Sesion() as s:
            usuarios = cuentas.lista_usuarios(s, q or None, rol or None)
            lista = entornos.lista_entornos(s)
            nombres = {e["id"]: e["nombre"] for e in lista}
            filas = [{
                "id": u.id, "email": u.email, "nombre": u.full_name,
                "rol": u.role.value, "entorno_id": u.environment_id,
                "entorno": nombres.get(u.environment_id, ""),
            } for u in usuarios]
    except (SinBase, Exception) as exc:
        return pinta(request, "cuentas.html", seccion="cuentas", filas=[],
                     entornos=[], roles=ROLES, q=q, rol=rol,
                     sin_base=str(exc).splitlines()[0][:200])
    return pinta(request, "cuentas.html", seccion="cuentas", filas=filas,
                 entornos=lista, roles=ROLES, q=q, rol=rol)


@app.post("/cuentas/crear")
def crear_cuenta(request: Request, correo: str = Form(""), nombre: str = Form(""),
                 rol: str = Form("teacher"), entorno: str = Form(""),
                 password: str = Form("")):
    if not entrado(request):
        return a_la_entrada()
    testigo = testigo_de(request)
    with Sesion() as s:
        try:
            usuario, clave = cuentas.crea_cuenta(s, correo, nombre, rol,
                                                 entorno or None, password or None)
            avisa(testigo, "clave",
                  "Cuenta creada: %s (%s)." % (usuario.email, rol), clave=clave)
        except Exception as exc:
            s.rollback()
            avisa(testigo, "error", "No se pudo crear la cuenta: %s" % exc)
    return vuelve("/cuentas")


@app.post("/cuentas/alta-lista")
async def alta_lista(request: Request, entorno: str = Form(""),
                     archivo: UploadFile = File(...)):
    if not entrado(request):
        return a_la_entrada()
    testigo = testigo_de(request)

    contexto.prepara_directorios()
    temporal = contexto.DIR_SALIDAS / ("lista_%s" % (archivo.filename or "altas.csv"))
    temporal.write_bytes(await archivo.read())

    with Sesion() as s:
        try:
            creados, fallidos = cuentas.alta_por_lista(s, str(temporal), entorno)
            destino = cuentas.exporta_credenciales(creados) if creados else None
            detalle = ["%s: %s" % (c, m) for c, m in fallidos]
            texto = "Creadas %d cuentas, %d con problema." % (len(creados),
                                                              len(fallidos))
            if destino:
                texto += (" Las credenciales quedaron en %s — llevan las "
                          "contrasenas en claro: entreguelas y borre el archivo."
                          % Path(destino).name)
            avisa(testigo, "ok" if creados else "error", texto, detalle=detalle)
        except Exception as exc:
            s.rollback()
            avisa(testigo, "error", "No se pudo procesar la lista: %s" % exc)
        finally:
            temporal.unlink(missing_ok=True)
    return vuelve("/cuentas")


@app.post("/cuentas/cambiar")
def cambiar_cuenta(request: Request, user_id: str = Form(...),
                   rol: str = Form(""), entorno: str = Form("")):
    if not entrado(request):
        return a_la_entrada()
    testigo = testigo_de(request)
    with Sesion() as s:
        try:
            usuario = cuentas.cambia_rol_o_entorno(s, user_id, rol or None,
                                                   entorno or None)
            avisa(testigo, "ok", "%s queda como %s, entorno %s. El cambio surte "
                                 "efecto en la siguiente peticion."
                  % (usuario.email, usuario.role.value,
                     usuario.environment_id or "sin entorno"))
        except Exception as exc:
            s.rollback()
            avisa(testigo, "error", "No se pudo cambiar: %s" % exc)
    return vuelve("/cuentas")


@app.post("/cuentas/clave")
def nueva_clave(request: Request, user_id: str = Form(...), password: str = Form("")):
    if not entrado(request):
        return a_la_entrada()
    testigo = testigo_de(request)
    with Sesion() as s:
        try:
            usuario, clave = cuentas.restablece_password(s, user_id, password or None)
            avisa(testigo, "clave", "Contrasena nueva de %s." % usuario.email,
                  clave=clave,
                  detalle=["Las sesiones ya abiertas siguen validas hasta "
                           "caducar: cambiar la contrasena no las cierra."])
        except Exception as exc:
            s.rollback()
            avisa(testigo, "error", "No se pudo restablecer: %s" % exc)
    return vuelve("/cuentas")


# --------------------------------------------------------------------------
# Entornos
# --------------------------------------------------------------------------

@app.get("/entornos")
def ver_entornos(request: Request):
    if not entrado(request):
        return a_la_entrada()
    try:
        with Sesion() as s:
            lista = entornos.lista_entornos(s)
            docentes = [{"id": u.id, "email": u.email, "nombre": u.full_name}
                        for u in entornos.docentes_disponibles(s)]
    except (SinBase, Exception) as exc:
        return pinta(request, "entornos.html", seccion="entornos", entornos=[],
                     docentes=[], sin_base=str(exc).splitlines()[0][:200])
    return pinta(request, "entornos.html", seccion="entornos", entornos=lista,
                 docentes=docentes)


@app.post("/entornos/crear")
def crear_entorno(request: Request, nombre: str = Form(""),
                  docente: str = Form(""), descripcion: str = Form(""),
                  area: str = Form(""), nivel: str = Form("")):
    if not entrado(request):
        return a_la_entrada()
    testigo = testigo_de(request)
    with Sesion() as s:
        try:
            e = entornos.crea_entorno(s, nombre, docente, descripcion or None,
                                      area or None, nivel or None)
            avisa(testigo, "ok", "Entorno «%s» creado y asignado." % e.name,
                  detalle=["Identificador: %s" % e.id])
        except Exception as exc:
            s.rollback()
            avisa(testigo, "error", "No se pudo crear el entorno: %s" % exc)
    return vuelve("/entornos")


@app.post("/entornos/reasignar")
def reasignar(request: Request, entorno: str = Form(...),
              docente: str = Form(...), liberar: str = Form("")):
    if not entrado(request):
        return a_la_entrada()
    testigo = testigo_de(request)
    with Sesion() as s:
        try:
            entornos.reasigna_docente(s, entorno, docente, bool(liberar))
            avisa(testigo, "ok", "Entorno reasignado.")
        except Exception as exc:
            s.rollback()
            avisa(testigo, "error", "No se pudo reasignar: %s" % exc)
    return vuelve("/entornos")


# --------------------------------------------------------------------------
# Configuracion
# --------------------------------------------------------------------------

def _encadena(testigo, texto, efectos, copia=None):
    """Traduce los efectos de un cambio en aviso, detalle y accion ofrecida."""
    detalle = []
    if copia is not None:
        detalle.append("Copia previa del .env: %s" % copia.name)
    accion = None

    if "sesiones_invalidadas" in efectos:
        detalle.append("Al cambiar el secreto, TODAS las sesiones abiertas del "
                       "sistema dejaran de valer.")
    if "reindexar" in efectos:
        detalle.append("IMPORTANTE: cambiar el proveedor o el modelo de "
                       "embeddings invalida el indice. Hasta reindexar, el "
                       "sistema responde con vectores que ya no corresponden, y "
                       "lo hace sin avisar. Para pasar de un modo a otro con todo "
                       "encadenado -copias, servicios, embeddings, reindexacion y "
                       "verificacion- use Operacion > Cambiar de modo.")
    if "reiniciar" in efectos:
        # Reiniciar NO aplica un cambio de config/.env: el backend recibe la
        # configuracion al CREARSE el contenedor. Aplicar alcanza tambien lo que
        # queda fuera de Docker: el servidor de embeddings y la memoria que
        # Ollama deja ocupada.
        detalle.append("El cambio esta escrito pero NO esta activo hasta "
                       "aplicarlo. Aplicar recrea los contenedores, libera la "
                       "memoria de los modelos locales que ya no se usan y "
                       "reinicia el servidor de embeddings si no sirve lo que "
                       "pide la configuracion.")
        accion = {"texto": "Aplicar el cambio ahora",
                  "url": "/operacion/aplicar",
                  "campos": {"volver": "/configuracion"}}

    grave = "reindexar" in efectos or "sesiones_invalidadas" in efectos
    avisa(testigo, "clave" if grave else "ok", texto,
          detalle=detalle or None, accion=accion)


@app.get("/configuracion")
def ver_configuracion(request: Request):
    if not entrado(request):
        return a_la_entrada()
    try:
        valores = configuracion.lee_todo()
        modo = [(c, valores.get(c, ""), configuracion.OPCIONES[c])
                for c in configuracion.MODO]
        # Los parametros con una credencial dentro salen del bloque editable:
        # ahi su valor se veria entero en pantalla. Van con los secretos.
        parametros = [(c, valores.get(c, "")) for c in configuracion.PARAMETROS
                      if c in valores and c not in configuracion.CREDENCIAL_EMBEBIDA]
        conexiones = [(c, configuracion.enmascara(c, valores.get(c, "")))
                      for c in configuracion.CREDENCIAL_EMBEBIDA if c in valores]
        secretos = [(c, configuracion.enmascara(c, valores.get(c, "")))
                    for c in configuracion.CLAVES_SECRETAS if c in valores]
        copias = [{"ruta": str(p), "nombre": p.name, "bytes": p.stat().st_size}
                  for p in configuracion.respaldos()[:15]]
    except Exception as exc:
        return pinta(request, "configuracion.html", seccion="configuracion",
                     modo=[], parametros=[], conexiones=[], secretos=[],
                     copias=[], problema=str(exc).splitlines()[0][:200])
    return pinta(request, "configuracion.html", seccion="configuracion",
                 modo=modo, parametros=parametros, conexiones=conexiones,
                 secretos=secretos, copias=copias, problema=None)


@app.post("/configuracion/valor")
def cambia_configuracion(request: Request, clave: str = Form(...),
                         valor: str = Form("")):
    if not entrado(request):
        return a_la_entrada()
    testigo = testigo_de(request)
    try:
        copia, efectos = configuracion.cambia_valor(clave, valor)
        secreto = clave.strip().upper() in configuracion.CLAVES_SECRETAS
        dicho = "%s actualizado." % clave if secreto \
            else "%s actualizado a %s." % (clave, valor)
        _encadena(testigo, dicho, efectos, copia)
    except Exception as exc:
        avisa(testigo, "error", "No se pudo cambiar %s: %s" % (clave, exc))
    return vuelve("/configuracion")


@app.post("/configuracion/restaurar")
def restaura_configuracion(request: Request, ruta: str = Form(...),
                           confirmacion: str = Form("")):
    if not entrado(request):
        return a_la_entrada()
    testigo = testigo_de(request)
    if confirmacion.strip().upper() != "SI":
        avisa(testigo, "error", "No se restauro: hay que escribir SI para confirmar.")
        return vuelve("/configuracion")
    try:
        previa = configuracion.restaura_respaldo(ruta)
        _encadena(testigo, "Configuracion restaurada desde %s." % Path(ruta).name,
                  ["reiniciar"], previa)
    except Exception as exc:
        avisa(testigo, "error", "No se pudo restaurar: %s" % exc)
    return vuelve("/configuracion")


# --------------------------------------------------------------------------
# Operacion
# --------------------------------------------------------------------------

@app.get("/operacion")
def ver_operacion(request: Request):
    if not entrado(request):
        return a_la_entrada()

    try:
        servicios, problemas = operacion.estado_servicios()
    except Exception as exc:
        servicios, problemas = [], [str(exc).splitlines()[0][:200]]

    estado = {n: e for n, e in servicios}
    fichas = [{"nombre": n, "estado": estado.get(n, "no levantado")}
              for n in operacion.SERVICIOS]

    try:
        salud = operacion.salud()
    except Exception as exc:
        salud = [("(no se pudo consultar)", None, str(exc).splitlines()[0][:160])]

    try:
        with Sesion() as s:
            lista = entornos.lista_entornos(s)
    except Exception:
        lista = []

    volcados = [{"ruta": str(p), "nombre": p.name, "bytes": p.stat().st_size}
                for p in operacion.volcados_disponibles()[:15]]

    instalados, _, _ = operacion.modelos_ollama()
    try:
        modelo_local = configuracion.lee_todo().get("OLLAMA_MODEL", "")
    except Exception:
        modelo_local = ""

    return pinta(request, "operacion.html", seccion="operacion", fichas=fichas,
                 problemas=problemas, salud=salud, entornos=lista,
                 volcados=volcados, modo=_modo(), instalados=instalados,
                 modelo_local=modelo_local)


@app.post("/operacion/servicios")
def mueve_servicios(request: Request, accion: str = Form(...),
                    servicio: str = Form(""), volver: str = Form("/operacion")):
    if not entrado(request):
        return a_la_entrada()
    testigo = testigo_de(request)
    cual = servicio or None
    nombre = servicio or "todos los servicios"
    try:
        if accion == "up":
            ok, salida = operacion.arranca(cual)
            hecho = "Arrancado"
        elif accion == "restart":
            ok, salida = operacion.reinicia(cual)
            hecho = "Reiniciado"
        elif accion == "recrear":
            ok, salida = operacion.recrea(cual)
            hecho = "Recreado (cambio de configuracion aplicado)"
        elif accion == "stop":
            ok, salida = operacion.detiene(cual)
            hecho = "Detenido"
        else:
            raise ValueError("Accion no valida: %s" % accion)
        olvida_semaforos()
        avisa(testigo, "ok" if ok else "error",
              "%s: %s." % (hecho, nombre) if ok else "No se pudo con %s." % nombre,
              detalle=None if ok else [salida[-500:]])
    except Exception as exc:
        avisa(testigo, "error", "No se pudo operar sobre %s: %s" % (nombre, exc))
    return vuelve(volver if volver.startswith("/") else "/operacion")


def _modo():
    """El modo escrito y el que corre de verdad, sin tumbar la pagina si falla."""
    try:
        return operacion.modo_actual()
    except Exception as exc:
        return {"escrito": "?", "activo": None,
                "pendientes": ["no se pudo determinar: %s" % str(exc).splitlines()[0][:160]]}


def _pasos(pasos):
    return ["%s %s: %s" % ("✓" if ok else "✗", nombre, detalle)
            for nombre, ok, detalle in pasos]


@app.post("/operacion/aplicar")
def aplica_configuracion(request: Request, volver: str = Form("/operacion")):
    if not entrado(request):
        return a_la_entrada()
    testigo = testigo_de(request)
    try:
        ok, pasos = operacion.aplica_configuracion()
        olvida_semaforos()
        avisa(testigo, "ok" if ok else "error",
              "Configuracion aplicada: el sistema corre con lo que dice el .env."
              if ok else "No se pudo aplicar la configuracion entera.",
              detalle=_pasos(pasos))
    except Exception as exc:
        avisa(testigo, "error", "No se pudo aplicar la configuracion: %s" % exc)
    return vuelve(volver if volver.startswith("/") else "/operacion")


@app.post("/operacion/embeddings")
def reinicia_servidor_embeddings(request: Request):
    if not entrado(request):
        return a_la_entrada()
    testigo = testigo_de(request)
    try:
        ok, estado, cerrados = operacion.reinicia_embeddings()
        detalle = ["Procesos cerrados: %s" % (", ".join(map(str, cerrados)) or "ninguno")]
        if estado.get("detalle"):
            detalle.append(estado["detalle"])
        avisa(testigo, "ok" if ok else "error",
              "Servidor de embeddings reiniciado: sirve %s." % estado.get("modelo")
              if ok else "El servidor de embeddings no volvio a responder.",
              detalle=detalle)
    except Exception as exc:
        avisa(testigo, "error", "No se pudo reiniciar el servidor de embeddings: %s" % exc)
    return vuelve("/operacion")


@app.post("/operacion/modo")
def cambia_de_modo(request: Request, modo: str = Form(...), modelo_local: str = Form(""),
                   entornos_elegidos: List[str] = Form(default=[]),
                   correo: str = Form(""), password: str = Form(""),
                   confirmacion: str = Form("")):
    if not entrado(request):
        return a_la_entrada()
    testigo = testigo_de(request)
    if confirmacion.strip().upper() != "SI":
        avisa(testigo, "error", "No se cambio de modo: hay que escribir SI para confirmar.")
        return vuelve("/operacion")
    try:
        with Sesion() as s:
            nombres = {e["id"]: e["nombre"] for e in entornos.lista_entornos(s)}
    except Exception:
        nombres = {}
    try:
        ok, pasos = operacion.cambia_modo(modo, entornos_elegidos, correo, password,
                                          modelo_local=modelo_local or None, nombres=nombres)
        olvida_semaforos()
        avisa(testigo, "ok" if ok else "error",
              "Sistema en modo %s." % modo.upper() if ok
              else "El cambio a modo %s no se completo: se detuvo en el paso marcado." % modo,
              detalle=_pasos(pasos))
    except Exception as exc:
        avisa(testigo, "error", "No se pudo cambiar de modo: %s" % exc)
    return vuelve("/operacion")


@app.post("/operacion/copia")
def copia_base(request: Request):
    if not entrado(request):
        return a_la_entrada()
    testigo = testigo_de(request)
    try:
        destino = operacion.copia_seguridad()
        avisa(testigo, "ok", "Copia de seguridad de la base hecha.",
              detalle=["%s — %d bytes" % (destino.name, destino.stat().st_size)])
    except Exception as exc:
        avisa(testigo, "error", "No se pudo hacer la copia: %s" % exc)
    return vuelve("/operacion")


@app.post("/operacion/reindexar")
def reindexa(request: Request, entorno: str = Form(...), correo: str = Form(...),
             password: str = Form(...), confirmacion: str = Form("")):
    if not entrado(request):
        return a_la_entrada()
    testigo = testigo_de(request)
    if confirmacion.strip().upper() != "SI":
        avisa(testigo, "error", "No se reindexo: hay que escribir SI para confirmar.")
        return vuelve("/operacion")
    try:
        subidos, fallidos = operacion.reindexa_corpus(entorno, correo, password)
        detalle = ["%s: %s" % (n, m) for n, m in fallidos]
        avisa(testigo, "ok" if subidos else "error",
              "Reindexado: %d documentos cargados, %d con problema."
              % (len(subidos), len(fallidos)), detalle=detalle or None)
    except Exception as exc:
        avisa(testigo, "error", "No se pudo reindexar: %s" % exc)
    return vuelve("/operacion")


@app.post("/operacion/restaurar")
def restaura_base(request: Request, ruta: str = Form(...),
                  confirmacion: str = Form("")):
    if not entrado(request):
        return a_la_entrada()
    testigo = testigo_de(request)
    if confirmacion.strip().upper() != "SI":
        avisa(testigo, "error", "No se restauro: hay que escribir SI para confirmar.")
        return vuelve("/operacion")
    try:
        ok, salida, previa = operacion.restaura(ruta)
        detalle = ["Lo anterior quedo en %s" % previa.name]
        if not ok:
            detalle.append(salida[-500:])
        avisa(testigo, "ok" if ok else "clave",
              "Base restaurada desde %s." % Path(ruta).name if ok
              else "Restaurada con avisos.", detalle=detalle)
    except Exception as exc:
        avisa(testigo, "error", "No se pudo restaurar: %s" % exc)
    return vuelve("/operacion")


# --------------------------------------------------------------------------
# Registro
# --------------------------------------------------------------------------

@app.get("/registro")
def ver_registro(request: Request, q: str = "", n: int = 200):
    if not entrado(request):
        return a_la_entrada()
    todas = registro.ultimas(max(1, min(n, 1000)))
    lineas = todas
    if q:
        aguja = q.lower()
        lineas = [l for l in todas
                  if aguja in l["accion"].lower()
                  or aguja in str(l.get("detalle", "")).lower()
                  or aguja in l["fecha"]]
    acciones = sorted({l["accion"] for l in todas})
    return pinta(request, "registro.html", seccion="registro", lineas=lineas,
                 acciones=acciones, q=q, total=len(todas))


# --------------------------------------------------------------------------
# Arranque
# --------------------------------------------------------------------------

def puerto_ocupado(host, puerto):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        return s.connect_ex((host, puerto)) == 0


def es_esta_consola(host, puerto):
    """Si lo que ocupa el puerto es otra copia del propio modulo.

    Se pregunta por la pantalla de entrada, que es la unica que responde sin
    haber entrado, y se mira su titulo. Una copia anterior a hoy responde igual:
    la plantilla no ha cambiado.
    """
    try:
        import httpx
        r = httpx.get("http://%s:%d/entrada" % (host, puerto), timeout=3.0)
        return r.status_code == 200 and "Entrar · Administración" in r.text
    except Exception:
        return False


def main():
    problemas = contexto.comprueba_requisitos()
    if problemas:
        print("No estan dadas las condiciones para operar:\n")
        for p in problemas:
            print("   - %s" % p)
        return 1

    if puerto_ocupado(HOST, PUERTO):
        # Reutilizar lo que ya corre, no fallar por ello: es el mismo criterio que
        # sigue iniciar_sistema.bat.
        if es_esta_consola(HOST, PUERTO):
            direccion = "http://%s:%d" % (HOST, PUERTO)
            print("Ya habia una consola de administracion abierta en %s." % direccion)
            print("Se abre esa; no hace falta arrancar otra.")
            print("")
            print("OJO SI VENIA A REINICIARLA: esa copia sigue corriendo el codigo")
            print("que cargo al arrancar. Para que tome un cambio hay que CERRAR SU")
            print("VENTANA -la de cmd donde corre, no la del navegador- y volver a")
            print("lanzar esto.")
            webbrowser.open(direccion)
            # Se sale con 2, no con 0, para que el lanzador deje la ventana
            # abierta y este aviso se lea: con salida 0 la ventana se cerraria
            # sola y quien creyera haber reiniciado seguiria mirando la copia
            # vieja, sin una sola pista de que lo es.
            return 2
        print("El puerto %d ya esta ocupado en %s, y no por esta consola." % (PUERTO, HOST))
        print("Cierre lo que lo ocupe y vuelva a intentarlo.")
        return 1

    contexto.prepara_directorios()

    direccion = "http://%s:%d" % (HOST, PUERTO)
    print("Modulo de administracion en %s" % direccion)
    print("Escucha solo en esta maquina. Cierre esta ventana para detenerlo.\n")
    threading.Timer(1.0, lambda: webbrowser.open(direccion)).start()

    import uvicorn
    uvicorn.run(app, host=HOST, port=PUERTO, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
