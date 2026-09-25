# -*- coding: utf-8 -*-
"""Bloque D - Operacion.

Servicios, salud, reindexacion del corpus, copia y restauracion, y el cambio de
modo de operacion -nube o local- de principio a fin.

POR QUE LA REINDEXACION NO LLAMA AL SCRIPT QUE YA EXISTE.
`codigo/scripts/indexar_corpus.py` lleva dentro un entorno y unas credenciales
fijos, escritos para una corrida concreta. Usarlo desde aqui obligaria a que el
operador supiera eso y a editarlo a mano cuando el entorno fuera otro, que es
justo lo que este modulo no debe dejar. Asi que la reindexacion se hace contra
la API publica del sistema -los mismos endpoints que usa el docente-, con el
entorno y las credenciales que se elijan en el momento. No se modifica ni el
script ni el sistema.

DOS COSAS SOBRE BORRAR.

1. `DELETE /corpus/environment/{id}` borra los documentos y tambien la
   coleccion del indice. Dejarla vacia conservaria la dimension del proveedor
   anterior, y cambiar de proveedor de embeddings fallaria al reindexar
   ("expecting embedding with dimension of 1024, got 384").
2. `corpus_versions` tiene clave foranea a `corpus_metadata`. Borrar un
   documento exige borrar antes sus versiones, o PostgreSQL lo rechaza. Vale
   tambien para una futura eliminacion de entornos.

LA COPIA Y LA RESTAURACION VAN POR EL CONTENEDOR. `pg_dump` y `pg_restore` viven
dentro de la imagen de PostgreSQL, asi que no hace falta instalarlos en la
maquina: se ejecutan con `docker exec` sobre el contenedor que ya corre.
"""
import os
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

import contexto
import registro

CONTENEDOR_BD = "asistente_postgres"
CONTENEDOR_INDICE = "asistente_chromadb"
SERVICIOS = ("postgres", "chromadb", "fastapi")
API = "http://127.0.0.1:8000"

_CLIENTE = None


def _cliente():
    """Un solo cliente HTTP para todas las llamadas del modulo.

    `httpx.get(...)` construye un cliente nuevo en cada llamada, y construirlo
    cuesta del orden de medio segundo -lo que tarda en cargar el paquete de
    certificados de `certifi` en un contexto SSL-. La conexion en si no cuesta
    casi nada. La pantalla de Salud encadena cinco consultas y pagaria ese peaje
    cinco veces.

    Se reutiliza el cliente, no la conexion: `max_keepalive_connections=0` evita
    que quede en el pozo una conexion a un servicio que este modulo acaba de
    reiniciar, que es lo que hace media docena de veces al cambiar de modo.
    """
    global _CLIENTE
    if _CLIENTE is None:
        import httpx
        _CLIENTE = httpx.Client(timeout=15.0,
                                limits=httpx.Limits(max_keepalive_connections=0))
    return _CLIENTE


class ErrorOperacion(Exception):
    pass


def _primera(exc):
    texto = str(exc).strip()
    return texto.splitlines()[0][:200] if texto else type(exc).__name__


