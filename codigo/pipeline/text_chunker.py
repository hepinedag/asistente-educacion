import logging
import re

logger = logging.getLogger(__name__)


class TextChunkError(Exception):
    pass


class TextChunker:
    def __init__(self, chunk_size_tokens: int = 120, chunk_overlap_tokens: int = 12):
        if chunk_size_tokens <= 0:
            raise ValueError("chunk_size_tokens debe ser mayor que cero")
        if chunk_overlap_tokens < 0 or chunk_overlap_tokens >= chunk_size_tokens:
            raise ValueError("chunk_overlap_tokens debe estar entre 0 y chunk_size_tokens - 1")

        self.chunk_size_tokens = chunk_size_tokens
        self.chunk_overlap_tokens = chunk_overlap_tokens

    def chunk_texts(self, pages: list[dict]) -> list[dict]:
        chunks: list[dict] = []
        for page in pages:
            try:
                chunks.extend(self._chunk_page(page))
            except TextChunkError as exc:
                logger.error(
                    "Error al fragmentar %s (pagina %s): %s",
                    page.get("filename"),
                    page.get("page_number"),
                    exc,
                )
                continue
        return chunks

    def _chunk_page(self, page: dict) -> list[dict]:
        filename = page.get("filename")
        page_number = page.get("page_number")
        text = page.get("text")

        if not filename or page_number is None:
            raise TextChunkError("metadatos incompletos (filename / page_number)")
        if not text or not text.strip():
            raise TextChunkError("texto vacio")

        tokens = self._tokenize(text)
        if not tokens:
            raise TextChunkError("sin tokens extraibles")

        step = self.chunk_size_tokens - self.chunk_overlap_tokens
        slug = self._slugify(filename)

        chunks = []
        chunk_index = 0
        start = 0
        while start < len(tokens):
            window = tokens[start : start + self.chunk_size_tokens]
            chunks.append(
                {
                    "chunk_id": f"{slug}_p{page_number}_c{chunk_index}",
                    "filename": filename,
                    "page_number": page_number,
                    "chunk_index": chunk_index,
                    "token_count": len(window),
                    "text": " ".join(window),
                }
            )

            if start + self.chunk_size_tokens >= len(tokens):
                break

            chunk_index += 1
            start += step

        return chunks

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        # Aproximacion por palabras, no el tokenizador real del modelo de embeddings
        # (ver max_seq_length en embedding_service.py: el modelo trunca a 128 tokens reales).
        return re.findall(r"\S+", text)

    @staticmethod
    def _slugify(value: str) -> str:
        value = re.sub(r"[^\w]+", "_", value)
        return value.strip("_")
