import logging
import re

from app.models.artifact import ArtifactFormat, ArtifactType
from app.services.llm.base import LLMClient
from app.services.reranking.reranker_client import RerankerClientError, RerankerServiceClient
from pipeline.semantic_retriever import SemanticRetriever, SemanticRetrieverError
from pipeline.semantic_validator import SemanticValidator

logger = logging.getLogger(__name__)

# El chat recupera 5 chunks para responder una pregunta puntual. Un artefacto
# sintetiza un tema completo, asi que parte de una base mas amplia.
ARTIFACT_TOP_K = 8

# El cliente de Claude usa 1024 tokens por defecto, calibrado para respuestas de
# chat. Un artefacto es un documento entero y lo desborda: se cortaria a media
# frase y perderia el bloque de continuacion, que va al final y es lo primero
# que se pierde al truncar. El tope
# del chat NO se toca: este viaja como argumento solo en las llamadas del motor.
ARTIFACT_MAX_TOKENS = 4000

# Cuando el artefacto nace de una propuesta, se recupera este multiplo de top_k
# para poder quedarse con los fragmentos del documento que motivo la propuesta.
# Sin este margen, anclar seria filtrar sobre una muestra ya recortada y el
# artefacto acabaria con menos material del que le corresponde.
ANCHOR_TOP_K_MULTIPLIER = 3

NO_MATERIAL_MESSAGE = (
    "No encontré material suficiente en el corpus de este entorno para generar el artefacto "
    "sobre ese tema."
)

# El artefacto NO tiene umbral propio por score. Las peticiones cortas y
# genericas viven en el suelo de ruido del cross-encoder, donde una pregunta
# legitima puede puntuar por debajo de una ajena al corpus: ningun umbral
# admite la una y rechaza la otra.
#
# El filtro es semantico y lo hace el propio modelo: se le pide que declare
# SIN_MATERIAL cuando el contexto recuperado no trate del tema pedido (ver
# BASE_INSTRUCTION y _clean). Lo que se evita no es generar con material escaso
# sino guardar un artefacto cuyo contenido no corresponde a su titulo.
ARTIFACT_MIN_TOP_SCORES: dict[str, float] = {}

# El modelo responde exactamente esto cuando el contexto no trata del tema pedido.
NO_MATERIAL_MARKER = "SIN_MATERIAL"

# Bloque delimitado con los temas de continuacion, mismo mecanismo que usa el chat
# para sus tres preguntas de seguimiento (ver PromptBuilder). Se separa del
# contenido: el artefacto que se guarda y se descarga no los lleva dentro.
CONTINUATION_BLOCK_START = "[[CONTINUACION]]"
CONTINUATION_BLOCK_END = "[[/CONTINUACION]]"
MAX_CONTINUATIONS = 3

# Tarjetas por juego. Diez caben en una pagina impresa, que es como se usan.
MAX_FLASH_CARDS = 10

# Preguntas por cuestionario. De seis a ocho, con sus justificaciones, caben en
# un par de paginas impresas.
MIN_QUIZ_QUESTIONS = 6
MAX_QUIZ_QUESTIONS = 8

_CONTINUATION_PATTERN = re.compile(
    re.escape(CONTINUATION_BLOCK_START) + r"(.*?)" + re.escape(CONTINUATION_BLOCK_END),
    re.DOTALL,
)
_LEADING_MARKER_PATTERN = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")

# Citas que el modelo escribe en el texto: "Presentacion Sesion 21.pdf, paginas 7 y 33",
# "(Sesion 7.pdf, p. 24)". Se capturan el archivo y la lista de paginas.
_CITATION_PATTERN = re.compile(
    r"([^\s(,;]+(?:[ \t][^\s(,;]+){0,6}\.pdf)\s*,?\s*(?:p[aá]gs?\.?|p[aá]ginas?|p\.)\s*([\d]+(?:\s*(?:,|y|-)\s*\d+)*)",
    re.IGNORECASE,
)


def _normalize_filename(name: str) -> str:
    # El nombre viene del texto del artefacto, asi que arrastra lo que lo precede
    # en la linea: guiones de lista, parentesis, comillas. Sin limpiarlos, el mismo
    # archivo se compara como dos distintos y toda cita en lista parece inventada.
    limpio = re.sub(r"^[^0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+", "", (name or "").strip())
    return _strip_accents(limpio.lower())


def extract_citations(text: str) -> set[tuple[str, int]]:
    """Pares (archivo normalizado, pagina) que el texto del artefacto afirma citar."""
    citas: set[tuple[str, int]] = set()
    for match in _CITATION_PATTERN.finditer(text or ""):
        archivo = _normalize_filename(match.group(1))
        for pagina in re.findall(r"\d+", match.group(2)):
            citas.add((archivo, int(pagina)))
    return citas


