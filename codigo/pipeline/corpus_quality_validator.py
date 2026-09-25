import logging
import re

logger = logging.getLogger(__name__)

DEFAULT_MIN_TOKENS = 3
DEFAULT_MIN_UNIQUE_RATIO = 0.4
DEFAULT_MIN_LETTERS = 10


class CorpusQualityValidator:
    def __init__(
        self,
        min_tokens: int = DEFAULT_MIN_TOKENS,
        min_unique_ratio: float = DEFAULT_MIN_UNIQUE_RATIO,
        min_letters: int = DEFAULT_MIN_LETTERS,
    ):
        if min_tokens <= 0:
            raise ValueError("min_tokens debe ser mayor que cero")
        if not 0 < min_unique_ratio <= 1:
            raise ValueError("min_unique_ratio debe estar entre 0 y 1")
        if min_letters <= 0:
            raise ValueError("min_letters debe ser mayor que cero")

        self.min_tokens = min_tokens
        self.min_unique_ratio = min_unique_ratio
        self.min_letters = min_letters

    def validate(self, chunks: list[dict]) -> dict:
        valid_chunks = []
        discarded = []

        for chunk in chunks:
            reason = self._reject_reason(chunk)
            if reason:
                discarded.append(
                    {
                        "chunk_id": chunk.get("chunk_id"),
                        "filename": chunk.get("filename"),
                        "reason": reason,
                    }
                )
                continue
            valid_chunks.append(chunk)

        if discarded:
            logger.info(
                "CorpusQualityValidator: %s de %s chunks descartados por baja calidad semantica",
                len(discarded),
                len(chunks),
            )
            for item in discarded:
                logger.info(
                    "Chunk descartado %s (%s): %s", item["chunk_id"], item["filename"], item["reason"]
                )

        return {"chunks": valid_chunks, "discarded": discarded}

    def _reject_reason(self, chunk: dict) -> str | None:
        text = (chunk.get("text") or "").strip()
        if not text:
            return "chunk vacio"

        tokens = text.split()
        token_count = chunk.get("token_count")
        if token_count is None:
            token_count = len(tokens)

        if token_count < self.min_tokens:
            return f"longitud insuficiente ({token_count} tokens, minimo {self.min_tokens})"

        if self._is_repetitive(tokens):
            return "contenido repetitivo (baja variedad lexica)"

        if not self._has_substantive_content(text):
            return "sin contenido sustantivo (solo simbolos, numeros o espacios)"

        return None

    def _is_repetitive(self, tokens: list[str]) -> bool:
        if not tokens:
            return True
        normalized = [token.lower() for token in tokens]
        unique_ratio = len(set(normalized)) / len(normalized)
        return unique_ratio < self.min_unique_ratio

    def _has_substantive_content(self, text: str) -> bool:
        letters = re.findall(r"[^\W\d_]", text, flags=re.UNICODE)
        return len(letters) >= self.min_letters
