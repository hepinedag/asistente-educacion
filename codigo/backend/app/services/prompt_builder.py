SUGGESTIONS_BLOCK_START = "[[SUGERENCIAS]]"
SUGGESTIONS_BLOCK_END = "[[/SUGERENCIAS]]"

DEFAULT_SYSTEM_INSTRUCTION = (
    "Eres un asistente educativo. Respondes unicamente con base en el contexto "
    "proporcionado a continuacion, extraido del corpus academico curado del entorno. "
    "Si el contexto no contiene informacion suficiente para responder la pregunta, "
    "dilo explicitamente en vez de inventar o completar con conocimiento externo. "
    "Cita las fuentes (nombre de archivo y numero de pagina) que sustentan tu respuesta. "
    "Si se te proporciona un historial reciente de la conversacion, usalo unicamente "
    "para dar continuidad: si el estudiante hace referencia a algo discutido antes "
    "(por ejemplo 'eso', 'lo anterior', 'el tema de la vez pasada'), respondes "
    "reconociendo ese contexto previo, sin dejar de fundamentar el contenido de tu "
    "respuesta en el contexto del corpus proporcionado. Mantienes un tono academico "
    "y profesional: no uses emojis ni caracteres decorativos en ninguna respuesta. "
    f"Al final de tu respuesta, agrega un bloque nuevo delimitado exactamente por "
    f"{SUGGESTIONS_BLOCK_START} y {SUGGESTIONS_BLOCK_END}, cada etiqueta en su propia "
    "linea, sin texto antes ni despues de ellas dentro del bloque. Dentro del bloque "
    "incluye exactamente 3 preguntas breves de seguimiento conversacional, una por "
    "linea, sin numerarlas ni agregar guiones. Esas preguntas deben ser unicamente "
    "preguntas que el estudiante podria hacer a continuacion sobre el mismo tema, "
    "para seguir conversando: nunca ofrezcas ni prometas generar cuestionarios, "
    "ejercicios, talleres, resumenes ni ningun otro artefacto en esas preguntas."
)


class PromptBuilder:
    def __init__(self, system_instruction: str = DEFAULT_SYSTEM_INSTRUCTION):
        self.system_instruction = system_instruction

    def build(
        self,
        message: str,
        chunks: list[dict],
        conversation_history: list[dict] | None = None,
    ) -> list[dict[str, str]]:
        if not message or not message.strip():
            raise ValueError("El mensaje del estudiante no puede estar vacio")
        if not chunks:
            raise ValueError("PromptBuilder requiere al menos un chunk de contexto valido")

        context_block = self._build_context_block(chunks)
        user_content = ""
        if conversation_history:
            history_block = self._build_history_block(conversation_history)
            user_content += f"Historial reciente de la conversacion:\n{history_block}\n\n"
        user_content += f"Contexto del corpus:\n{context_block}\n\nPregunta del estudiante:\n{message}"

        return [
            {"role": "system", "content": self.system_instruction},
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
    def _build_history_block(conversation_history: list[dict]) -> str:
        return "\n".join(
            f"{'Estudiante' if turn['speaker'] == 'student' else 'Sistema'}: {turn['text']}"
            for turn in conversation_history
        )
