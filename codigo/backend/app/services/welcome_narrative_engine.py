import logging

from app.services.llm.base import LLMClient

logger = logging.getLogger(__name__)

DEFAULT_MAX_EXCHANGES = 6

NO_HISTORY_MESSAGE = (
    "¡Bienvenido a este entorno académico! Es tu primera conversación aquí — "
    "escribe tu primera pregunta sobre el corpus para comenzar."
)

SYSTEM_INSTRUCTION = (
    "Eres un asistente educativo. Tu unica tarea es generar un mensaje breve de "
    "bienvenida narrativa para un estudiante que retoma este entorno de aprendizaje. "
    "Usa EXCLUSIVAMENTE el historial de conversacion proporcionado a continuacion "
    "-- no inventes temas, nombres ni datos que no aparezcan en el, y no menciones "
    "a otros estudiantes ni a otros entornos academicos. El mensaje debe, en 2 a 4 "
    "frases, en espanol, con un tono cercano: (1) resumir brevemente el ultimo tema "
    "trabajado segun el historial, (2) invitar al estudiante a retomarlo o a "
    "explorar un tema nuevo del corpus. Mantén un tono academico y profesional: "
    "no uses emojis ni caracteres decorativos."
)


class WelcomeNarrativeEngineError(Exception):
    pass


class WelcomeNarrativeEngine:
    def __init__(self, llm_client: LLMClient, max_exchanges: int = DEFAULT_MAX_EXCHANGES):
        self.llm_client = llm_client
        self.max_exchanges = max_exchanges

    async def generate(self, messages: list[dict]) -> dict:
        if not messages:
            return {"message": NO_HISTORY_MESSAGE, "has_history": False}

        recent = messages[-self.max_exchanges :]
        history_block = "\n".join(
            f"{'Estudiante' if m['speaker'] == 'student' else 'Sistema'}: {m['text']}" for m in recent
        )
        prompt_messages = [
            {"role": "system", "content": SYSTEM_INSTRUCTION},
            {"role": "user", "content": f"Historial reciente de la conversacion:\n{history_block}"},
        ]

        try:
            welcome_text = await self.llm_client.chat(prompt_messages)
        except Exception as exc:
            raise WelcomeNarrativeEngineError(f"Error al generar la bienvenida narrativa: {exc}") from exc

        return {"message": welcome_text.strip(), "has_history": True}
