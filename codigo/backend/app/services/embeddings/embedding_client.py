import httpx


class EmbeddingClientError(Exception):
    pass


class EmbeddingServiceClient:
    def __init__(self, base_url: str, timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def embed_chunks(self, chunks: list[dict]) -> list[dict]:
        if not chunks:
            return []

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{self.base_url}/embed_chunks", json={"chunks": chunks})
                response.raise_for_status()
                return response.json()["chunks"]
        except httpx.HTTPError as exc:
            raise EmbeddingClientError(
                f"No se pudo contactar al servicio de embeddings en {self.base_url}: {exc}"
            ) from exc

    async def embed_text(self, text: str) -> list[float]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{self.base_url}/embed_text", json={"text": text})
                response.raise_for_status()
                return response.json()["embedding"]
        except httpx.HTTPError as exc:
            raise EmbeddingClientError(
                f"No se pudo contactar al servicio de embeddings en {self.base_url}: {exc}"
            ) from exc

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/health")
                response.raise_for_status()
                return True
        except httpx.HTTPError:
            return False
