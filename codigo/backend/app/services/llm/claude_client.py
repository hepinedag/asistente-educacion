import asyncio
import logging

import anthropic

from app.services.llm.base import LLMClient

logger = logging.getLogger(__name__)

DEFAULT_MAX_TOKENS = 1024


class ClaudeClientError(Exception):
    pass


class ClaudeClient(LLMClient):
    def __init__(self, api_key: str, model: str, timeout: float = 120.0):
        self.model = model
        self.timeout = timeout
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout)

    async def chat(self, messages: list[dict[str, str]], **kwargs) -> str:
        system_instruction = "\n\n".join(
            m["content"] for m in messages if m.get("role") == "system"
        )
        conversation = [m for m in messages if m.get("role") != "system"]

        create_kwargs = {"max_tokens": DEFAULT_MAX_TOKENS, **kwargs}
        if system_instruction:
            create_kwargs["system"] = system_instruction

        try:
            logger.info(
                "Claude request: model=%s num_messages=%d", self.model, len(conversation)
            )
            response = await asyncio.to_thread(
                self._client.messages.create,
                model=self.model,
                messages=conversation,
                **create_kwargs,
            )
            logger.info("Claude response: stop_reason=%s", response.stop_reason)
            return "".join(
                block.text for block in response.content if getattr(block, "type", None) == "text"
            )
        except anthropic.AnthropicError as exc:
            raise ClaudeClientError(
                f"{type(exc).__name__} al llamar a Claude (modelo={self.model}, timeout={self.timeout}s): {exc}"
            ) from exc
        except (AttributeError, IndexError, KeyError) as exc:
            raise ClaudeClientError(
                f"Respuesta de Claude con formato inesperado (modelo={self.model}): {exc!r}"
            ) from exc

    async def health_check(self) -> bool:
        try:
            await asyncio.to_thread(self._client.models.list)
            return True
        except anthropic.AnthropicError:
            return False