def invalid_citations(text: str, chunks: list[dict]) -> set[tuple[str, int]]:
    """Citas del texto que NO corresponden a ningun fragmento entregado al modelo.

    Es la comprobacion que de verdad cierra el problema: la instruccion pide no
    inventar citas, pero pedirlo no es garantizarlo.
    """
    permitidas = {
        (_normalize_filename(c.get("filename")), c.get("page_number"))
        for c in chunks
        if c.get("filename") and c.get("page_number") is not None
    }
    return {cita for cita in extract_citations(text) if cita not in permitidas}

# Preambulo comun a todos los tipos. Deliberadamente NO incluye el bloque de
# sugerencias que PromptBuilder le pide al chat: un artefacto es un documento
# cerrado, no un turno de conversacion.
BASE_INSTRUCTION = (
    "Eres un asistente educativo que produce material academico para un estudiante. "
    "Construyes el artefacto solicitado usando UNICAMENTE el contexto del corpus que se "
    "te proporciona: no agregues informacion, ejemplos ni datos que no esten en el. "
    "Si el contexto no alcanza para alguna parte del artefacto, dilo explicitamente en "
    "esa parte en vez de completarla con conocimiento externo. "
    "Cita las fuentes (nombre de archivo y numero de pagina) donde el tipo de artefacto "
    "lo permita. Mantienes un tono academico y profesional: no uses emojis ni caracteres "
    "decorativos. Responde solo con el artefacto, sin preambulos del tipo 'aqui tienes' "
    "ni comentarios finales sobre lo que hiciste.\n\n"
    # Sin esto el modelo hace lo peor posible: como se le pide usar solo el contexto,
    # cuando el contexto no trata del tema pedido construye un artefacto correcto
    # sobre lo que SI trae el contexto, y queda guardado con un titulo que no le
    # corresponde. Comprobado: un artefacto titulado "recetas de cocina italiana"
    # con contenido sobre pandas.
    "ANTES DE EMPEZAR, comprueba una cosa: si el contexto del corpus que se te "
    f"proporciona no trata sobre el tema solicitado, responde UNICAMENTE con la palabra "
    f"{NO_MATERIAL_MARKER}, sin ninguna otra cosa, sin explicaciones y sin construir el "
    "artefacto. No construyas nunca el artefacto sobre un tema distinto del que se pide, "
    "aunque el contexto de para hacerlo. Que el contexto sea escaso no es motivo para "
    f"responder {NO_MATERIAL_MARKER}: si trata del tema pedido, construye el artefacto "
    "con lo que haya y di explicitamente en el que el material disponible es limitado.\n\n"
    # Cuanto MENOS material recibe el modelo, mas tiende a rellenar la lista de
    # fuentes con referencias verosimiles, imitando el patron de nombres que ve en
    # el contexto.
    "SOBRE LAS CITAS, y esto es inviolable: las unicas fuentes que puedes citar son "
    "las que aparecen en el contexto rotuladas como [Fuente N: archivo, pagina N]. "
    "No cites ningun otro documento ni ninguna otra pagina, ni siquiera si te parece "
    "probable que exista en el corpus. Si solo recibes dos o tres fragmentos, cita dos o "
    "tres: una lista de fuentes corta es correcta, y una inventada invalida el artefacto "
    "entero. El apartado de fuentes debe listar exactamente los archivos y paginas del "
    "contexto que hayas usado, ni uno mas."
)


# Esta instruccion NO va en el mensaje de sistema sino al final del mensaje de
# usuario, que es lo ultimo que el modelo lee. Puesta en el sistema, el modelo
# tiende a emitir los tres temas SIN los delimitadores, y quedan pegados al final
# del documento como si fueran parte de el.
CONTINUATION_INSTRUCTION = (
    f"Para terminar, despues del artefacto, escribe un bloque delimitado exactamente por "
    f"{CONTINUATION_BLOCK_START} y {CONTINUATION_BLOCK_END}, cada etiqueta sola en su linea. "
    f"Las dos etiquetas son obligatorias y deben aparecer tal cual, con los corchetes dobles. "
    f"Dentro, exactamente {MAX_CONTINUATIONS} temas de continuacion, uno por linea, sin numerar "
    "ni poner guiones: temas concretos que el estudiante podria trabajar despues de este y que el "
    "corpus del entorno pueda sustentar. Son temas para pedir otro artefacto, no preguntas: "
    "escribelos como sintagma nominal ('la normalizacion de variables numericas'), no como "
    f"interrogacion. Si respondes {NO_MATERIAL_MARKER}, no escribas este bloque."
)