def _compose(*args, timeout=300):
    orden = ["docker", "compose", "-f", str(contexto.COMPOSE_PATH)] + list(args)
    try:
        r = subprocess.run(orden, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise ErrorOperacion("docker no esta disponible en esta maquina")
    except subprocess.TimeoutExpired:
        raise ErrorOperacion("La orden tardo demasiado y se interrumpio")
    return r


def estado_servicios():
    """Que contenedores estan levantados."""
    r = _compose("ps", "--format", "{{.Service}} {{.State}}", timeout=60)
    if r.returncode != 0:
        return [], (r.stderr or r.stdout).strip().splitlines()[:2]
    filas = [l.split(None, 1) for l in r.stdout.strip().splitlines() if l.strip()]
    return [(f[0], f[1] if len(f) > 1 else "?") for f in filas], []


def arranca(servicio=None):
    """Levanta todo o un servicio concreto."""
    args = ["up", "-d"] + ([servicio] if servicio else [])
    r = _compose(*args)
    registro.anota("arrancar_servicios", {"servicio": servicio or "todos"},
                   "ok" if r.returncode == 0 else "error")
    return r.returncode == 0, (r.stderr or r.stdout).strip()[-800:]


def detiene(servicio=None):
    """Detiene todo o un servicio concreto."""
    args = (["stop", servicio] if servicio else ["down"])
    r = _compose(*args)
    registro.anota("detener_servicios", {"servicio": servicio or "todos"},
                   "ok" if r.returncode == 0 else "error")
    return r.returncode == 0, (r.stderr or r.stdout).strip()[-800:]


def reinicia(servicio=None):
    """Reinicio de los procesos. NO basta para un cambio de config/.env.

    Con `LLM_PROVIDER=ollama` ya escrito en el archivo, tras esta llamada
    `docker exec asistente_fastapi printenv LLM_PROVIDER` sigue respondiendo el
    valor anterior, y `/health/llm` tambien.

    El motivo es que el backend no lee config/.env: dentro del contenedor esa
    ruta ni existe -los volumenes montados son /app/app, /app/pipeline y
    /app/corpus-. Lee variables de entorno, y compose las fija al CREAR el
    contenedor a partir de `env_file`. `restart` para y arranca el mismo
    contenedor, con el entorno que ya traia. Para un cambio de configuracion hay
    que recrearlo: ver `recrea()`.

    Sigue sirviendo para lo suyo: volver a arrancar un proceso trabado o releer
    el codigo montado por volumen, que si cambia en caliente.
    """
    args = ["restart"] + ([servicio] if servicio else list(SERVICIOS))
    r = _compose(*args)
    registro.anota("reiniciar_servicios", {"servicio": servicio or "todos"},
                   "ok" if r.returncode == 0 else "error")
    return r.returncode == 0, (r.stderr or r.stdout).strip()[-800:]


def recrea(servicio=None):
    """Lo que hace efectivo un cambio de config/.env EN LOS CONTENEDORES.

    Es `docker compose up -d`: compose compara la configuracion resuelta -y el
    contenido de `env_file` entra en esa comparacion- y recrea solo los
    servicios cuya definicion cambio. Los demas los deja corriendo: un cambio
    de proveedor recrea `asistente_fastapi` sin tocar postgres ni chromadb.

    No alcanza al servidor de embeddings del 8500, que no es un contenedor. Lo
    que aplica un cambio entero es `aplica_configuracion()`.
    """
    args = ["up", "-d"] + ([servicio] if servicio else [])
    r = _compose(*args)
    registro.anota("recrear_servicios", {"servicio": servicio or "todos"},
                   "ok" if r.returncode == 0 else "error")
    return r.returncode == 0, (r.stderr or r.stdout).strip()[-800:]


def salud():
    """Estado del sistema, leido de donde cada dato es CIERTO.

    La fila de embeddings no sale de `/health/embeddings` del backend, que
    devuelve el valor de EMBEDDING_MODEL del .env sin mirar que proveedor esta
    activo, sino del propio servidor de embeddings; igual con Ollama y con el
    indice.

    Conserva la forma de siempre -(etiqueta, codigo, cuerpo)-, asi que la consola
    y la web la pintan sin cambios.
    """
    try:
        import httpx
    except ImportError:
        raise ErrorOperacion("Falta httpx; ejecutar con el interprete del backend")

    resultados = []
    for ruta in ("/health", "/health/llm"):
        try:
            r = _cliente().get(API + ruta, timeout=15.0)
            resultados.append((ruta, r.status_code, r.text.strip()[:160]))
        except Exception as exc:
            resultados.append((ruta, None, _primera(exc)))

    emb = estado_embeddings()
    if emb["responde"]:
        extra = "" if emb.get("max_seq_length") is None else \
            ", hasta %s tokens por fragmento (modelo local)" % emb["max_seq_length"]
        resultados.append(("embeddings (8500)", 200, "sirve %s%s" % (emb["modelo"], extra)))
    else:
        resultados.append(("embeddings (8500)", None, emb.get("detalle") or "sin respuesta"))

    disponibles, cargados, error = modelos_ollama()
    if error:
        resultados.append(("ollama", None, "no responde (solo hace falta en modo local): %s" % error))
    else:
        resultados.append(("ollama", 200, "en memoria: %s · instalados: %s"
                           % (", ".join(cargados) or "ninguno", ", ".join(disponibles) or "ninguno")))

    # El frontend no esta en el compose ni lo administra este modulo, pero es por
    # donde entra el estudiante: sin esta fila, con Vite caido la consola pintaria
    # todo en verde y nadie podria entrar. Se mira, no se opera.
    origen = _frontend_base()
    if origen:
        etiqueta = "frontend (%s)" % origen.rsplit(":", 1)[-1]
        try:
            r = _cliente().get(origen, timeout=5.0)
            resultados.append((etiqueta, r.status_code,
                               "responde en %s" % origen if r.status_code == 200
                               else "responde %d en %s" % (r.status_code, origen)))
        except Exception as exc:
            resultados.append((etiqueta,
                               None,
                               "no responde en %s: el estudiante no puede entrar (%s)"
                               % (origen, _primera(exc))))

    try:
        for c in estado_indice()[:6]:
            resultados.append(("indice %s" % (c["entorno"] or c["coleccion"])[:8], 200,
                               "%s dimensiones, %s fragmentos" % (c["dimension"], c["fragmentos"])))
    except Exception as exc:
        resultados.append(("indice", None, _primera(exc)))
    return resultados


def _token(correo, password):
    import httpx
    r = _cliente().post(API + "/auth/login", json={"email": correo, "password": password},
                        timeout=30.0)
    if r.status_code != 200:
        raise ErrorOperacion("No se pudo iniciar sesion: %s" % r.text[:160])
    return r.json()["access_token"]


def reindexa_corpus(environment_id, correo, password, purgar=True, corpus_dir=None):
    """Vuelve a cargar el corpus de un entorno. DESTRUCTIVO sobre el indice.

    Purga los documentos del entorno y sube de nuevo todos los archivos de
    corpus/fuente. Devuelve (subidos, fallidos).
    """
    import httpx

    carpeta = Path(corpus_dir or (contexto.RAIZ / "corpus" / "fuente"))
    if not carpeta.is_dir():
        raise ErrorOperacion("No se encuentra la carpeta del corpus: %s" % carpeta)

    archivos = sorted([p for p in carpeta.iterdir() if p.suffix.lower() in (".pdf", ".txt", ".md")])
    if not archivos:
        raise ErrorOperacion("No hay archivos que cargar en %s" % carpeta)

    token = _token(correo, password)
    cabeceras = {"Authorization": "Bearer %s" % token}

    if purgar:
        r = _cliente().request("DELETE", "%s/corpus/environment/%s" % (API, environment_id),
                          headers=cabeceras, timeout=120.0)
        if r.status_code not in (200, 204):
            raise ErrorOperacion("No se pudo purgar el corpus del entorno: %s" % r.text[:200])

    subidos, fallidos = [], []
    for archivo in archivos:
        try:
            with open(archivo, "rb") as f:
                r = _cliente().post(
                    "%s/corpus/upload" % API,
                    headers=cabeceras,
                    files={"file": (archivo.name, f, "application/octet-stream")},
                    data={"environment_id": environment_id},
                    timeout=300.0,
                )
            if r.status_code in (200, 201):
                subidos.append(archivo.name)
            else:
                fallidos.append((archivo.name, r.text[:160]))
        except Exception as exc:
            fallidos.append((archivo.name, str(exc).splitlines()[0][:160]))

    registro.anota("reindexar_corpus", {"entorno": environment_id, "purgado": purgar,
                                        "subidos": len(subidos), "fallidos": len(fallidos)})
    return subidos, fallidos


def _nombre_bd():
    """La base a la que apunta el sistema, sacada de DATABASE_URL."""
    url = contexto.ajustes().database_url
    m = re.search(r"/([^/?]+)(\?|$)", url)
    return m.group(1) if m else "asistente_educacion"


def copia_seguridad(etiqueta="manual", bd=None):
    """Volcado de la base con pg_dump dentro del contenedor.

    `bd` permite volcar una base distinta de la que usa el sistema. Sirve para
    trabajar sobre un espejo sin tocar `DATABASE_URL`, que es configuracion del
    sistema y no deberia moverse para hacer una prueba.
    """
    contexto.prepara_directorios()
    marca = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    destino = contexto.DIR_RESPALDOS / ("bd_%s_%s.dump" % (etiqueta, marca))
    bd = bd or _nombre_bd()

    orden = ["docker", "exec", CONTENEDOR_BD, "pg_dump", "-U", "postgres", "-F", "c", "-d", bd]
    try:
        r = subprocess.run(orden, capture_output=True, timeout=900)
    except FileNotFoundError:
        raise ErrorOperacion("docker no esta disponible en esta maquina")
    if r.returncode != 0:
        raise ErrorOperacion("pg_dump fallo: %s" % r.stderr.decode("utf-8", "replace")[:300])

    destino.write_bytes(r.stdout)
    registro.anota("copia_seguridad", {"archivo": str(destino), "bytes": destino.stat().st_size})
    return destino


def copia_indice(etiqueta="manual"):
    """Copia del indice semantico: el /data del contenedor de Chroma.

    Chroma persiste en /data, que es donde esta montado el volumen: ahi vive el
    indice, y cambiar de modo lo reconstruye.
    """
    contexto.prepara_directorios()
    marca = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    destino = contexto.DIR_RESPALDOS / ("indice_%s_%s.tar.gz" % (etiqueta, marca))
    try:
        with open(destino, "wb") as salida:
            r = subprocess.run(["docker", "exec", CONTENEDOR_INDICE, "tar", "czf", "-", "-C", "/", "data"],
                               stdout=salida, stderr=subprocess.PIPE, timeout=900)
    except FileNotFoundError:
        raise ErrorOperacion("docker no esta disponible en esta maquina")
    if r.returncode != 0 or destino.stat().st_size < 1024:
        tamano = destino.stat().st_size
        destino.unlink(missing_ok=True)
        raise ErrorOperacion("La copia del indice fallo o salio vacia (%d bytes): %s"
                             % (tamano, r.stderr.decode("utf-8", "replace")[:200]))
    registro.anota("copia_indice", {"archivo": str(destino), "bytes": destino.stat().st_size})
    return destino


def restaura(ruta_dump, bd=None):
    """Restaura un volcado. DESTRUCTIVO: sustituye el contenido de la base.

    Hace copia de lo que hay antes de tocar nada, para poder volver. `bd` permite
    restaurar sobre una base distinta de la del sistema -un espejo-, sin tocar
    `DATABASE_URL`.
    """
    ruta = Path(ruta_dump)
    if not ruta.is_file():
        raise ErrorOperacion("No se encuentra el archivo %s" % ruta)

    destino_bd = bd or _nombre_bd()
    previa = copia_seguridad(etiqueta="previa_restauracion", bd=destino_bd)

    interno = "/tmp/%s" % ruta.name
    r = subprocess.run(["docker", "cp", str(ruta), "%s:%s" % (CONTENEDOR_BD, interno)],
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise ErrorOperacion("No se pudo copiar el volcado al contenedor: %s" % r.stderr[:200])

    r = subprocess.run(
        ["docker", "exec", CONTENEDOR_BD, "pg_restore", "-U", "postgres", "-d", destino_bd,
         "--clean", "--if-exists", interno],
        capture_output=True, text=True, timeout=900)

    # pg_restore devuelve != 0 por avisos que no son fallos; se informa entero.
    salida = (r.stderr or r.stdout).strip()[-1200:]
    registro.anota("restaurar_base", {"desde": str(ruta), "base": destino_bd,
                                      "copia_previa": str(previa), "codigo": r.returncode},
                   "ok" if r.returncode == 0 else "con_avisos")
    return r.returncode == 0, salida, previa


def volcados_disponibles():
    """Volcados que el modulo puede restaurar: los suyos y los del proyecto."""
    contexto.prepara_directorios()
    propios = sorted(contexto.DIR_RESPALDOS.glob("bd_*.dump"), reverse=True)
    del_proyecto = sorted((contexto.RAIZ / "scratch_backup").glob("*.dump"), reverse=True)
    return propios + del_proyecto


# ==========================================================================
# Modo de operacion: nube o local
# ==========================================================================
# El sistema tiene tres piezas con proveedor: el modelo de lenguaje, los
# embeddings y el reordenamiento. En modo NUBE el modelo es Claude y los
# embeddings Cohere; en modo LOCAL el modelo corre en Ollama y los embeddings en
# la propia maquina. El reordenamiento es local en los dos (cross-encoder).
#
# Cambiar de modo no es cambiar dos claves. Arrastra siete cosas:
#   1. escribir las claves
#   2. recrear los contenedores
#   3. descargar de la RAM el modelo local que ya no se usa -Ollama los deja
#      fijados por keep_alive -1-
#   4. reiniciar el servidor de embeddings, que no es un contenedor y lee el
#      proveedor una sola vez al arrancar
#   5. comprobar que sirve el modelo que toca
#   6. reindexar, porque los vectores de un modelo y otro no tienen la misma
#      dimension (1024 frente a 384)
#   7. comprobar que el indice quedo con la dimension del modelo nuevo
# `cambia_modo()` hace las siete, con comprobaciones antes de tocar nada y
# copia de la base y del indice.

MODOS = {
    "nube": {"LLM_PROVIDER": "claude", "EMBEDDING_PROVIDER": "cohere"},
    "local": {"LLM_PROVIDER": "ollama", "EMBEDDING_PROVIDER": "sentence-transformers"},
}
PUERTO_EMBEDDINGS = 8500


def _valores():
    import configuracion
    return configuracion.lee_todo()


def _en_la_maquina(url, predeterminada):
    """Las URL del .env vistas desde fuera de Docker.

    Se traduce a 127.0.0.1 y NO a localhost: Ollama escucha en 127.0.0.1 y el
    servidor de embeddings en 0.0.0.0, los dos solo en IPv4. En Windows,
    `localhost` intenta primero ::1, espera ~2 s a que falle y reintenta por
    IPv4, y la pantalla de Salud encadena varias llamadas.
    """
    return ((url or predeterminada)
            .replace("host.docker.internal", "127.0.0.1")
            .replace("localhost", "127.0.0.1")
            .rstrip("/"))


def _ollama_base():
    return _en_la_maquina(_valores().get("OLLAMA_HOST"), "http://localhost:11434")


def _embeddings_base():
    return _en_la_maquina(_valores().get("EMBEDDING_SERVICE_URL"),
                          "http://localhost:%d" % PUERTO_EMBEDDINGS)


def _frontend_base():
    """La direccion del frontend, leida de donde el sistema la declara.

    Sale de `CORS_ORIGINS` del .env -el origen al que el backend le abre la
    puerta-, no de un valor escrito aqui: si alguien mueve el frontend, esa
    clave es la que tiene que cambiar de todos modos.

    OJO, ESTA NO SE TRADUCE A 127.0.0.1, al reves que las demas: Vite escucha
    SOLO en ::1, asi que por 127.0.0.1 no responde y por `localhost` si -en
    Windows se intenta ::1 primero-. La regla de `_en_la_maquina()` vale para
    Ollama y para el servidor de embeddings, que escuchan solo en IPv4; aqui es
    justo al contrario.
    """
    origenes = (_valores().get("CORS_ORIGINS") or "").split(",")
    primero = origenes[0].strip().rstrip("/")
    return primero or None


def _puerto_chroma():
    """El puerto de Chroma EN LA MAQUINA, que no es el del .env.

    `CHROMA_PORT=8000` es el puerto de dentro de Docker; desde fuera, en el 8000
    responde el backend. El que vale aqui es el que publica el compose.
    """
    try:
        texto = contexto.COMPOSE_PATH.read_text(encoding="utf-8")
        m = re.search(r"chromadb:.*?ports:\s*-\s*\"(\d+):8000\"", texto, re.S)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return 8001


def _constante(archivo, nombre):
    """Lee `NOMBRE = "valor"` del codigo del pipeline sin importarlo.

    Importar el pipeline arrastra sentence_transformers, que el interprete del
    backend -con el que corre este modulo- no tiene.
    """
    texto = (contexto.RAIZ / "codigo" / "pipeline" / archivo).read_text(encoding="utf-8")
    m = re.search(r'^%s\s*=\s*"([^"]+)"' % re.escape(nombre), texto, re.M)
    if not m:
        raise ErrorOperacion("No se encuentra %s en codigo/pipeline/%s" % (nombre, archivo))
    return m.group(1)


def modelo_embeddings_esperado(proveedor=None):
    """El modelo que el servidor de embeddings DEBE servir con ese proveedor.

    Sale del codigo del pipeline y no del .env: el servidor ignora
    EMBEDDING_MODEL y usa la constante de su propio codigo.
    """
    proveedor = proveedor or _valores().get("EMBEDDING_PROVIDER") or "sentence-transformers"
    if proveedor == "cohere":
        return _constante("cohere_embedding_client.py", "DEFAULT_MODEL_NAME")
    return _constante("embedding_service.py", "DEFAULT_MODEL_NAME")


def _normaliza_modelo(nombre):
    nombre = (nombre or "").strip()
    return nombre if ":" in nombre else nombre + ":latest"


def modelos_ollama():
    """(instalados, en_memoria, error). Si Ollama no responde: ([], [], motivo)."""
    import httpx
    base = _ollama_base()
    try:
        instalados = [m["name"] for m in _cliente().get(base + "/api/tags",
                                                        timeout=10).json().get("models", [])]
        cargados = [m["name"] for m in _cliente().get(base + "/api/ps",
                                                      timeout=10).json().get("models", [])]
        return instalados, cargados, None
    except Exception as exc:
        return [], [], _primera(exc)


def descarga_modelos_ollama(conservar=None):
    """Saca de la RAM los modelos de Ollama que no son el activo.

    El cliente de Ollama del sistema pide keep_alive -1: cada modelo que se usa
    queda fijado en memoria para siempre. Al cambiar de modelo o de modo, el
    anterior seguiria ocupando RAM. Devuelve (descargados, error).
    """
    import httpx
    _, cargados, error = modelos_ollama()
    if error:
        return [], error
    base = _ollama_base()
    objetivo = _normaliza_modelo(conservar) if conservar else None
    descargados = []
    for nombre in cargados:
        if objetivo and _normaliza_modelo(nombre) == objetivo:
            continue
        try:
            _cliente().post(base + "/api/generate", json={"model": nombre, "keep_alive": 0},
                            timeout=120)
            descargados.append(nombre)
        except Exception as exc:
            return descargados, "No se pudo descargar %s: %s" % (nombre, _primera(exc))
    registro.anota("descargar_modelos_ollama", {"descargados": descargados, "conservado": conservar})
    return descargados, None


def estado_embeddings(dimension=False):
    """Lo que sirve DE VERDAD el servidor de embeddings, preguntandole a el.

    Con `dimension=True` vectoriza una frase para medir la dimension real. No se
    hace por defecto: en modo nube cada comprobacion es una llamada de pago a
    Cohere, y la pantalla de salud se pinta en cada visita.
    """
    import httpx
    base = _embeddings_base()
    try:
        datos = _cliente().get(base + "/health", timeout=10).json()
    except Exception as exc:
        return {"responde": False, "modelo": None, "detalle": _primera(exc)}
    salida = {"responde": datos.get("status") == "ok", "modelo": datos.get("model"),
              "max_seq_length": datos.get("max_seq_length"), "detalle": datos.get("detail")}
    if dimension and salida["responde"]:
        try:
            r = _cliente().post(base + "/embed_text", json={"text": "comprobacion de dimension"},
                                timeout=120)
            salida["dimension"] = len(r.json()["embedding"])
        except Exception as exc:
            salida["dimension"] = None
            salida["detalle"] = _primera(exc)
    return salida


def estado_indice():
    """Colecciones del indice semantico: entorno, dimension y fragmentos."""
    import httpx
    base = ("http://127.0.0.1:%d/api/v2/tenants/default_tenant/databases/"
            "default_database/collections" % _puerto_chroma())
    salida = []
    for c in _cliente().get(base, timeout=10).json():
        nombre = c.get("name", "")
        n = _cliente().get("%s/%s/count" % (base, c["id"]), timeout=10).json()
        salida.append({"coleccion": nombre,
                       "entorno": nombre[len("corpus_"):] if nombre.startswith("corpus_") else None,
                       "dimension": c.get("dimension"), "fragmentos": n})
    return salida


def modo_actual():
    """Que modo dice la configuracion y si lo que corre coincide con ello.

    No basta con que el .env diga "local": tiene que estar corriendo en local.
    """
    import httpx
    v = _valores()
    llm, emb = v.get("LLM_PROVIDER"), v.get("EMBEDDING_PROVIDER")
    escrito = next((m for m, claves in MODOS.items()
                    if claves["LLM_PROVIDER"] == llm and claves["EMBEDDING_PROVIDER"] == emb), "mixto")

    pendientes = []
    activo_llm = None
    try:
        activo_llm = _cliente().get(API + "/health/llm", timeout=15).json()
    except Exception as exc:
        pendientes.append("el backend no responde: %s" % _primera(exc))
    if activo_llm:
        if activo_llm.get("provider") != llm:
            pendientes.append("el backend usa %s y la configuracion dice %s: falta aplicar el cambio"
                              % (activo_llm.get("provider"), llm))
        elif llm == "ollama" and _normaliza_modelo(activo_llm.get("model")) != _normaliza_modelo(v.get("OLLAMA_MODEL")):
            pendientes.append("el backend usa %s y la configuracion dice %s: falta aplicar el cambio"
                              % (activo_llm.get("model"), v.get("OLLAMA_MODEL")))

    emb_estado = estado_embeddings()
    esperado = modelo_embeddings_esperado(emb)
    if not emb_estado["responde"]:
        pendientes.append("el servidor de embeddings no responde")
    elif emb_estado["modelo"] != esperado:
        pendientes.append("el servidor de embeddings sirve %s y la configuracion pide %s: falta reiniciarlo"
                          % (emb_estado["modelo"], esperado))

    return {
        "escrito": escrito,
        "activo": escrito if not pendientes and escrito != "mixto" else None,
        "llm": llm,
        "modelo_llm": (activo_llm or {}).get("model"),
        "embeddings": emb,
        "modelo_embeddings": emb_estado.get("modelo"),
        "pendientes": pendientes,
    }


def _escucha(puerto):
    """PID que escucha en ese puerto, en IPv4 o IPv6, o None.

    No usa `netstat -p TCP`, que solo lista IPv4: el frontend de Vite escucha en
    [::1] y apareceria como puerto libre estando ocupado.
    """
    r = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=30)
    for linea in r.stdout.splitlines():
        partes = linea.split()
        if (len(partes) >= 5 and partes[0].upper() == "TCP" and partes[1].endswith(":%d" % puerto)
                and partes[3].upper() in ("LISTENING", "ESCUCHANDO")):
            return int(partes[4])
    return None


def _ventanas_embeddings():
    """Las ventanas cmd que corren el servidor de embeddings, vivas o huerfanas.

    Cerrar solo el proceso que escucha deja la ventana abierta y vacia, y tras
    varios reinicios se acumulan.
    """
    filtro = ("Get-CimInstance Win32_Process -Filter \"Name='cmd.exe'\" | "
              "Where-Object { $_.CommandLine -like '*pipeline.embedding_server*' } | "
              "ForEach-Object { $_.ProcessId }")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", filtro],
                       capture_output=True, text=True, timeout=60)
    return [int(x) for x in r.stdout.split() if x.strip().isdigit()]


