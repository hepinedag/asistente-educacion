# Asistente de Educación

Sistema de aprendizaje asistido sobre un corpus académico curado. El docente carga y
administra el material de su asignatura; el estudiante lo consulta en lenguaje natural y
recibe respuestas fundamentadas **exclusivamente** en ese material, con la cita del
documento y la página que las sustentan. Cuando el corpus no cubre una consulta, el
sistema lo dice en lugar de completar con conocimiento externo.

Este repositorio contiene el código del sistema. Es el código que acompaña a un trabajo
académico y se publica para su consulta y evaluación.

## Cómo funciona

La consulta del estudiante recorre un pipeline de recuperación aumentada:

1. **Indexación** — el documento que carga el docente se fragmenta, se vectoriza y se
   guarda en el almacén vectorial junto a los metadatos de citación (documento, página).
2. **Recuperación** — la consulta se vectoriza y se buscan los fragmentos más próximos.
3. **Reordenamiento** — un *cross-encoder* reordena los candidatos por relevancia real.
4. **Validación semántica** — si el mejor fragmento no supera el umbral, el recorrido se
   corta aquí y el sistema avisa de que el corpus no cubre la consulta. No se invoca al
   modelo generador.
5. **Generación** — si lo supera, el orquestador arma el mensaje —instrucción de sistema,
   fragmentos recuperados e historial reciente de la sesión— y el modelo responde.
6. **Cierre** — la respuesta se procesa, se le adjuntan las fuentes y se persiste.

## Arquitectura

| Capa | Tecnología |
|---|---|
| Frontend | React 18 + Vite + Tailwind CSS + Zustand |
| Backend | Python 3.11 + FastAPI |
| Almacén vectorial | ChromaDB |
| Base de datos | PostgreSQL |
| Generación | Claude (API) · Ollama como alternativa local |
| Vectorización | Cohere · `sentence-transformers` como alternativa local |
| Reordenamiento | *cross-encoder* local (`mmarco-mMiniLMv2-L12-H384-v1`) |
| Autenticación | JWT + control de acceso por rol |
| Despliegue | Docker Compose |

El proveedor de generación, de vectorización y de reordenamiento se elige por
configuración, sin tocar código. El sistema opera en **modo nube** (APIs externas) o en
**modo local** (Ollama y embeddings en la propia máquina).

## Estructura

```
codigo/
  backend/    API FastAPI: rutas, modelo de datos, seguridad y orquestación conversacional
  pipeline/   ingesta, fragmentación, vectorización, recuperación, reordenamiento y validación
  frontend/   SPA React: vistas de estudiante, docente y administración
  admin/      módulo de administración — externo al sistema, no lo modifica
  scripts/    arranque, indexación del corpus y validación
config/
  .env.example      plantilla de configuración con todas las variables requeridas
  docker-compose.yml
```

## Puesta en marcha

Requisitos: Docker y Docker Compose, Python 3.11, Node.js.

```bash
cp config/.env.example config/.env            # y completar las claves
mkdir -p corpus/fuente                        # el compose lo monta; el material no se versiona

docker compose -f config/docker-compose.yml up -d

cd codigo && uvicorn pipeline.embedding_server:app --host 0.0.0.0 --port 8500
cd codigo/frontend && npm install && npm run dev
```

El servidor de embeddings y reordenamiento corre **fuera de Docker** y se lanza desde
`codigo/`, no desde la raíz: el módulo se importa como `pipeline.embedding_server`.

En Windows, `codigo/scripts/iniciar_sistema.bat` levanta el conjunto en orden, respeta las
dependencias entre servicios y dispara la indexación del corpus si encuentra vacío el
índice del entorno.

Con los servicios arriba, `python codigo/scripts/indexar_corpus.py` indexa el material del
entorno.

## Configuración

Toda la configuración vive en variables de entorno, documentadas una a una en
`config/.env.example`: credenciales de las APIs, conexión de los almacenes y elección de
proveedores. **Ningún secreto se versiona:** `config/.env` está excluido del repositorio.

## Nota sobre las credenciales de los scripts de validación

Los scripts de `codigo/scripts/` autentican contra una instancia **local** de desarrollo
con cuentas de prueba (`*@test.com`) y una contraseña fija escrita en el propio script.
Son datos de una instalación de pruebas en `localhost`, no credenciales de ningún entorno
real. Al desplegar el sistema para uso efectivo, las cuentas se crean desde el módulo de
administración y esas constantes dejan de aplicar.

## Alcance de este repositorio

Se publica el código del sistema y la configuración necesaria para reproducir el entorno.
No se incluyen el corpus documental —material de terceros—, los datos de las bases, ni la
documentación del trabajo académico al que acompaña.

## Licencia

Todos los derechos reservados. Ver [LICENSE](LICENSE).
