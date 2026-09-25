# -*- coding: utf-8 -*-
"""Bloque C - Configuracion.

Lee y escribe `config/.env`, que es el otro almacen comun: el sistema lo lee al
arrancar y de ahi salen el modo de operacion y los parametros.

TRES REGLAS QUE CUMPLE SIEMPRE.

1. Copia con marca de tiempo antes de cada modificacion, en respaldos/ del
   propio modulo.
2. Modifica SOLO la clave indicada. No reescribe el archivo entero: conserva
   comentarios, orden y lineas en blanco, porque ese archivo tiene explicaciones
   que valen tanto como los valores.
3. Las claves de API no se muestran completas, no se registran y no viajan a
   ninguna copia que salga de la maquina.

Y UNA ADVERTENCIA QUE NO ES OPCIONAL. Cambiar el proveedor de embeddings
invalida el indice: los vectores de un modelo no son comparables con los de
otro. Si se cambia y no se reindexa, el sistema sigue respondiendo, pero mal, y
sin avisar. Por eso `cambia_valor` devuelve que consecuencias arrastra el cambio,
para que quien llame las encadene en vez de dejarlas como nota.
"""
import io
import re
import shutil
from datetime import datetime

import contexto
import registro

# Valores admitidos, leidos del codigo del sistema y no inventados:
# llm/factory.py, pipeline/embedding_service.py y pipeline/reranker_service.py.
OPCIONES = {
    "LLM_PROVIDER": ["claude", "ollama"],
    "EMBEDDING_PROVIDER": ["cohere", "sentence-transformers"],
    "RERANKER_PROVIDER": ["cohere", "cross-encoder"],
}

CLAVES_SECRETAS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "COHERE_API_KEY",
                   "GOOGLE_API_KEY", "JWT_SECRET")

# Claves que no son secretas ENTERAS pero llevan una contrasena dentro. Su valor
# es util a la vista -el host, el puerto, la base- y por eso no se ocultan como
# las anteriores: se oculta solo la parte de la credencial.
#
# DATABASE_URL es `postgresql://usuario:contrasena@host:puerto/base`: mostrada
# entera, cualquier captura de la pantalla de configuracion expondria la
# contrasena de PostgreSQL.
CREDENCIAL_EMBEBIDA = ("DATABASE_URL",)

# `user:password@` dentro de una URL de conexion.
CREDENCIAL_EN_URL = re.compile(r"(?P<esquema>[A-Za-z0-9+.\-]+://)"
                               r"(?P<usuario>[^:/?#@\s]+):"
                               r"(?P<clave>[^@/\s]+)@")


def es_sensible(clave):
    """True si el valor no debe mostrarse ni registrarse tal cual."""
    return clave in CLAVES_SECRETAS or clave in CREDENCIAL_EMBEBIDA

MODO = ["LLM_PROVIDER", "EMBEDDING_PROVIDER", "RERANKER_PROVIDER"]

PARAMETROS = ["ENVIRONMENT", "DATABASE_URL", "CHROMA_HOST", "CHROMA_PORT",
              "EMBEDDING_MODEL", "EMBEDDING_SERVICE_URL", "OLLAMA_HOST", "OLLAMA_MODEL",
              "OLLAMA_TIMEOUT_SECONDS",
              "ACCESS_TOKEN_EXPIRE_MINUTES", "REFRESH_TOKEN_EXPIRE_DAYS", "CORS_ORIGINS"]

# Parametros que tienen que ser un numero positivo. El tiempo de espera del
# modelo local se expone porque en CPU un modelo pequeno puede tardar mas de
# 120 s en responder, y sin este parametro solo se cambiaria editando el .env.
NUMERICOS = ("OLLAMA_TIMEOUT_SECONDS",)


# Se declaran con chr() y no con secuencias de escape a proposito, para que
# ninguna herramienta de edicion las interprete antes de tiempo.
SALTO = chr(10)
RETORNO = chr(13)


class ErrorConfiguracion(Exception):
    pass


def _texto():
    if not contexto.ENV_PATH.is_file():
        raise ErrorConfiguracion("No se encuentra config/.env")
    return io.open(contexto.ENV_PATH, encoding="utf-8", newline="").read()


def _lineas():
    return _texto().split(SALTO)


def _es_crlf():
    """Si el archivo usa CRLF, la linea que se escriba debe usarlo tambien.

    Escribir sin tenerlo en cuenta dejaria el archivo con finales de linea
    mezclados -solo la linea modificada en LF-. No rompe la lectura, pero
    ensucia el archivo y deja un cambio invisible en cada linea que se toque.
    """
    texto = _texto()
    crlf = texto.count(RETORNO + SALTO)
    return crlf > (texto.count(SALTO) - crlf)


def lee_todo():
    """Las claves con su valor, tal como estan en el archivo."""
    valores = {}
    for linea in _lineas():
        limpia = linea.strip()
        if not limpia or limpia.startswith("#") or "=" not in limpia:
            continue
        clave, _, valor = limpia.partition("=")
        valores[clave.strip()] = valor.strip()
    return valores


def enmascara(clave, valor):
    """Un secreto se muestra por sus extremos, nunca completo.

    En una URL de conexion se tapa solo la contrasena: el host, el puerto y el
    nombre de la base son justo lo que hay que poder leer de un vistazo.
    """
    if not valor:
        return valor
    if clave in CREDENCIAL_EMBEBIDA:
        return CREDENCIAL_EN_URL.sub(
            lambda m: "%s%s:********@" % (m.group("esquema"), m.group("usuario")),
            valor)
    if clave not in CLAVES_SECRETAS:
        return valor
    if len(valor) <= 8:
        return "*" * len(valor)
    return "%s...%s  (%d caracteres)" % (valor[:4], valor[-4:], len(valor))