def _uvicorn_del_sistema():
    """El uvicorn con que iniciar_sistema.bat levanta el 8500: el del PATH.

    Se salta el entorno virtual del backend a proposito. El modulo corre con ese
    interprete, y ese interprete no tiene sentence_transformers: un servidor de
    embeddings lanzado desde ahi no podria servir el modo local.
    """
    venv = os.path.normcase(os.path.abspath(str(contexto.BACKEND / "venv")))
    for carpeta in os.environ.get("PATH", "").split(os.pathsep):
        if not carpeta.strip():
            continue
        if os.path.normcase(os.path.abspath(carpeta)).startswith(venv):
            continue
        candidato = Path(carpeta) / "uvicorn.exe"
        if candidato.is_file():
            return candidato
    return None


def reinicia_embeddings(espera=180):
    """Cierra y vuelve a abrir el servidor de embeddings.

    El servidor no es un contenedor, lo levanta iniciar_sistema.bat en su propia ventana, y lee el
    proveedor una sola vez al construirse, asi que ni reiniciar ni recrear los
    contenedores lo alcanzan. Se relanza EXACTAMENTE como lo hace ese .bat -misma
    ventana, mismo directorio, mismo comando-. Devuelve (ok, estado, cerrados).
    """
    uvicorn = _uvicorn_del_sistema()
    if uvicorn is None:
        raise ErrorOperacion("No se encuentra uvicorn fuera del entorno virtual del backend; "
                             "es el que usa iniciar_sistema.bat para el servidor de embeddings")

    cerrados = []
    for pid in filter(None, [_escucha(PUERTO_EMBEDDINGS)] + _ventanas_embeddings()):
        r = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            cerrados.append(pid)

    for _ in range(30):
        if _escucha(PUERTO_EMBEDDINGS) is None:
            break
        time.sleep(1)
    else:
        raise ErrorOperacion("El puerto %d sigue ocupado despues de cerrar el servidor" % PUERTO_EMBEDDINGS)

    entorno = dict(os.environ)
    entorno["PATH"] = str(uvicorn.parent) + os.pathsep + entorno.get("PATH", "")
    codigo = contexto.RAIZ / "codigo"
    orden = ('start "Embedding Server" /D "%s" cmd /k uvicorn pipeline.embedding_server:app '
             '--host 0.0.0.0 --port %d' % (codigo, PUERTO_EMBEDDINGS))
    # Sin heredar la entrada ni la salida de quien llama. Si no, la ventana nueva
    # se queda con esos descriptores: con la salida del modulo redirigida a una
    # tuberia, el lector de la tuberia no recibe nunca el final y se cuelga
    # mientras el servidor de embeddings siga abierto.
    subprocess.Popen(orden, shell=True, env=entorno, cwd=str(codigo),
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, close_fds=True)

    inicio = time.time()
    estado = {"responde": False, "modelo": None, "detalle": "no arranco"}
    while time.time() - inicio < espera:
        time.sleep(3)
        estado = estado_embeddings()
        if estado["responde"]:
            break
    segundos = round(time.time() - inicio)
    registro.anota("reiniciar_servidor_embeddings",
                   {"cerrados": cerrados, "modelo": estado.get("modelo"), "segundos": segundos},
                   "ok" if estado["responde"] else "error")
    return estado["responde"], estado, cerrados


