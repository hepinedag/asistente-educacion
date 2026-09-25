import logging

import cohere

logger = logging.getLogger(__name__)

DEFAULT_MODEL_NAME = "rerank-multilingual-v3.0"


class ReRankerError(Exception):
    pass


class ReRanker:
    def __init__(self, api_key: str, model_name: str = DEFAULT_MODEL_NAME):
        if not api_key:
            raise ReRankerError("COHERE_API_KEY no esta configurada")

        self.model_name = model_name
        try:
            self._client = cohere.ClientV2(api_key)
        except Exception as exc:
            raise ReRankerError(f"No se pudo inicializar el cliente de Cohere Rerank: {exc}") from exc

    def rerank(self, query: str, chunks: list[dict]) -> list[dict]:
        if not chunks:
            return []
        if not query or not query.strip():
            raise ReRankerError("La consulta no puede estar vacia")

        documents = [chunk["text"] for chunk in chunks]

        try:
            response = self._client.rerank(model=self.model_name, query=query, documents=documents)
        except Exception as exc:
            raise ReRankerError(f"Error al reordenar chunks con Cohere Rerank ({self.model_name}): {exc}") from exc

        reranked = []
        for result in response.results:
            chunk = dict(chunks[result.index])
            chunk["cosine_score"] = chunk.get("score")
            chunk["score"] = result.relevance_score
            reranked.append(chunk)

        return reranked