class ArtifactSpec:
    """Estructura y formato esperados de un tipo de artefacto.

    La instruccion es lo que hace que el artefacto sea pedagogicamente util y no
    solo texto bien formateado: un resumen pide sintesis, un mapa conceptual pide
    extraccion de relaciones, un ejercicio pide construir una situacion problema
    con su respuesta esperada.
    """

    def __init__(self, label: str, artifact_format: ArtifactFormat, instruction: str):
        self.label = label
        self.format = artifact_format
        self.instruction = instruction


ARTIFACT_SPECS: dict[ArtifactType, ArtifactSpec] = {
    ArtifactType.resumen: ArtifactSpec(
        "Resumen estructurado",
        ArtifactFormat.markdown,
        "Produce un RESUMEN ESTRUCTURADO del tema. Sintetiza: no copies parrafos del "
        "contexto ni lo parafrasees frase por frase. Organizalo con un titulo de nivel 2, "
        "entre tres y seis apartados con encabezado de nivel 3, y dentro de cada uno un "
        "parrafo breve o una lista de puntos. Cierra con un apartado 'Fuentes' que liste "
        "los documentos y paginas utilizados.",
    ),
    ArtifactType.mapa_conceptual: ArtifactSpec(
        "Mapa conceptual",
        ArtifactFormat.structured,
        "Produce un MAPA CONCEPTUAL en texto jerarquico. Extrae los conceptos del contexto "
        "y, sobre todo, las RELACIONES entre ellos: cada linea hija debe explicitar con que "
        "relacion se conecta a su padre, con la forma 'concepto -- relacion --> concepto'. "
        "Usa indentacion de dos espacios por nivel y un maximo de tres niveles. "
        # El modelo abria unas veces con el concepto raiz y otras con una proposicion
        # completa, y entonces la raiz del mapa era el origen de esa primera linea.
        "La PRIMERA LINEA debe ser unicamente el concepto raiz del tema, sin sangria, "
        "sin relacion y sin flecha: solo el nombre del concepto. Las relaciones empiezan "
        "en la segunda linea. No uses tablas ni parrafos de prosa. "
        "Limita el mapa a un maximo de veinte conceptos: es preferible un mapa corto y "
        "articulado que uno exhaustivo. "
        # La jerarquia sola solo puede expresar un arbol: cada concepto cuelga de un unico
        # padre. Los enlaces cruzados entre ramas distintas son lo que distingue un mapa
        # conceptual de un simple esquema, y necesitan su propia seccion para existir.
        "Al final, deja una linea en blanco y escribe una seccion que empiece exactamente "
        "con 'Enlaces cruzados:'. Debajo, una por linea y sin indentacion, las relaciones "
        "que conecten conceptos de RAMAS DISTINTAS del mapa, con la misma forma "
        "'concepto -- relacion --> concepto'. "
        # Sin este enfasis, el modelo tiende a usar los enlaces cruzados para anadir
        # nodos nuevos, no para cruzar ramas. De ahi que ambos extremos deban existir.
        "AMBOS extremos deben ser conceptos que YA APARECEN en la jerarquia de arriba, "
        "copiados con exactamente las mismas palabras. Esta seccion no sirve para "
        "introducir conceptos nuevos: si el concepto no esta arriba, no puede aparecer "
        "aqui. Su unico proposito es conectar dos ramas distintas del mapa que ya "
        "existen. Incluye solo relaciones que se desprendan del contexto, nunca "
        "inventadas para rellenar; si no hay ninguna, escribe 'ninguno' en esa seccion.",
    ),
    ArtifactType.ejercicio_aplicacion: ArtifactSpec(
        "Ejercicio de aplicacion",
        # Markdown, no structured: sus bloques son titulos y negritas, no sangria
        # significativa. Marcarlo structured lo mandaba al visor monoespaciado y
        # el estudiante veia los asteriscos y las almohadillas en crudo.
        ArtifactFormat.markdown,
        "Produce un EJERCICIO DE APLICACION. Plantea entre tres y cinco items que exijan "
        "aplicar lo del contexto a una situacion, no recordarlo. Cada item lleva tres "
        "bloques separados y rotulados: 'Enunciado', 'Espacio de respuesta' (dejalo en "
        "blanco, marcado con una linea de guiones bajos) y 'Respuesta esperada', que indique "
        "que deberia contener una buena respuesta y en que fuente y pagina se sustenta.",
    ),
    ArtifactType.caso_practico: ArtifactSpec(
        "Caso practico",
        ArtifactFormat.markdown,
        "Produce un CASO PRACTICO construido a partir del contexto. Estructura: 'Situacion' "
        "(un escenario concreto y verosimil del dominio del corpus), 'Datos disponibles' "
        "(solo los que se desprendan del contexto), 'Preguntas de analisis' (entre tres y "
        "cinco) y 'Claves de resolucion' (que conceptos del corpus resuelven cada pregunta, "
        "con su fuente y pagina). El escenario puede ser inventado; los conceptos que lo "
        "resuelven, no.",
    ),
    ArtifactType.autovaloracion: ArtifactSpec(
        "Instrumento de autovaloracion",
        ArtifactFormat.table,
        "Produce un INSTRUMENTO DE AUTOVALORACION para que el estudiante juzgue su propio "
        "dominio del tema, como tabla de Markdown con cuatro columnas: 'Puedo...', "
        "'No lo he trabajado', 'Lo reconozco', 'Lo explico'. Entre seis y diez filas, cada "
        "una con un enunciado en primera persona ('Puedo explicar ...', 'Distingo entre ...') "
        "y las tres columnas de escala vacias, para que el estudiante las marque. Debajo de "
        "la tabla, un apartado 'Donde repasar' que enlace cada enunciado con su fuente y "
        "pagina, y una instruccion breve de como interpretar el resultado. No es una "
        "calificacion.",
    ),
    ArtifactType.glosario: ArtifactSpec(
        "Glosario tematico",
        ArtifactFormat.table,
        "Produce un GLOSARIO TEMATICO como tabla de Markdown con exactamente tres columnas: "
        "'Termino', 'Definicion segun el corpus' y 'Fuente'. Entre ocho y quince terminos, "
        "ordenados alfabeticamente. La definicion debe ser una sola frase y provenir del "
        "contexto, no de conocimiento general. En 'Fuente' va el archivo y la pagina.",
    ),
    ArtifactType.flash_cards: ArtifactSpec(
        "Flash cards",
        # Tabla de dos columnas: cabe en una pagina impresa y permite tapar la
        # columna de la derecha con la mano, que es como se usa una hoja de
        # tarjetas en papel. El PDF sale de la hoja de estilo de impresion.
        ArtifactFormat.table,
        "Produce un JUEGO DE FLASH CARDS como tabla de Markdown con exactamente dos "
        f"columnas, 'Pregunta' y 'Respuesta', y exactamente {MAX_FLASH_CARDS} filas. "
        "Cada fila es una tarjeta. La pregunta va sola y completa, entendible sin leer "
        "el resto de la tabla. La respuesta ocupa de una a tres frases y termina con su "
        "fuente entre parentesis (archivo y pagina). "
        # Un corpus de diapositivas invita a preguntar solo definiciones, que es el
        # nivel mas bajo. La mezcla es lo que hace util el juego.
        "Reparte las tarjetas en tres clases: unas de definicion ('que es X'), otras de "
        "aplicacion ('en que situacion usarias X') y otras de discriminacion entre "
        "conceptos que el contexto trate juntos ('que diferencia a X de Y'). No hagas "
        "ninguna pregunta de si o no, ni de respuesta de una sola palabra, ni preguntas "
        "cuya respuesta sea otra pregunta. Cada tarjeta debe poder responderse "
        "exclusivamente con el contexto proporcionado: si el material no da para "
        f"{MAX_FLASH_CARDS} tarjetas de calidad, escribe menos filas antes que rellenar "
        "con preguntas triviales.",
    ),
    ArtifactType.cuestionario: ArtifactSpec(
        "Cuestionario de opción múltiple",
        ArtifactFormat.markdown,
        f"Produce un CUESTIONARIO DE OPCION MULTIPLE de {MIN_QUIZ_QUESTIONS} a "
        f"{MAX_QUIZ_QUESTIONS} preguntas, cada una con cuatro opciones rotuladas a), b), "
        "c) y d), y una sola correcta. Numera las preguntas en negrita. "
        # En Markdown un salto de linea simple NO crea linea nueva: las lineas
        # consecutivas se unen en un parrafo, y en el PDF impreso las cuatro opciones
        # saldrian corridas y no se podrian marcar. Como lista,
        # cada opcion cae en su renglon.
        "Escribe las cuatro opciones como una LISTA de Markdown, cada una en su propia "
        "linea empezando por un guion y un espacio: '- a) texto de la opcion'. Nunca "
        "las pongas seguidas en un mismo parrafo. "
        # Un distractor inventado es ruido; un distractor construido con un concepto
        # vecino del propio corpus obliga a discriminar, que es lo que este tipo de
        # artefacto aporta y ningun otro da.
        "Los distractores son la parte importante: construyelos con conceptos que SI "
        "aparecen en el contexto pero aplicados en el lugar equivocado -- confundir una "
        "etapa con otra, un metodo con su alternativa, una definicion con la del concepto "
        "vecino. No inventes hechos ni datos para rellenar opciones, y no uses 'todas las "
        "anteriores', 'ninguna de las anteriores' ni opciones absurdas de descarte "
        "inmediato: las cuatro deben resultar creibles para quien no domina el tema. "
        # Sin esto el cuestionario solo sirve a quien lo responde. Con esto, leerlo ya
        # es un texto de discriminacion conceptual.
        "Despues de las preguntas, y separado por una linea horizontal, escribe un "
        "apartado 'Respuestas justificadas'. Para CADA pregunta indica cual es la correcta "
        "y explica, opcion por opcion, por que la correcta lo es y por que cada una de las "
        "otras tres no lo es. La justificacion de la opcion correcta termina con su fuente "
        "(archivo y pagina). Ese apartado es obligatorio: sin el, el cuestionario solo "
        "sirve a quien lo responde, y debe servir tambien a quien solo lo lee.",
    ),
    ArtifactType.otro: ArtifactSpec(
        "Artefacto",
        ArtifactFormat.markdown,
        "Produce el material que el estudiante pide, organizado con encabezados y listas, "
        "y cierra con las fuentes utilizadas.",
    ),
}