def _espera_backend(espera=120):
    import httpx
    inicio, ultimo = time.time(), ""
    while time.time() - inicio < espera:
        try:
            r = _cliente().get(API + "/health", timeout=5)
            if r.status_code == 200:
                return True, "respondio en %d s" % (time.time() - inicio)
            ultimo = "HTTP %d" % r.status_code
        except Exception as exc:
            ultimo = _primera(exc)
        time.sleep(3)
    return False, "no respondio en %d s: %s" % (espera, ultimo)


def aplica_configuracion(avance=None):
    """Hace efectivo un cambio de modo o de modelo, entero.

    Recrea los contenedores, espera al backend, comprueba que el proveedor de
    lenguaje activo es el configurado, descarga de la RAM los modelos locales
    que ya no se usan, y reinicia el servidor de embeddings si no sirve el
    modelo que la configuracion pide. No reindexa: eso lo decide quien llama,
    porque es destructivo y necesita credenciales.

    Devuelve (ok, pasos), con pasos = [(nombre, ok, detalle)].
    """
    import httpx
    pasos = []

    def paso(nombre, ok, detalle):
        pasos.append((nombre, ok, detalle))
        if avance:
            avance(nombre, ok, detalle)
        return ok

    ok, salida = recrea()
    if not paso("Recrear los servicios", ok, "hecho" if ok else salida[-300:]):
        return False, pasos

    ok, detalle = _espera_backend()
    if not paso("Esperar al backend", ok, detalle):
        return False, pasos

    v = _valores()
    try:
        llm = _cliente().get(API + "/health/llm", timeout=30).json()
    except Exception as exc:
        llm = {"provider": None, "model": None, "available": False, "error": _primera(exc)}
    ok = (llm.get("provider") == v.get("LLM_PROVIDER") and bool(llm.get("available"))
          and (v.get("LLM_PROVIDER") != "ollama"
               or _normaliza_modelo(llm.get("model")) == _normaliza_modelo(v.get("OLLAMA_MODEL"))))
    if not paso("Modelo de lenguaje activo", ok, "%s / %s%s" % (
            llm.get("provider"), llm.get("model"), "" if llm.get("available") else " (no disponible)")):
        return False, pasos

    conservar = v.get("OLLAMA_MODEL") if v.get("LLM_PROVIDER") == "ollama" else None
    descargados, error = descarga_modelos_ollama(conservar)
    paso("Liberar la memoria de modelos locales que no se usan", True,
         ("descargados: %s" % ", ".join(descargados)) if descargados else
         ("ninguno que liberar" if error is None else "Ollama no responde; no hay nada que liberar"))

    esperado = modelo_embeddings_esperado(v.get("EMBEDDING_PROVIDER"))
    actual = estado_embeddings()
    if actual["responde"] and actual["modelo"] == esperado:
        paso("Servidor de embeddings", True, "ya sirve %s" % esperado)
    else:
        ok, estado, _ = reinicia_embeddings()
        ok = ok and estado.get("modelo") == esperado
        if not paso("Reiniciar el servidor de embeddings", ok,
                    "sirve %s (se esperaba %s)" % (estado.get("modelo"), esperado)):
            return False, pasos

    registro.anota("aplicar_configuracion", {"pasos": len(pasos)}, "ok")
    return True, pasos


