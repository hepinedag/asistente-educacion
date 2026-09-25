import logging

from pipeline.vector_index_manager import VectorIndexError, VectorIndexManager

logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 5


class SemanticRetrieverError(Exception):
    pass


class SemanticRetriever:
    """embedding_client solo necesita exponer `async def embed_text(text) -> list[float]`.

    Deliberadamente no se tipa contra `EmbeddingService` (codigo/pipeline/embedding_service.py):
    esa clase carga sentence-transformers en proceso, lo que no esta disponible dentro del
    contenedor fastapi. El cliente real inyectado ahi es `EmbeddingServiceClient`
    (codigo/backend/app/services/embeddings/embedding_client.py), que habla por HTTP con
    embedding_server.py corriendo fuera de Docker.
    """

    def __init__(self, embedding_client, vector_index_manager: VectorIndexManager):
        self.embedding_client = embedding_client
        self.vector_index_manager = vector_index_manager

    async def retrieve(self, environment_id: str, query: str, top_k: int = DEFAULT_TOP_K) -> list[dict]:
        if not query or not query.strip():
            raise SemanticRetrieverError("La consulta no puede estar vacia")
        if top_k <= 0:
            raise SemanticRetrieverError("top_k debe ser mayor que cero")

        try:
            query_embedding = await self.embedding_client.embed_text(query)
        except Exception as exc:
            raise SemanticRetrieverError(f"No se pudo vectorizar la consulta: {exc}") from exc

        try:
            collection = self.vector_index_manager.get_or_create_collection(environment_id)
            count = collection.count()
        except VectorIndexError as exc:
            raise SemanticRetrieverError(
                f"No se pudo acceder a la coleccion del entorno '{environment_id}': {exc}"
            ) from exc

        if count == 0:
            logger.warning("La coleccion del entorno '%s' esta vacia, no hay nada que recuperar", environment_id)
            return []

        try:
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=min(top_k, count),
                include=["metadatas", "documents", "distances"],
            )
        except Exception as exc:
            raise SemanticRetrieverError(
                f"Error al buscar en la coleccion del entorno '{environment_id}': {exc}"
            ) from exc

        chunks = self._build_chunks(results)
        logger.info(
            "Chunks recuperados: %d scores: %s",
            len(chunks), [c.get('score') for c in chunks]
        )
        return chunks

    @staticmethod
    def _build_chunks(results: dict) -> list[dict]:
        ids = (results.get("ids") or [[]])[0]
        distances = (results.get("distances") or [[]])[0]
        documents = (results.get("documents") or [[]])[0]
        metadatas = (results.get("metadatas") or [[]])[0]

        chunks = []
        for chunk_id, distance, document, metadata in zip(ids, distances, documents, metadatas):
            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "text": document,
                    # Coleccion creada con hnsw:space=cosine -> distance es distancia coseno.
                    "score": 1 - distance,
                    **(metadata or {}),
                }
            )
        return chunks
