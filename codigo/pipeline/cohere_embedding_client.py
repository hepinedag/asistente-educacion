import logging

import cohere

logger = logging.getLogger(__name__)

DEFAULT_MODEL_NAME = "embed-multilingual-v3.0"
MAX_TEXTS_PER_REQUEST = 90


class CohereEmbeddingError(Exception):
    pass


class CohereEmbeddingClient:
    def __init__(self, api_key: str, model_name: str = DEFAULT_MODEL_NAME):
        if not api_key:
            raise CohereEmbeddingError("COHERE_API_KEY no esta configurada")

        self.model_name = model_name
        try:
            self._client = cohere.ClientV2(api_key)
        except Exception as exc:
            raise CohereEmbeddingError(f"No se pudo inicializar el cliente de Cohere: {exc}") from exc

    def embed_chunks(self, chunks: list[dict]) -> list[dict]:
        if not chunks:
            return []

        texts = [chunk["text"] for chunk in chunks]
        vectors: list[list[float]] = []
        for start in range(0, len(texts), MAX_TEXTS_PER_REQUEST):
            batch = texts[start : start + MAX_TEXTS_PER_REQUEST]
            vectors.extend(self._embed(batch, input_type="search_document"))

        return [{**chunk, "embedding": vector} for chunk, vector in zip(chunks, vectors)]

    def embed_text(self, text: str) -> list[float]:
        if not text or not text.strip():
            raise CohereEmbeddingError("No se puede vectorizar un texto vacio")

        vectors = self._embed([text], input_type="search_query")
        return vectors[0]

    def _embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        try:
            response = self._client.embed(
                texts=texts,
                model=self.model_name,
                input_type=input_type,
                embedding_types=["float"],
            )
        except Exception as exc:
            raise CohereEmbeddingError(f"Error al vectorizar con Cohere ({self.model_name}): {exc}") from exc

        return response.embeddings.float_