def cambia_modo(modo, entornos_ids, correo, password, modelo_local=None, nombres=None, avance=None):
    """Pasa el sistema a modo nube o a modo local, de principio a fin.

    Antes de tocar nada comprueba lo que podria dejarlo a medias -Docker, Ollama
    y el modelo elegido, las claves del modo nube, las credenciales, los
    entornos y el uvicorn del sistema- y aborta sin escribir si falta algo. Luego
    copia la base y el indice, escribe las claves, aplica el cambio entero,
    reindexa los entornos elegidos y comprueba que cada indice quedo con la
    dimension que produce el servidor de embeddings nuevo.

    Si un paso falla se detiene ahi y lo dice. Las copias del .env, de la base y
    del indice quedan en codigo/admin/respaldos/ para volver atras.

    Devuelve (ok, pasos), con pasos = [(nombre, ok, detalle)].
    """
    import configuracion

    nombres = nombres or {}
    pasos = []

    def paso(nombre, ok, detalle):
        pasos.append((nombre, ok, detalle))
        if avance:
            avance(nombre, ok, detalle)
        return ok

    if modo not in MODOS:
        raise ErrorOperacion("Modo no valido: %s. Opciones: %s" % (modo, ", ".join(MODOS)))
    v = _valores()

    # --- comprobaciones previas: nada se toca si falta algo ---------------
    problemas = []
    hay_docker, detalle = contexto.docker_disponible()
    if not hay_docker:
        problemas.append("Docker no responde: %s" % detalle)
    if modo == "local":
        instalados, _, error = modelos_ollama()
        if error:
            problemas.append("Ollama no responde: %s" % error)
        elif not modelo_local:
            problemas.append("Falta elegir el modelo local")
        elif _normaliza_modelo(modelo_local) not in {_normaliza_modelo(m) for m in instalados}:
            problemas.append("El modelo %s no esta instalado en Ollama. Instalados: %s"
                             % (modelo_local, ", ".join(instalados) or "ninguno"))
    else:
        for clave in ("ANTHROPIC_API_KEY", "COHERE_API_KEY"):
            if not v.get(clave):
                problemas.append("Falta %s, y el modo nube la necesita" % clave)
    if not entornos_ids:
        problemas.append("Hay que elegir al menos un entorno que reindexar")
    if _uvicorn_del_sistema() is None:
        problemas.append("No se encuentra el uvicorn del sistema para el servidor de embeddings")
    try:
        _token(correo, password)
    except Exception as exc:
        problemas.append(_primera(exc))

    if problemas:
        for p in problemas:
            paso("Comprobacion previa", False, p)
        registro.anota("cambiar_modo", {"modo": modo, "abortado": "comprobaciones previas",
                                        "problemas": problemas}, "error")
        return False, pasos
    paso("Comprobaciones previas", True,
         "Docker, %s, credenciales y %d entorno(s) en orden"
         % ("Ollama con %s" % modelo_local if modo == "local" else "claves de los servicios externos",
            len(entornos_ids)))

    # --- copias antes de tocar ----------------------------------------------
    try:
        copia_bd = copia_seguridad(etiqueta="antes_modo_%s" % modo)
        paso("Copia de la base", True, copia_bd.name)
        copia_idx = copia_indice(etiqueta="antes_modo_%s" % modo)
        paso("Copia del indice", True, "%s, %d bytes" % (copia_idx.name, copia_idx.stat().st_size))
    except Exception as exc:
        paso("Copias de seguridad", False, _primera(exc))
        registro.anota("cambiar_modo", {"modo": modo, "abortado": "copias"}, "error")
        return False, pasos

    # --- claves -------------------------------------------------------------
    claves = dict(MODOS[modo])
    if modo == "local":
        claves["OLLAMA_MODEL"] = modelo_local
    cambiadas = []
    for clave, valor in claves.items():
        if v.get(clave) != valor:
            configuracion.cambia_valor(clave, valor)
            cambiadas.append("%s=%s" % (clave, valor))
    paso("Configuracion", True, ", ".join(cambiadas) if cambiadas else "ya estaba escrita en modo %s" % modo)

    # --- aplicar ------------------------------------------------------------
    ok, _ = aplica_configuracion(avance=lambda n, o, d: paso(n, o, d))
    if not ok:
        registro.anota("cambiar_modo", {"modo": modo, "abortado": "aplicar"}, "error")
        return False, pasos

    # --- reindexar y verificar ------------------------------------------------
    dimension = estado_embeddings(dimension=True).get("dimension")
    if not paso("Dimension de los vectores nuevos", bool(dimension),
                "%s dimensiones" % dimension if dimension else "no se pudo medir"):
        return False, pasos

    for eid in entornos_ids:
        etiqueta = nombres.get(eid, eid[:8])
        try:
            subidos, fallidos = reindexa_corpus(eid, correo, password)
        except Exception as exc:
            paso("Reindexar %s" % etiqueta, False, _primera(exc))
            return False, pasos
        if not paso("Reindexar %s" % etiqueta, bool(subidos) and not fallidos,
                    "%d documentos cargados, %d con problema" % (len(subidos), len(fallidos))):
            return False, pasos

    todo_bien = True
    indice = {c["entorno"]: c for c in estado_indice()}
    for eid in entornos_ids:
        c = indice.get(eid)
        ok = bool(c) and c["dimension"] == dimension and c["fragmentos"] > 0
        todo_bien &= ok
        paso("Indice de %s" % nombres.get(eid, eid[:8]), ok,
             "%s dimensiones, %s fragmentos" % (c["dimension"], c["fragmentos"]) if c else "no aparece")

    registro.anota("cambiar_modo", {"modo": modo, "modelo_local": modelo_local,
                                    "entornos": list(entornos_ids), "claves": cambiadas,
                                    "dimension": dimension},
                   "ok" if todo_bien else "error")
    return todo_bien, pasos
