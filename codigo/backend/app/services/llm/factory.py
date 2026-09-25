from functools import lru_cache

from app.core.config import settings
from app.services.llm.base import LLMClient
from app.services.llm.claude_client import ClaudeClient
from app.services.llm.ollama_client import OllamaClient


@lru_cache
def get_llm_client() -> LLMClient:
    if settings.llm_provider == "ollama":
        return OllamaClient(
            host=settings.ollama_host,
            model=settings.ollama_model,
            timeout=settings.ollama_timeout_seconds,
        )
    if settings.llm_provider == "claude":
        return ClaudeClient(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
            timeout=settings.anthropic_timeout_seconds,
        )
    raise NotImplementedError(f"Proveedor LLM no soportado todavia: {settings.llm_provider}")