# Deteccion por palabras clave (paso 2 del ciclo). Deliberadamente deterministica:
# identificar el tipo no justifica una llamada extra al LLM, y una regla legible
# se corrige mirandola. El orden importa -- se evalua de mas especifico a menos.
_TYPE_KEYWORDS: list[tuple[ArtifactType, tuple[str, ...]]] = [
    (ArtifactType.cuestionario, ("cuestionario", "opcion multiple", "opciones multiples",
                                "seleccion multiple", "quiz", "test de", "examen tipo")),
    (ArtifactType.flash_cards, ("flash card", "flashcard", "flash-card", "tarjetas de estudio",
                                "tarjetas de repaso", "tarjetas", "fichas de estudio")),
    (ArtifactType.mapa_conceptual, ("mapa conceptual", "mapa de conceptos", "esquema conceptual",
                                    "mapa de relaciones", "esquema")),
    (ArtifactType.ejercicio_aplicacion, ("ejercicio", "ejercicios", "practica", "problema",
                                         "problemas", "taller")),
    (ArtifactType.caso_practico, ("caso practico", "caso de estudio", "caso")),
    (ArtifactType.autovaloracion, ("autovaloracion", "autoevaluacion", "autoevaluarme",
                                   "evaluar mi", "instrumento de valoracion")),
    (ArtifactType.glosario, ("glosario", "terminos", "definiciones", "vocabulario")),
    (ArtifactType.resumen, ("resumen", "resume", "sintesis", "sintetiza")),
]