def vista(solo=None):
    """C1 - La configuracion vigente, con los secretos enmascarados."""
    valores = lee_todo()
    claves = solo or list(valores.keys())
    return [(c, enmascara(c, valores.get(c, ""))) for c in claves if c in valores]


def respalda():
    """Copia del .env antes de tocarlo. Devuelve la ruta.

    El nombre NUNCA se repite, y no es un detalle: con marca de tiempo al
    segundo, dos operaciones seguidas caerian en el mismo nombre y la segunda
    sobrescribiria la copia de la primera -cambiar un valor y restaurar acto
    seguido devolveria el archivo MODIFICADO-. Una copia de seguridad que se
    pisa a si misma es peor que no tenerla, porque se confia en ella.
    """
    contexto.prepara_directorios()
    marca = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    destino = contexto.DIR_RESPALDOS / ("env_%s.bak" % marca)
    n = 0
    while destino.exists():
        n += 1
        destino = contexto.DIR_RESPALDOS / ("env_%s_%d.bak" % (marca, n))
    shutil.copy2(contexto.ENV_PATH, destino)
    return destino


def consecuencias(clave, valor_anterior, valor_nuevo):
    """Que arrastra este cambio. Lista vacia es que basta con guardarlo."""
    efectos = []
    if valor_anterior == valor_nuevo:
        return efectos
    efectos.append("reiniciar")
    if clave == "EMBEDDING_PROVIDER":
        # El servidor de embeddings no es un contenedor: recrear no lo alcanza.
        efectos.append("reiniciar_embeddings")
    if clave == "EMBEDDING_PROVIDER" or clave == "EMBEDDING_MODEL":
        efectos.append("reindexar")
    if clave in ("LLM_PROVIDER", "OLLAMA_MODEL"):
        # Ollama deja fijado en RAM el modelo que se uso (keep_alive -1).
        efectos.append("liberar_modelos")
    if clave == "JWT_SECRET":
        efectos.append("sesiones_invalidadas")
    return efectos


def _comprueba_modelo_ollama(modelo):
    """Un modelo que Ollama no tiene instalado deja el modo local sin modelo.

    Si Ollama no responde no se puede comprobar, y no se bloquea el cambio por
    eso: Ollama solo tiene que estar arriba en modo local.
    """
    try:
        # La direccion y el cliente los da `operacion`, que es donde esta escrito
        # por que se traduce a 127.0.0.1 y por que el cliente HTTP se reutiliza.
        import operacion
        base = operacion._ollama_base()
        instalados = [m["name"] for m in operacion._cliente().get(
            base + "/api/tags", timeout=5).json().get("models", [])]
    except Exception:
        return

    def normal(nombre):
        return nombre if ":" in nombre else nombre + ":latest"

    if normal((modelo or "").strip()) not in {normal(m) for m in instalados}:
        raise ErrorConfiguracion("El modelo %s no esta instalado en Ollama. Instalados: %s"
                                 % (modelo, ", ".join(instalados) or "ninguno"))


def cambia_valor(clave, valor):
    """C2, C3, C4 - Escribe una clave conservando el resto del archivo.

    Devuelve (ruta_del_respaldo, efectos). Los efectos los encadena quien llama.
    """
    clave = clave.strip().upper()
    if clave in OPCIONES and valor not in OPCIONES[clave]:
        raise ErrorConfiguracion(
            "Valor no admitido para %s. Opciones: %s" % (clave, ", ".join(OPCIONES[clave]))
        )
    if clave in NUMERICOS:
        try:
            numero = float(valor)
        except (TypeError, ValueError):
            raise ErrorConfiguracion("%s tiene que ser un numero de segundos" % clave)
        if numero <= 0:
            raise ErrorConfiguracion("%s tiene que ser mayor que cero" % clave)
    if clave == "OLLAMA_MODEL":
        _comprueba_modelo_ollama(valor)

    lineas = _lineas()
    anterior = lee_todo().get(clave, "")

    cr = RETORNO if _es_crlf() else ""
    patron = re.compile(r"^(\s*)%s(\s*)=(.*)$" % re.escape(clave))
    encontrada = False
    for i, linea in enumerate(lineas):
        if patron.match(linea):
            lineas[i] = "%s=%s%s" % (clave, valor, cr)
            encontrada = True
            break

    if not encontrada:
        # Se anade al final, sin tocar nada de lo anterior.
        if lineas and lineas[-1].strip() != "":
            lineas.append(cr)
        lineas.append("%s=%s%s" % (clave, valor, cr))

    copia = respalda()
    io.open(contexto.ENV_PATH, "w", encoding="utf-8", newline="").write(SALTO.join(lineas))

    efectos = consecuencias(clave, anterior, valor)
    registro.anota("cambiar_configuracion", {
        "clave": clave,
        # DATABASE_URL entra aqui por la misma razon que no se muestra entera:
        # el registro es un archivo de texto y la contrasena no tiene por que
        # quedar escrita en el.
        "anterior": "(secreto)" if es_sensible(clave) else anterior,
        "nuevo": "(secreto)" if es_sensible(clave) else valor,
        "respaldo": str(copia),
        "efectos": efectos,
    })
    return copia, efectos


def restaura_respaldo(ruta):
    """Devuelve el .env a una copia anterior. Antes hace copia del actual."""
    ruta = str(ruta)
    copia = respalda()
    shutil.copy2(ruta, contexto.ENV_PATH)
    registro.anota("restaurar_configuracion", {"desde": ruta, "respaldo_previo": str(copia)})
    return copia


def respaldos():
    """Las copias disponibles, de la mas reciente a la mas antigua."""
    contexto.prepara_directorios()
    return sorted(contexto.DIR_RESPALDOS.glob("env_*.bak"), reverse=True)
