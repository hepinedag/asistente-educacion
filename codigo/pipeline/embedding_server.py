import logging

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from pipeline.embedding_service import EmbeddingService, EmbeddingServiceError
from pipeline.reranker_service import RerankerService, RerankerServiceError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Embedding Service (local, fuera de Docker)")

_embedding_service: EmbeddingService | None = None
_reranker_service: RerankerService | None = None


def _get_embedding_service() -> EmbeddingService:
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service


def _get_reranker_service() -> RerankerService:
    global _reranker_service
    if _reranker_service is None:
        _reranker_service = RerankerService()
    return _reranker_service


class EmbedChunksRequest(BaseModel):
    chunks: list[dict]


class EmbedTextRequest(BaseModel):
    text: str


class RerankRequest(BaseModel):
    query: str
    chunks: list[dict]


@app.post("/embed_chunks")
def embed_chunks(payload: EmbedChunksRequest):
    try:
        service = _get_embedding_service()
        return {"chunks": service.embed_chunks(payload.chunks)}
    except EmbeddingServiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/embed_text")
def embed_text(payload: EmbedTextRequest):
    try:
        service = _get_embedding_service()
        return {"embedding": service.embed_text(payload.text)}
    except EmbeddingServiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/rerank")
def rerank(payload: RerankRequest):
    try:
        service = _get_reranker_service()
        return {"chunks": service.rerank(payload.query, payload.chunks)}
    except RerankerServiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/health")
def health():
    try:
        service = _get_embedding_service()
    except EmbeddingServiceError as exc:
        return {"status": "error", "detail": str(exc)}
    return {"status": "ok", "model": service.model_name, "max_seq_length": service.max_seq_length}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("pipeline.embedding_server:app", host="0.0.0.0", port=8500, reload=False)
