from fastapi import APIRouter

from app.core.config import settings
from app.services.embeddings.embedding_client import EmbeddingServiceClient
from app.services.llm.factory import get_llm_client

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok", "environment": settings.environment}


@router.get("/health/llm")
async def health_llm():
    client = get_llm_client()
    available = await client.health_check()
    model = settings.anthropic_model if settings.llm_provider == "claude" else settings.ollama_model
    return {
        "provider": settings.llm_provider,
        "model": model,
        "available": available,
    }


@router.get("/health/embeddings")
async def health_embeddings():
    client = EmbeddingServiceClient(base_url=settings.embedding_service_url)
    available = await client.health_check()
    return {
        "model": settings.embedding_model,
        "service_url": settings.embedding_service_url,
        "available": available,
    }
