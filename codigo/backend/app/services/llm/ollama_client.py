import logging

import httpx

from app.services.llm.base import LLMClient

logger = logging.getLogger(__name__)


class OllamaClientError(Exception):
    pass


class OllamaClient(LLMClient):
    def __init__(self, host: str, model: str, timeout: float = 60.0):
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout

    async def chat(self, messages: list[dict[str, str]], **kwargs) -> str:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                logger.info(
                    "Ollama request: host=%s model=%s num_messages=%d",
                    self.host, self.model, len(messages)
                )
                response = await client.post(
                    f"{self.host}/api/chat",
                    json={
                        "model": self.model,
                        "messages": messages,
                        "stream": False,
                        "keep_alive": -1,
                        **kwargs,
                    },
                )
                response.raise_for_status()
                # No se logea el contenido de la respuesta -- deriva de
                # la conversacion del estudiante y del corpus academico.
                logger.info("Ollama response: status=%d", response.status_code)
                data = response.json()
                return data["message"]["content"]
        except httpx.HTTPError as exc:
            raise OllamaClientError(
                f"{type(exc).__name__} al llamar a Ollama en {self.host} "
                f"(modelo={self.model}, timeout={self.timeout}s): {exc}"
            ) from exc
        except (KeyError, ValueError) as exc:
            raise OllamaClientError(
                f"Respuesta de Ollama con formato inesperado (modelo={self.model}): {exc!r}"
            ) from exc

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.host}/api/tags")
                response.raise_for_status()
                models = [m["name"] for m in response.json().get("models", [])]
                return any(self.model in name for name in models)
        except httpx.HTTPError:
            return False
