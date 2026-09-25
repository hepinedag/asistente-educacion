import logging

from pipeline.cross_encoder_reranker import CrossEncoderReranker, CrossEncoderRerankerError
from pipeline.embedding_service import _read_env_value
from pipeline.reranker import ReRanker, ReRankerError

logger = logging.getLogger(__name__)


class RerankerServiceError(Exception):
    pass


class RerankerService:
    def __init__(self):
        self.provider = _read_env_value("RERANKER_PROVIDER") or "cross-encoder"

        if self.provider == "cohere":
            api_key = _read_env_value("COHERE_API_KEY")
            try:
                self._client = ReRanker(api_key=api_key)
            except ReRankerError as exc:
                raise RerankerServiceError(f"No se pudo inicializar el proveedor Cohere Rerank: {exc}") from exc
            return

        try:
            self._client = CrossEncoderReranker()
        except CrossEncoderRerankerError as exc:
            raise RerankerServiceError(f"No se pudo inicializar el cross-encoder local: {exc}") from exc

    def rerank(self, query: str, chunks: list[dict]) -> list[dict]:
        try:
            return self._client.rerank(query, chunks)
        except (ReRankerError, CrossEncoderRerankerError) as exc:
            raise RerankerServiceError(f"Error al reordenar chunks ({self.provider}): {exc}") from exc
