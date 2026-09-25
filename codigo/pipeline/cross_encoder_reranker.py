import logging

from sentence_transformers import CrossEncoder

logger = logging.getLogger(__name__)

# cross-encoder/ms-marco-MiniLM-L-6-v2 es SOLO EN INGLES (entrenado sobre MS MARCO ingles):
# probado empiricamente contra el corpus real en espanol, no existe ningun umbral que
# separe correctamente consultas dentro/fuera del corpus (CT-1 y CT-2 nunca pasan juntos).
# mmarco-mMiniLMv2-L12-H384-v1 es la version multilingue del mismo modelo (mismo entrenamiento
# MS MARCO, extendido a mas de 100 idiomas via mMARCO) y si separa limpiamente en espanol.
DEFAULT_MODEL_NAME = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"


class CrossEncoderRerankerError(Exception):
    pass


class CrossEncoderReranker:
    def __init__(self, model_name: str = DEFAULT_MODEL_NAME):
        self.model_name = model_name
        try:
            self._model = CrossEncoder(model_name)
        except Exception as exc:
            raise CrossEncoderRerankerError(
                f"No se pudo cargar el modelo cross-encoder '{model_name}': {exc}"
            ) from exc

    def rerank(self, query: str, chunks: list[dict]) -> list[dict]:
        if not chunks:
            return []
        if not query or not query.strip():
            raise CrossEncoderRerankerError("La consulta no puede estar vacia")

        pairs = [(query, chunk["text"]) for chunk in chunks]

        try:
            scores = self._model.predict(pairs, show_progress_bar=False)
        except Exception as exc:
            raise CrossEncoderRerankerError(
                f"Error al reordenar chunks con cross-encoder ({self.model_name}): {exc}"
            ) from exc

        reranked = []
        for chunk, score in zip(chunks, scores):
            new_chunk = dict(chunk)
            new_chunk["cosine_score"] = new_chunk.get("score")
            new_chunk["score"] = float(score)
            reranked.append(new_chunk)

        reranked.sort(key=lambda c: c["score"], reverse=True)
        return reranked