def infer_artifact_type(text: str) -> ArtifactType:
    """Deduce el tipo pedido a partir del texto del estudiante.

    Cae en `resumen` cuando no reconoce ninguna palabra clave: es el artefacto
    mas neutro y el que menos sorprende a quien pidio algo en terminos vagos.
    """
    if not text:
        return ArtifactType.resumen
    normalized = _strip_accents(text.lower())
    for artifact_type, keywords in _TYPE_KEYWORDS:
        if any(keyword in normalized for keyword in keywords):
            return artifact_type
    return ArtifactType.resumen


def _strip_accents(text: str) -> str:
    for accented, plain in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ñ", "n")):
        text = text.replace(accented, plain)
    return text


# "hazme un resumen de X" recupera peor que "X": la parte de la peticion no
# describe el tema y diluye la consulta: sin el preambulo, el mismo tema puntua
# muy por encima.
_REQUEST_PREAMBLE_PATTERN = re.compile(
    r"^\s*(?:me\s+)?(?:puedes\s+|podrias\s+|quiero\s+|necesito\s+|dame\s+|hazme\s+|haz\s+|"
    r"genera\s+|generame\s+|prepara\s+|plantea\s+|arma\s+|elabora\s+|crea\s+)*"
    r"(?:un|una|el|la|los|las)?\s*"
    r"(?:resumen|sintesis|mapa\s+conceptual|mapa\s+de\s+conceptos|esquema\s+conceptual|"
    r"esquema|mapa\s+de\s+relaciones|ejercicios?|practica|taller|caso\s+practico|"
    r"caso\s+de\s+estudio|glosario|vocabulario|definiciones|autovaloracion|autoevaluacion|"
    r"instrumento\s+de\s+valoracion)\s*"
    r"(?:de|del|de\s+la|sobre|acerca\s+de|para)?\s+",
    re.IGNORECASE,
)

# Por debajo de esto lo que queda no es un tema, es un resto: se usa el texto original.
_MIN_TOPIC_LENGTH = 4


