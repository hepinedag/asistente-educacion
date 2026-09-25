# -*- coding: utf-8 -*-
"""Comprobaciones de iniciar_sistema.bat que el lenguaje de un .bat no hace bien.

Dos comprobaciones:

1. Si el servidor de embeddings YA esta abierto. Lanzar otro no podria tomar el
   puerto 8500, y el sistema seguiria con el anterior aunque la configuracion
   pidiera otro modelo.
2. Si la DIMENSION del indice corresponde al modelo de embeddings configurado.
   Contar fragmentos no basta: con el indice en 384 dimensiones (modo local) y la
   configuracion en modo nube (1024), el sistema quedaria sin poder buscar.

Es autonomo a proposito: no importa el modulo de administracion, para que el
arranque del sistema no dependa de un componente externo que puede retirarse.

Uso -lo llama iniciar_sistema.bat, y los codigos de salida son el contrato-:

    python codigo/scripts/comprueba_arranque.py embeddings
        0  ya sirve el modelo configurado: se reutiliza
        1  no responde: hay que lanzarlo (antes se cierran ventanas huerfanas)
        2  servia otro modelo: se cerro, hay que lanzarlo

    python codigo/scripts/comprueba_arranque.py indice <environment_id> <puerto_chroma>
        0  coherente y con fragmentos: no hace falta reindexar
        1  vacio o inexistente: hay que indexar
        2  la dimension no corresponde al modelo configurado: hay que reindexar
        3  no se pudo comprobar: no se toca nada
"""
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx

RAIZ = Path(__file__).resolve().parents[2]
ENV = RAIZ / "config" / ".env"
EMBEDDINGS = "http://127.0.0.1:8500"  # no localhost: en Windows cuesta ~2 s por llamada (ver operacion._en_la_maquina)
PUERTO_EMBEDDINGS = 8500


def lee_env(clave, defecto=""):
    for linea in ENV.read_text(encoding="utf-8").splitlines():
        limpia = linea.strip()
        if limpia and not limpia.startswith("#") and "=" in limpia:
            nombre, _, valor = limpia.partition("=")
            if nombre.strip() == clave:
                return valor.strip()
    return defecto


def constante(archivo, nombre):
    """El servidor de embeddings ignora EMBEDDING_MODEL: el modelo sale de su codigo."""
    texto = (RAIZ / "codigo" / "pipeline" / archivo).read_text(encoding="utf-8")
    m = re.search(r'^%s\s*=\s*"([^"]+)"' % re.escape(nombre), texto, re.M)
    return m.group(1) if m else None


def modelo_esperado():
    if lee_env("EMBEDDING_PROVIDER", "sentence-transformers") == "cohere":
        return constante("cohere_embedding_client.py", "DEFAULT_MODEL_NAME")
    return constante("embedding_service.py", "DEFAULT_MODEL_NAME")


def modelo_servido(timeout=10):
    try:
        datos = httpx.get(EMBEDDINGS + "/health", timeout=timeout).json()
        return datos.get("model") if datos.get("status") == "ok" else None
    except Exception:
        return None


def escucha(puerto):
    """PID que escucha en ese puerto, en IPv4 o IPv6. `netstat -p TCP` solo lista IPv4."""
    r = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=30)
    for linea in r.stdout.splitlines():
        partes = linea.split()
        if (len(partes) >= 5 and partes[0].upper() == "TCP" and partes[1].endswith(":%d" % puerto)
                and partes[3].upper() in ("LISTENING", "ESCUCHANDO")):
            return int(partes[4])
    return None


def ventanas_embeddings():
    filtro = ("Get-CimInstance Win32_Process -Filter \"Name='cmd.exe'\" | "
              "Where-Object { $_.CommandLine -like '*pipeline.embedding_server*' } | "
              "ForEach-Object { $_.ProcessId }")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", filtro],
                       capture_output=True, text=True, timeout=60)
    return [int(x) for x in r.stdout.split() if x.isdigit()]


def cierra(pids):
    for pid in pids:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=30)
    for _ in range(30):
        if escucha(PUERTO_EMBEDDINGS) is None:
            return True
        time.sleep(1)
    return False


def comprueba_embeddings():
    esperado = modelo_esperado()
    actual = modelo_servido()
    if actual and actual == esperado:
        print("      El servidor de embeddings ya estaba abierto y sirve %s: se reutiliza." % actual)
        return 0
    if actual:
        print("      El servidor de embeddings servia %s y la configuracion pide %s: se cierra para relanzarlo."
              % (actual, esperado))
        cierra([p for p in [escucha(PUERTO_EMBEDDINGS)] if p] + ventanas_embeddings())
        return 2
    restos = [p for p in [escucha(PUERTO_EMBEDDINGS)] if p] + ventanas_embeddings()
    if restos:
        print("      Se cierran %d proceso(s) del servidor de embeddings que no respondian." % len(restos))
        cierra(restos)
    return 1


def dimension_del_modelo(espera=90):
    inicio = time.time()
    while time.time() - inicio < espera:
        try:
            r = httpx.post(EMBEDDINGS + "/embed_text", json={"text": "comprobacion de dimension"}, timeout=60)
            return len(r.json()["embedding"])
        except Exception:
            time.sleep(3)
    return None


def comprueba_indice(entorno, puerto):
    base = ("http://localhost:%s/api/v2/tenants/default_tenant/databases/"
            "default_database/collections" % puerto)
    try:
        colecciones = {c["name"]: c for c in httpx.get(base, timeout=15).json()}
        coleccion = colecciones.get("corpus_%s" % entorno)
        if coleccion is None:
            print("      El indice del entorno no existe.")
            return 1
        fragmentos = httpx.get("%s/%s/count" % (base, coleccion["id"]), timeout=15).json()
        if not fragmentos:
            print("      El indice del entorno esta vacio.")
            return 1
    except Exception as exc:
        print("      ADVERTENCIA: no se pudo consultar el indice: %s" % str(exc).splitlines()[0][:160])
        return 3

    dimension_indice = coleccion.get("dimension")
    dimension_modelo = dimension_del_modelo()
    if dimension_modelo is None:
        print("      ADVERTENCIA: el servidor de embeddings no respondio; no se pudo comprobar la dimension.")
        return 3
    if dimension_indice != dimension_modelo:
        print("      El indice tiene %s fragmentos de %s dimensiones, pero el modelo configurado produce %s: "
              "no corresponde al modo." % (fragmentos, dimension_indice, dimension_modelo))
        return 2
    print("      El indice tiene %s fragmentos de %s dimensiones, las del modelo configurado."
          % (fragmentos, dimension_indice))
    return 0


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "embeddings":
        return comprueba_embeddings()
    if len(sys.argv) >= 4 and sys.argv[1] == "indice":
        return comprueba_indice(sys.argv[2], sys.argv[3])
    print(__doc__)
    return 3


if __name__ == "__main__":
    sys.exit(main())
