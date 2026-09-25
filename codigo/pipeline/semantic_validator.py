import logging

logger = logging.getLogger(__name__)

# Calibrado empiricamente para Cohere Rerank: el relevance_score de Cohere vive en una
# escala distinta y mucho mas separada que la similitud coseno (0.5 es el umbral para
# coseno, no para rerank). Con las 20 consultas de CT-1/CT-2: contenido irrelevante puntua siempre por debajo de 0.0005, contenido
# relevante siempre por encima de 0.0013. 0.002 deja margen de seguridad a ambos lados.
DEFAULT_RELEVANCE_THRESHOLD = 0.002


class SemanticValidator:
    # relevance_threshold no esta acotado a [0, 1]: cada proveedor de score (similitud coseno,
    # Cohere Rerank, cross-encoder local) usa una escala distinta -- el cross-encoder de
    # sentence-transformers devuelve logits crudos sin acotar (tipicamente entre -11 y +9).
    def __init__(self, relevance_threshold: float = DEFAULT_RELEVANCE_THRESHOLD):
        self.relevance_threshold = relevance_threshold

    def validate(self, chunks: list[dict]) -> dict:
        valid_chunks = []
        for chunk in chunks:
            score = chunk.get("score")
            if score is None:
                logger.warning("Chunk sin score, se descarta: %s", chunk.get("chunk_id", "<sin id>"))
                continue
            if score >= self.relevance_threshold:
                valid_chunks.append(chunk)

        valid_chunks.sort(key=lambda c: c["score"], reverse=True)

        return {"chunks": valid_chunks, "below_threshold": len(valid_chunks) == 0}
