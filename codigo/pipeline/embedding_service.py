import logging
import os
from pathlib import Path

from sentence_transformers import SentenceTransformer

from pipeline.cohere_embedding_client import CohereEmbeddingClient, CohereEmbeddingError

logger = logging.getLogger(__name__)

DEFAULT_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
ENV_PATH = Path(__file__).resolve().parents[2] / "config" / ".env"


class EmbeddingServiceError(Exception):
    pass


def _read_env_value(key: str) -> str:
    value = os.environ.get(key)
    if value:
        return value

    if not ENV_PATH.exists():
        return ""

    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        env_key, _, env_value = stripped.partition("=")
        if env_key.strip() == key:
            return env_value.strip()

    return ""


class EmbeddingService:
    def __init__(self, model_name: str = DEFAULT_MODEL_NAME):
        self.provider = _read_env_value("EMBEDDING_PROVIDER") or "sentence-transformers"

        if self.provider == "cohere":
            api_key = _read_env_value("COHERE_API_KEY")
            try:
                self._cohere_client = CohereEmbeddingClient(api_key=api_key)
            except CohereEmbeddingError as exc:
                raise EmbeddingServiceError(f"No se pudo inicializar el proveedor Cohere: {exc}") from exc
            self.model_name = self._cohere_client.model_name
            self.max_seq_length = None
            return

        self.model_name = model_name
        try:
            self._model = SentenceTransformer(model_name)
        except Exception as exc:
            raise EmbeddingServiceError(f"No se pudo cargar el modelo de embeddings '{model_name}': {exc}") from exc

        self.max_seq_length = getattr(self._model, "max_seq_length", None)

    def embed_chunks(self, chunks: list[dict]) -> list[dict]:
        if not chunks:
            return []

        if self.provider == "cohere":
            try:
                return self._cohere_client.embed_chunks(chunks)
            except CohereEmbeddingError as exc:
                raise EmbeddingServiceError(f"Error al vectorizar chunks con Cohere: {exc}") from exc

        texts = [chunk["text"] for chunk in chunks]
        self._warn_if_truncated(texts)

        try:
            vectors = self._model.encode(texts, show_progress_bar=False, convert_to_numpy=True)
        except Exception as exc:
            raise EmbeddingServiceError(f"Error al vectorizar chunks: {exc}") from exc

        return [{**chunk, "embedding": vector.tolist()} for chunk, vector in zip(chunks, vectors)]

    def embed_text(self, text: str) -> list[float]:
        if not text or not text.strip():
            raise EmbeddingServiceError("No se puede vectorizar un texto vacio")

        if self.provider == "cohere":
            try:
                return self._cohere_client.embed_text(text)
            except CohereEmbeddingError as exc:
                raise EmbeddingServiceError(f"Error al vectorizar texto con Cohere: {exc}") from exc

        self._warn_if_truncated([text])

        try:
            vector = self._model.encode(text, show_progress_bar=False, convert_to_numpy=True)
        except Exception as exc:
            raise EmbeddingServiceError(f"Error al vectorizar texto: {exc}") from exc

        return vector.tolist()

    def _warn_if_truncated(self, texts: list[str]) -> None:
        if not self.max_seq_length:
            return

        tokenizer = getattr(self._model, "tokenizer", None)
        if tokenizer is None:
            return

        for text in texts:
            token_count = len(tokenizer.tokenize(text))
            if token_count > self.max_seq_length:
                logger.warning(
                    "Un chunk de %s tokens excede max_seq_length=%s del modelo '%s'; "
                    "el modelo lo truncara silenciosamente al vectorizar.",
                    token_count,
                    self.max_seq_length,
                    self.model_name,
                )