def build_retrieval_query(topic: str) -> str:
    """Quita de la consulta la parte que es peticion y no tema.

    El texto original se conserva como `topic` del artefacto -- es lo que el
    estudiante pidio y lo que vera en su portafolio. Lo que se recorta aqui es
    solo lo que se manda al recuperador.
    """
    if not topic:
        return topic
    cleaned = _REQUEST_PREAMBLE_PATTERN.sub("", topic, count=1).strip()
    if len(cleaned) < _MIN_TOPIC_LENGTH:
        return topic.strip()
    return cleaned


class ArtifactGenerationEngineError(Exception):
    pass


class ArtifactGenerationEngine:
    """Genera un artefacto academico sobre un tema, fundado en el corpus del entorno.

    Es un servicio par del ConversationOrchestrator, no una extension suya:
    comparte la cadena RAG (retriever, reranker, validador) pero tiene su propio
    prompt, su propio formato de salida y su propia persistencia. El flujo del
    chat, que es el flujo principal del sistema, no pasa por aqui.
    """

    def __init__(
        self,
        semantic_retriever: SemanticRetriever,
        semantic_validator: SemanticValidator,
        llm_client: LLMClient,
        reranker: RerankerServiceClient,
        fallback_validator: SemanticValidator,
        top_k: int = ARTIFACT_TOP_K,
        min_top_score: float | None = None,
    ):
        self.semantic_retriever = semantic_retriever
        self.semantic_validator = semantic_validator
        self.llm_client = llm_client
        self.reranker = reranker
        self.fallback_validator = fallback_validator
        self.top_k = top_k
        # None = sin barrera adicional (proveedor de reranking sin calibrar).
        self.min_top_score = min_top_score

    async def generate(
        self,
        environment_id: str,
        artifact_type: ArtifactType,
        topic: str,
        conversation_history: list[dict] | None = None,
        student_profile: dict | None = None,
        focus: list[str] | None = None,
        prefer_filename: str | None = None,
    ) -> dict:
        """Devuelve {content, format, sources, suggestions, below_threshold}.

        `prefer_filename` es el documento que motivo la propuesta. El artefacto se
        ancla a el: se recupera mas material del habitual y se anteponen sus
        fragmentos, de modo que el artefacto se apoye en lo que el estudiante
        trabajo de verdad y no en lo que la busqueda devuelva por su cuenta. Es
        preferencia, no filtro: si ese documento no aporta suficiente, el resto
        del corpus completa.

        `focus` son las preguntas que el estudiante hizo de verdad sobre el tema.
        Cuando el artefacto nace de una propuesta del sistema, el resumen debe
        tratar los puntos que el trabajo, no el tema entero tal como lo cubre el
        corpus. Sin focus, el artefacto cubre el tema completo.

        `student_profile` queda declarado y sin uso a proposito: el perfil vivo
        del estudiante pertenece a la capa de inteligencia evolutiva y todavia no
        existe. Se recibe aqui para llenarlo sin reabrir la firma ni el prompt.
        """
        if not topic or not topic.strip():
            raise ArtifactGenerationEngineError("El tema del artefacto no puede estar vacio")

        spec = ARTIFACT_SPECS.get(artifact_type, ARTIFACT_SPECS[ArtifactType.otro])
        query = build_retrieval_query(topic)

        # Con anclaje se recupera de mas para poder elegir; sin el, lo de siempre.
        recuperar = self.top_k * ANCHOR_TOP_K_MULTIPLIER if prefer_filename else self.top_k

        try:
            chunks = await self.semantic_retriever.retrieve(environment_id, query, top_k=recuperar)
        except SemanticRetrieverError as exc:
            raise ArtifactGenerationEngineError(
                f"Error al recuperar material del corpus: {exc}"
            ) from exc

        reranked = False
        if chunks:
            try:
                chunks = await self.reranker.rerank(query, chunks)
                reranked = True
            except RerankerClientError as exc:
                logger.warning(
                    "ReRanker fallo al generar artefacto, se sigue con el orden del retriever: %s", exc
                )

        # Misma razon que en ConversationOrchestrator: los scores de rerank y los
        # de similitud coseno viven en escalas distintas y cada uno tiene su umbral.
        validator = self.semantic_validator if reranked else self.fallback_validator
        validation = validator.validate(chunks)

        # Barrera propia del artefacto: el mejor chunk debe superar el minimo, no
        # basta con que sobreviva alguno al umbral del chat. Solo se aplica cuando
        # hubo reranking, porque el minimo esta calibrado en esa escala de scores.
        if reranked and self.min_top_score is not None and validation["chunks"]:
            best_score = validation["chunks"][0]["score"]
            if best_score < self.min_top_score:
                logger.info(
                    "Material insuficiente para un artefacto: mejor score %.4f < %.4f",
                    best_score,
                    self.min_top_score,
                )
                validation = {"chunks": [], "below_threshold": True}

        if validation["below_threshold"]:
            logger.info(
                "Sin material suficiente para generar '%s' sobre '%s' en el entorno '%s'",
                artifact_type.value,
                topic,
                environment_id,
            )
            return {
                "content": NO_MATERIAL_MESSAGE,
                "format": spec.format,
                "sources": [],
                "suggestions": [],
                "below_threshold": True,
            }

        validated_chunks = self._anchor(validation["chunks"], prefer_filename)
        prompt_messages = self._build_prompt(
            spec, topic, validated_chunks, conversation_history, student_profile, focus
        )

        try:
            raw = await self.llm_client.chat(prompt_messages, max_tokens=ARTIFACT_MAX_TOKENS)
        except Exception as exc:
            raise ArtifactGenerationEngineError(f"Error al generar el artefacto: {exc}") from exc

        raw = await self._retry_if_invented_citations(raw, prompt_messages, validated_chunks)

        # El modelo declaro que el contexto no trata del tema pedido: no hay
        # artefacto que guardar. Se compara sobre las primeras palabras porque el
        # marcador puede venir con puntuacion o formato alrededor.
        if NO_MATERIAL_MARKER in self._clean(raw)[:60].upper():
            logger.info(
                "El modelo declaro %s para '%s' sobre '%s' en el entorno '%s'",
                NO_MATERIAL_MARKER,
                artifact_type.value,
                topic,
                environment_id,
            )
            return {
                "content": NO_MATERIAL_MESSAGE,
                "format": spec.format,
                "sources": [],
                "suggestions": [],
                "below_threshold": True,
            }

        content, suggestions = self._split_continuations(self._clean(raw))
        return {
            "content": content,
            "format": spec.format,
            "sources": self._build_sources(validated_chunks),
            "suggestions": suggestions,
            "below_threshold": False,
        }

    def _build_prompt(
        self,
        spec: ArtifactSpec,
        topic: str,
        chunks: list[dict],
        conversation_history: list[dict] | None,
        student_profile: dict | None,
        focus: list[str] | None = None,
    ) -> list[dict[str, str]]:
        system_content = f"{BASE_INSTRUCTION}\n\nTipo de artefacto solicitado: {spec.label}.\n{spec.instruction}"

        user_content = ""
        if conversation_history:
            history_block = "\n".join(
                f"{'Estudiante' if turn['speaker'] == 'student' else 'Sistema'}: {turn['text']}"
                for turn in conversation_history
            )
            user_content += (
                "Historial reciente de la conversacion, para saber que se trabajo y con que "
                f"enfoque (no es fuente de contenido):\n{history_block}\n\n"
            )
        if focus:
            puntos = "\n".join(f"- {punto}" for punto in focus)
            user_content += (
                "Lo que el estudiante pregunto de verdad sobre este tema, y que el artefacto "
                "debe cubrir con prioridad (si el contexto da para mas, incluyelo despues, "
                f"pero estos puntos primero):\n{puntos}\n\n"
            )
        if student_profile:
            user_content += f"Perfil del estudiante:\n{student_profile}\n\n"
        user_content += f"Contexto del corpus:\n{self._build_context_block(chunks)}\n\n"
        user_content += f"Tema del artefacto:\n{topic}\n\n{CONTINUATION_INSTRUCTION}"

        return [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]

    @staticmethod
    def _build_context_block(chunks: list[dict]) -> str:
        blocks = []
        for index, chunk in enumerate(chunks, start=1):
            filename = chunk.get("filename", "desconocido")
            page_number = chunk.get("page_number", "?")
            blocks.append(f"[Fuente {index}: {filename}, pagina {page_number}]\n{chunk.get('text', '')}")
        return "\n\n".join(blocks)

    @staticmethod
    def _clean(raw: str) -> str:
        # El artefacto se guarda y se descarga tal cual: se le quitan las vallas de
        # codigo con que algunos modelos envuelven la respuesta completa, que en un
        # .md descargado se verian como un bloque de codigo en vez de como documento.
        if not raw:
            return ""
        text = raw.strip()
        fenced = re.match(r"^```[a-zA-Z]*\n(.*)\n```$", text, re.DOTALL)
        if fenced:
            text = fenced.group(1).strip()
        return text

    async def _retry_if_invented_citations(
        self, raw: str, prompt_messages: list[dict[str, str]], chunks: list[dict]
    ) -> str:
        """Regenera UNA vez si el artefacto cita fuentes que no se le entregaron.

        Regenerar no devuelve el mismo documento con las citas arregladas: dos
        generaciones del mismo tema comparten una parte menor de sus palabras.
        Devuelve un documento distinto y
        coherente, que es preferible a podar las citas falsas -- estas no viven
        solo en la lista final, tambien entre parentesis dentro del texto, y
        recortarlas deja afirmaciones atribuidas a una fuente que ya no figura.

        Si el segundo intento tambien inventa, se queda el que menos invente y se
        deja constancia en el log: negarle el artefacto al estudiante seria peor.
        """
        if NO_MATERIAL_MARKER in self._clean(raw)[:60].upper():
            return raw

        inventadas = invalid_citations(raw, chunks)
        if not inventadas:
            return raw

        permitidas = "\n".join(
            f"- {c.get('filename')}, pagina {c.get('page_number')}" for c in chunks
        )
        falsas = "\n".join(f"- {archivo}, pagina {pagina}" for archivo, pagina in sorted(inventadas))
        logger.warning(
            "Artefacto con %d cita(s) inventada(s), se regenera una vez: %s",
            len(inventadas),
            sorted(inventadas),
        )

        correccion = list(prompt_messages) + [
            {"role": "assistant", "content": raw},
            {
                "role": "user",
                "content": (
                    "El artefacto que acabas de escribir cita fuentes que NO estaban en el "
                    f"contexto que se te dio:\n{falsas}\n\n"
                    f"Las unicas fuentes validas eran estas:\n{permitidas}\n\n"
                    "Reescribe el artefacto entero citando exclusivamente esas fuentes. Si son "
                    "pocas, cita pocas: es correcto. No añadas ninguna otra referencia."
                ),
            },
        ]
        try:
            segundo = await self.llm_client.chat(correccion, max_tokens=ARTIFACT_MAX_TOKENS)
        except Exception as exc:
            logger.warning("Fallo la regeneracion por citas inventadas, se conserva la primera: %s", exc)
            return raw

        siguen = invalid_citations(segundo, chunks)
        if siguen:
            logger.warning(
                "La regeneracion tambien invento %d cita(s); se conserva la version con menos",
                len(siguen),
            )
            return segundo if len(siguen) < len(inventadas) else raw

        logger.info("Regeneracion limpia: las citas del artefacto corresponden al material entregado")
        return segundo

    def _anchor(self, chunks: list[dict], prefer_filename: str | None) -> list[dict]:
        """Antepone los fragmentos del documento que motivo la propuesta.

        Sin anclaje, la propuesta y la generacion podian apuntar a documentos
        distintos: la propuesta cuenta citas ya registradas y la generacion vuelve
        a buscar en el corpus, y puede apoyarse en otro documento.

        Es preferencia y no filtro a proposito: si el documento no aporta bastante,
        el resto del corpus completa hasta top_k. Un artefacto pobre pero "fiel"
        seria peor que uno completo.
        """
        if not prefer_filename:
            return chunks[: self.top_k]

        preferidos = [c for c in chunks if c.get("filename") == prefer_filename]
        resto = [c for c in chunks if c.get("filename") != prefer_filename]
        anclados = (preferidos + resto)[: self.top_k]
        logger.info(
            "Anclaje a '%s': %d de %d fragmentos del documento que motivo la propuesta",
            prefer_filename,
            sum(1 for c in anclados if c.get("filename") == prefer_filename),
            len(anclados),
        )
        return anclados

    @staticmethod
    def _split_continuations(text: str) -> tuple[str, list[str]]:
        """Separa el bloque de temas de continuacion del cuerpo del artefacto.

        Nunca rompe el artefacto: si el bloque falta o viene mal formado, se
        devuelve el texto intacto y la lista vacia -- mismo criterio que el
        ResponsePostProcessor del chat con sus sugerencias.
        """
        if not text:
            return text, []
        try:
            match = _CONTINUATION_PATTERN.search(text)
            if not match:
                return text, []
            cuerpo = (text[: match.start()] + text[match.end() :]).strip()
            lineas = [linea.strip() for linea in match.group(1).splitlines()]
            temas = [
                _LEADING_MARKER_PATTERN.sub("", linea).strip() for linea in lineas if linea.strip()
            ]
            return cuerpo, temas[:MAX_CONTINUATIONS]
        except Exception:
            return text, []

    @staticmethod
    def _build_sources(chunks: list[dict]) -> list[dict]:
        return [
            {
                "chunk_id": chunk.get("chunk_id"),
                "filename": chunk.get("filename"),
                "page_number": chunk.get("page_number"),
                "score": chunk.get("score"),
            }
            for chunk in chunks
        ]
