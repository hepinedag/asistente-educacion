# -*- coding: utf-8 -*-
"""Modulo de administracion del Asistente de Educacion.

Externo al sistema: no anade endpoints, no modifica el backend ni el frontend y
no toca el esquema de la base. Actua sobre lo que el sistema LEE -PostgreSQL,
config/.env y los contenedores-, nunca sobre el sistema.

Uso:
    codigo/backend/venv/Scripts/python.exe codigo/admin/admin.py

Nada se pide a mano: los entornos y las cuentas se eligen de una lista, los
valores admitidos los ofrece el propio modulo, y lo que un cambio arrastra
-reiniciar, reindexar- lo encadena el modulo en la misma operacion.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import configuracion  # noqa: E402
import contexto  # noqa: E402
import cuentas  # noqa: E402
import entornos  # noqa: E402
import operacion  # noqa: E402
import registro  # noqa: E402

LINEA = "-" * 72


def titulo(texto):
    print("\n" + LINEA)
    print(texto)
    print(LINEA)


def elige(opciones, etiqueta, permite_volver=True):
    """Muestra una lista numerada y devuelve el elemento elegido, o None."""
    if not opciones:
        print("   (no hay %s)" % etiqueta)
        return None
    for i, (_, texto) in enumerate(opciones, 1):
        print("   %2d. %s" % (i, texto))
    if permite_volver:
        print("    0. volver")
    while True:
        try:
            n = input("   Elija %s: " % etiqueta).strip()
        except EOFError:
            return None
        if n == "0" and permite_volver:
            return None
        if n.isdigit() and 1 <= int(n) <= len(opciones):
            return opciones[int(n) - 1][0]
        print("   Opcion no valida.")


def pide(texto, obligatorio=True, oculto=False):
    while True:
        try:
            valor = input("   %s: " % texto).strip()
        except EOFError:
            return ""
        if valor or not obligatorio:
            return valor
        print("   No puede quedar vacio.")


def confirma(texto):
    try:
        return input("   %s  Escriba SI para continuar: " % texto).strip().upper() == "SI"
    except EOFError:
        return False


def _opciones_usuarios(s, texto=None, rol=None):
    lista = cuentas.lista_usuarios(s, texto, rol)
    return [(u.id, "%-38s %-9s %s" % (u.email, u.role.value, u.full_name)) for u in lista]


def _opciones_entornos(s):
    lista = entornos.lista_entornos(s)
    return [(e["id"], "%-28s docente: %-30s %2d doc, %2d estud." %
             (e["nombre"][:28], e["docente"][:30], e["documentos"], e["estudiantes"])) for e in lista]


# --------------------------------------------------------------------- CUENTAS
def menu_cuentas(s):
    while True:
        titulo("CUENTAS")
        print("   1. Ver y buscar usuarios")
        print("   2. Crear cuenta de docente")
        print("   3. Crear cuenta de administrador")
        print("   4. Dar de alta un estudiante")
        print("   5. Dar de alta estudiantes desde un archivo")
        print("   6. Cambiar el rol o el entorno de una cuenta")
        print("   7. Restablecer una contrasena")
        print("   0. volver")
        op = pide("Opcion", obligatorio=False)

        if op == "0" or op == "":
            return
        try:
            if op == "1":
                texto = pide("Buscar (correo o nombre, vacio para todos)", obligatorio=False)
                for u in cuentas.lista_usuarios(s, texto or None):
                    print("   %-38s %-9s %-28s entorno: %s" %
                          (u.email, u.role.value, u.full_name[:28], u.environment_id or "-"))

            elif op in ("2", "3"):
                rol = "teacher" if op == "2" else "admin"
                correo = pide("Correo")
                nombre = pide("Nombre completo")
                dada = pide("Contrasena (vacio: la genera el modulo)", obligatorio=False)
                usuario, clave = cuentas.crea_cuenta(s, correo, nombre, rol, password=dada or None)
                print("\n   Creada la cuenta %s (%s)" % (usuario.email, rol))
                print("   Contrasena: %s" % clave)
                print("   Anotela ahora: no se guarda en ningun registro.")

            elif op == "4":
                entorno_id = elige(_opciones_entornos(s), "entorno")
                if not entorno_id:
                    continue
                correo = pide("Correo")
                nombre = pide("Nombre completo")
                dada = pide("Contrasena (vacio: la genera el modulo)", obligatorio=False)
                usuario, clave = cuentas.crea_cuenta(s, correo, nombre, "student", entorno_id,
                                                     password=dada or None)
                print("\n   Alta de %s" % usuario.email)
                print("   Contrasena: %s" % clave)

            elif op == "5":
                entorno_id = elige(_opciones_entornos(s), "entorno")
                if not entorno_id:
                    continue
                ruta = pide("Ruta del archivo (columnas: correo, nombre)")
                creados, fallidos = cuentas.alta_por_lista(s, ruta, entorno_id)
                print("\n   Creadas %d cuentas, %d con problema." % (len(creados), len(fallidos)))
                for correo, motivo in fallidos:
                    print("      - %s: %s" % (correo, motivo))
                if creados:
                    destino = cuentas.exporta_credenciales(creados)
                    print("   Credenciales en: %s" % destino)
                    print("   Ese archivo lleva las contrasenas en claro: entreguelas y borrelo.")

            elif op == "6":
                busca = pide("Buscar la cuenta (correo o nombre)", obligatorio=False)
                user_id = elige(_opciones_usuarios(s, busca or None), "cuenta")
                if not user_id:
                    continue
                rol = elige([("student", "estudiante"), ("teacher", "docente"),
                             ("admin", "administrador"), ("", "no cambiar el rol")], "rol")
                mover = confirma("Cambiar tambien de entorno?") if rol is not None else False
                entorno_id = elige(_opciones_entornos(s), "entorno") if mover else None
                usuario = cuentas.cambia_rol_o_entorno(s, user_id, rol or None, entorno_id)
                print("   %s queda como %s, entorno %s" %
                      (usuario.email, usuario.role.value, usuario.environment_id or "-"))
                print("   El cambio surte efecto en la siguiente peticion.")

            elif op == "7":
                busca = pide("Buscar la cuenta (correo o nombre)", obligatorio=False)
                user_id = elige(_opciones_usuarios(s, busca or None), "cuenta")
                if not user_id:
                    continue
                dada = pide("Contrasena nueva (vacio: la genera el modulo)", obligatorio=False)
                usuario, clave = cuentas.restablece_password(s, user_id, dada or None)
                print("\n   Contrasena nueva de %s: %s" % (usuario.email, clave))
                print("   Aviso: las sesiones ya abiertas siguen validas hasta caducar.")
                print("   Para cerrarlas todas hay que cambiar el secreto (Configuracion).")

        except Exception as exc:
            s.rollback()
            print("\n   No se pudo completar: %s" % exc)


# -------------------------------------------------------------------- ENTORNOS
def menu_entornos(s):
    while True:
        titulo("ENTORNOS")
        print("   1. Ver entornos")
        print("   2. Crear un entorno para un docente")
        print("   3. Reasignar el docente de un entorno")
        print("   0. volver")
        op = pide("Opcion", obligatorio=False)

        if op == "0" or op == "":
            return
        try:
            if op == "1":
                for e in entornos.lista_entornos(s):
                    print("   %-32s %-10s docente: %-30s %2d doc, %2d estud." %
                          (e["nombre"][:32], e["estado"], e["docente"][:30],
                           e["documentos"], e["estudiantes"]))
                    print("      identificador: %s" % e["id"])

            elif op == "2":
                docentes = [(u.id, "%-38s %s" % (u.email, u.full_name))
                            for u in entornos.docentes_disponibles(s)]
                teacher_id = elige(docentes, "docente")
                if not teacher_id:
                    print("   Cree primero una cuenta de docente.")
                    continue
                nombre = pide("Nombre del entorno")
                descripcion = pide("Descripcion", obligatorio=False)
                area = pide("Area de conocimiento", obligatorio=False)
                nivel = pide("Nivel educativo", obligatorio=False)
                e = entornos.crea_entorno(s, nombre, teacher_id, descripcion, area, nivel)
                print("   Entorno '%s' creado y asignado." % e.name)
                print("   Identificador del entorno: %s" % e.id)

            elif op == "3":
                entorno_id = elige(_opciones_entornos(s), "entorno")
                if not entorno_id:
                    continue
                docentes = [(u.id, "%-38s %s" % (u.email, u.full_name))
                            for u in entornos.docentes_disponibles(s)]
                nuevo = elige(docentes, "nuevo docente")
                if not nuevo:
                    continue
                liberar = confirma("Retirar el entorno al docente anterior?")
                entornos.reasigna_docente(s, entorno_id, nuevo, liberar)
                print("   Entorno reasignado.")

        except Exception as exc:
            s.rollback()
            print("\n   No se pudo completar: %s" % exc)


# --------------------------------------------------------------- CONFIGURACION
def _muestra_paso(nombre, ok, detalle):
    print("   %-5s %s: %s" % ("OK" if ok else "FALLO", nombre, detalle))


def _aplica_efectos(efectos):
    """Encadena lo que el cambio arrastra, en vez de dejarlo como aviso."""
    if "sesiones_invalidadas" in efectos:
        print("   Aviso: al cambiar el secreto, todas las sesiones abiertas dejaran de valer.")
    if "reiniciar" in efectos:
        # Reiniciar NO aplica un cambio de config/.env, y
        # recrear no alcanza al servidor de embeddings ni libera la memoria que
        # Ollama deja ocupada. aplica_configuracion() hace las tres cosas.
        if confirma("El cambio necesita aplicarse: recrear los servicios, liberar la memoria "
                    "de modelos locales y reiniciar el servidor de embeddings si hace falta. "
                    "Aplicar ahora?"):
            ok, _ = operacion.aplica_configuracion(avance=_muestra_paso)
            print("   %s" % ("Cambio aplicado." if ok else "No se pudo aplicar entero."))
        else:
            print("   El cambio queda escrito pero NO esta activo hasta aplicarlo")
            print("   (Operacion > Aplicar la configuracion).")
    if "reindexar" in efectos:
        print("\n   IMPORTANTE: cambiar el proveedor o el modelo de embeddings invalida")
        print("   el indice. Hasta reindexar, el sistema responde con vectores que ya no")
        print("   corresponden, y lo hace sin avisar. Para pasar de un modo a otro con")
        print("   todo encadenado, use Operacion > Cambiar de modo.")


def menu_configuracion():
    while True:
        titulo("CONFIGURACION")
        print("   1. Ver configuracion vigente")
        print("   2. Cambiar modo de operacion (modelo, embeddings, reordenamiento)")
        print("   3. Cambiar un parametro")
        print("   4. Reponer una clave de API")
        print("   5. Restaurar una configuracion anterior")
        print("   0. volver")
        op = pide("Opcion", obligatorio=False)

        if op == "0" or op == "":
            return
        try:
            if op == "1":
                for clave, valor in configuracion.vista():
                    print("   %-28s %s" % (clave, valor))

            elif op == "2":
                clave = elige([(c, c) for c in configuracion.MODO], "que cambiar")
                if not clave:
                    continue
                actual = configuracion.lee_todo().get(clave, "")
                print("   Valor actual: %s" % actual)
                valor = elige([(v, v) for v in configuracion.OPCIONES[clave]], "valor")
                if not valor:
                    continue
                copia, efectos = configuracion.cambia_valor(clave, valor)
                print("   Guardado. Copia previa: %s" % copia.name)
                _aplica_efectos(efectos)

            elif op == "3":
                clave = elige([(c, c) for c in configuracion.PARAMETROS], "parametro")
                if not clave:
                    continue
                print("   Valor actual: %s" % configuracion.lee_todo().get(clave, "(sin definir)"))
                valor = pide("Valor nuevo")
                copia, efectos = configuracion.cambia_valor(clave, valor)
                print("   Guardado. Copia previa: %s" % copia.name)
                _aplica_efectos(efectos)

            elif op == "4":
                clave = elige([(c, c) for c in configuracion.CLAVES_SECRETAS], "clave")
                if not clave:
                    continue
                valor = pide("Valor nuevo (no se mostrara despues)")
                copia, efectos = configuracion.cambia_valor(clave, valor)
                print("   Guardado. Copia previa: %s" % copia.name)
                _aplica_efectos(efectos)

            elif op == "5":
                copias = [(str(p), "%s  (%s)" % (p.name, p.stat().st_size)) for p in configuracion.respaldos()]
                ruta = elige(copias, "copia")
                if not ruta:
                    continue
                if confirma("Se sustituira config/.env por esa copia."):
                    previa = configuracion.restaura_respaldo(ruta)
                    print("   Restaurada. La anterior quedo en %s" % previa.name)
                    _aplica_efectos(["reiniciar"])

        except Exception as exc:
            print("\n   No se pudo completar: %s" % exc)


# ------------------------------------------------------------------- OPERACION
def menu_operacion(s):
    while True:
        titulo("OPERACION")
        print("   1. Estado de los servicios")
        print("   2. Arrancar / detener / reiniciar")
        print("   3. Estado de salud del sistema")
        print("   4. Copia de seguridad de la base")
        print("   5. Reindexar el corpus de un entorno")
        print("   6. Restaurar la base desde una copia")
        print("   7. Cambiar de modo (nube / local)")
        print("   8. Aplicar la configuracion")
        print("   9. Reiniciar el servidor de embeddings")
        print("   0. volver")
        op = pide("Opcion", obligatorio=False)

        if op == "0" or op == "":
            return
        try:
            if op == "1":
                filas, problemas = operacion.estado_servicios()
                for servicio, estado in filas:
                    print("   %-12s %s" % (servicio, estado))
                for p in problemas:
                    print("   %s" % p)

            elif op == "2":
                accion = elige([("up", "arrancar"), ("restart", "reiniciar"),
                                ("recrear", "recrear (aplica cambios de .env)"),
                                ("stop", "detener")], "accion")
                if not accion:
                    continue
                servicio = elige([(x, x) for x in operacion.SERVICIOS] + [("", "todos")], "servicio")
                servicio = servicio or None
                if accion == "up":
                    ok, salida = operacion.arranca(servicio)
                elif accion == "restart":
                    ok, salida = operacion.reinicia(servicio)
                elif accion == "recrear":
                    ok, salida = operacion.recrea(servicio)
                else:
                    ok, salida = operacion.detiene(servicio)
                print("   %s" % ("Hecho." if ok else "No se pudo:\n%s" % salida))

            elif op == "3":
                m = operacion.modo_actual()
                print("   Modo: %s" % ((m["activo"] or "la configuracion dice %s, pero no corre asi"
                                        % m["escrito"]).upper()))
                for p in m["pendientes"]:
                    print("      - %s" % p)
                for ruta, codigo, cuerpo in operacion.salud():
                    print("   %-22s %s  %s" % (ruta, codigo if codigo else "sin respuesta", cuerpo))

            elif op == "4":
                destino = operacion.copia_seguridad()
                print("   Copia hecha: %s (%d bytes)" % (destino, destino.stat().st_size))

            elif op == "5":
                entorno_id = elige(_opciones_entornos(s), "entorno")
                if not entorno_id:
                    continue
                print("\n   Esto BORRA los documentos de ese entorno y los vuelve a cargar.")
                if not confirma("Es una operacion destructiva sobre el indice."):
                    continue
                correo = pide("Correo de una cuenta docente o administradora")
                clave = pide("Contrasena")
                subidos, fallidos = operacion.reindexa_corpus(entorno_id, correo, clave)
                print("   Cargados %d documentos, %d con problema." % (len(subidos), len(fallidos)))
                for nombre, motivo in fallidos:
                    print("      - %s: %s" % (nombre, motivo))

            elif op == "6":
                copias = [(str(p), "%s  (%d bytes)" % (p.name, p.stat().st_size))
                          for p in operacion.volcados_disponibles()]
                ruta = elige(copias, "copia")
                if not ruta:
                    continue
                print("\n   Esto SUSTITUYE el contenido actual de la base.")
                if not confirma("Se hara una copia de lo actual antes de restaurar."):
                    continue
                ok, salida, previa = operacion.restaura(ruta)
                print("   %s" % ("Restaurada." if ok else "Restaurada con avisos:"))
                if not ok:
                    print(salida)
                print("   Lo anterior quedo en %s" % previa.name)

            elif op == "7":
                m = operacion.modo_actual()
                print("   Modo actual: %s" % ((m["activo"] or "no coincide con la configuracion (%s)"
                                               % m["escrito"]).upper()))
                modo = elige([("local", "modo local: modelo y embeddings en la maquina"),
                              ("nube", "modo nube: Claude y Cohere")], "modo")
                if not modo:
                    continue
                modelo = None
                if modo == "local":
                    instalados, _, error = operacion.modelos_ollama()
                    if error:
                        print("   Ollama no responde: %s" % error)
                        continue
                    modelo = elige([(x, x) for x in instalados], "modelo local")
                    if not modelo:
                        continue
                lista = entornos.lista_entornos(s)
                con_corpus = [e for e in lista if e["documentos"]]
                if not con_corpus:
                    print("   No hay entornos con corpus que reindexar.")
                    continue
                print("   Se reindexaran:")
                for e in con_corpus:
                    print("      - %s (%d documentos)" % (e["nombre"], e["documentos"]))
                if not confirma("Copia la base y el indice, cambia la configuracion, aplica y "
                                "reindexa. Tarda varios minutos."):
                    continue
                correo = pide("Correo de una cuenta docente o administradora")
                clave = pide("Contrasena")
                ok, _ = operacion.cambia_modo(modo, [e["id"] for e in con_corpus], correo, clave,
                                              modelo_local=modelo,
                                              nombres={e["id"]: e["nombre"] for e in lista},
                                              avance=_muestra_paso)
                print("\n   %s" % ("Sistema en modo %s." % modo.upper() if ok else
                                   "El cambio no se completo: se detuvo en el paso marcado FALLO."))

            elif op == "8":
                ok, _ = operacion.aplica_configuracion(avance=_muestra_paso)
                print("   %s" % ("Configuracion aplicada." if ok else "No se pudo aplicar entera."))

            elif op == "9":
                ok, estado, cerrados = operacion.reinicia_embeddings()
                print("   %s" % ("Reiniciado: sirve %s." % estado.get("modelo") if ok
                                 else "No volvio a responder: %s" % estado.get("detalle")))

        except Exception as exc:
            print("\n   No se pudo completar: %s" % exc)


# ----------------------------------------------------------------------- INICIO
def arranque():
    titulo("ASISTENTE DE EDUCACION - Modulo de administracion")

    problemas = contexto.comprueba_requisitos()
    if problemas:
        print("\nNo estan dadas las condiciones para operar:\n")
        for p in problemas:
            print("   - %s" % p)
        return None

    ok, motivo = contexto.base_alcanzable()
    print("   Base de datos: %s" % ("accesible" if ok else "NO accesible - %s" % motivo))
    hay_docker, detalle = contexto.docker_disponible()
    print("   Docker:        %s" % (detalle if hay_docker else "no disponible - %s" % detalle))
    if not hay_docker:
        print("                  (Configuracion y Operacion quedaran limitadas)")

    if not ok:
        print("\n   Sin base de datos no se puede administrar cuentas ni entornos.")
        print("   Levante los servicios y vuelva a entrar.")
        return None

    contexto.prepara_directorios()
    return contexto.sesion()


def main():
    s = arranque()
    if s is None:
        return 1
    try:
        while True:
            titulo("MENU PRINCIPAL")
            print("   1. Cuentas")
            print("   2. Entornos")
            print("   3. Configuracion")
            print("   4. Operacion")
            print("   5. Ultimas operaciones registradas")
            print("   0. salir")
            op = pide("Opcion", obligatorio=False)

            if op in ("0", ""):
                print("\n   Hasta luego.\n")
                return 0
            if op == "1":
                menu_cuentas(s)
            elif op == "2":
                menu_entornos(s)
            elif op == "3":
                menu_configuracion()
            elif op == "4":
                menu_operacion(s)
            elif op == "5":
                for linea in registro.ultimas():
                    print("   %s  %-26s %s" % (linea["fecha"], linea["accion"], linea["detalle"]))
    finally:
        s.close()


if __name__ == "__main__":
    sys.exit(main())
