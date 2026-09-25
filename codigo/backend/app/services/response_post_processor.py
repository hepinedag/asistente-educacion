import re

MAX_SUGGESTIONS = 3

# Las etiquetas canonicas las define PromptBuilder ([[SUGERENCIAS]] y
# [[/SUGERENCIAS]]); aqui se reconocen ademas sus variantes mal cerradas, porque
# el modelo pequeno escribe una y otra vez un corchete de mas o de menos: sin
# reconocerlas, "[/SUGERENCIAS]]" llegaria a la pantalla del estudiante y las
# tres preguntas sugeridas se quedarian dentro del texto de la respuesta.
#
# Se exige la palabra en MAYUSCULAS entre corchetes, y esa es la barrera que
# protege el contenido legitimo: `data[['columna']]` de pandas no la lleva, y un
# "[sugerencias]" en minusculas de un texto normal tampoco.
_APERTURA = r"\[{1,2}[ \t]*SUGERENCIAS[ \t]*\]{1,2}"
_CIERRE = r"\[{1,2}[ \t]*/[ \t]*SUGERENCIAS[ \t]*\]{1,2}"

# Bloque delimitado que PromptBuilder le pide al modelo al final de la
# respuesta -- DOTALL porque las preguntas van una por linea dentro del bloque.
_SUGGESTIONS_BLOCK_PATTERN = re.compile(_APERTURA + r"(.*?)" + _CIERRE, re.DOTALL)

# Numeracion o guiones que el LLM pudiera anteponer pese a la instruccion de no hacerlo.
_LEADING_MARKER_PATTERN = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")

# Etiqueta suelta: la de apertura o la de cierre sin su pareja.
_STRAY_TAG_PATTERN = re.compile(r"[ \t]*(?:" + _APERTURA + r"|" + _CIERRE + r")[ \t]*")


def _strip_stray_tags(text: str) -> str:
    """Quita etiquetas del protocolo que hayan quedado sueltas en la respuesta.

    Solo las dos etiquetas literales, y sin tocar nada mas: los dobles corchetes
    de un bloque de codigo (`data[['columna']]`) son contenido legitimo.
    """
    if not text:
        return text
    limpio = _STRAY_TAG_PATTERN.sub("", text)
    # La etiqueta ocupaba su propia linea: al quitarla deja una linea en blanco de
    # mas, y encadenadas dejan varias.
    limpio = re.sub(r"\n{3,}", "\n\n", limpio)
    return limpio.strip()


class ResponsePostProcessor:
    def process(self, raw_answer: str, chunks: list[dict], below_threshold: bool) -> dict:
        answer, suggestions = self._extract_suggestions(raw_answer)
        return {
            "answer": self._normalize(answer),
            "sources": self._build_sources(chunks),
            "below_threshold": below_threshold,
            "suggestions": suggestions,
        }

    @staticmethod
    def _extract_suggestions(raw_answer: str) -> tuple[str, list[str]]:
        # El parseo nunca debe romper el chat -- si algo falla se devuelve
        # la respuesta intacta y suggestions vacio.
        if not raw_answer:
            return raw_answer, []
        try:
            match = _SUGGESTIONS_BLOCK_PATTERN.search(raw_answer)
            if not match:
                # Sin bloque bien formado puede haber etiquetas sueltas, que no
                # deben llegar a la pantalla. No se corta nada por una etiqueta sin pareja:
                # el modelo pequeno las pone al PRINCIPIO de la respuesta, asi que
                # cortar desde ahi borraria el texto entero.
                return _strip_stray_tags(raw_answer), []

            answer_without_block = (raw_answer[: match.start()] + raw_answer[match.end() :]).strip()
            lines = [line.strip() for line in match.group(1).splitlines()]
            questions = [_LEADING_MARKER_PATTERN.sub("", line).strip() for line in lines if line.strip()]

            # Si quitar el bloque no deja respuesta, es que no habia respuesta y el
            # bloque era todo: devolver "" le entregaria al estudiante una burbuja
            # vacia. Se prefiere entregar el contenido sin las
            # etiquetas, aunque venga en forma de preguntas, antes que nada.
            if not answer_without_block:
                return _strip_stray_tags(raw_answer), questions[:MAX_SUGGESTIONS]

            return _strip_stray_tags(answer_without_block), questions[:MAX_SUGGESTIONS]
        except Exception:
            return _strip_stray_tags(raw_answer), []

    @staticmethod
    def _normalize(raw_answer: str) -> str:
        if raw_answer is None:
            return raw_answer
        return raw_answer.strip()

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
