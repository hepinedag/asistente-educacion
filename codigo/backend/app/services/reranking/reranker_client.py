import httpx


class RerankerClientError(Exception):
    pass


class RerankerServiceClient:
    def __init__(self, base_url: str, timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def rerank(self, query: str, chunks: list[dict]) -> list[dict]:
        if not chunks:
            return []

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/rerank", json={"query": query, "chunks": chunks}
                )
                response.raise_for_status()
                return response.json()["chunks"]
        except httpx.HTTPError as exc:
            raise RerankerClientError(
                f"No se pudo contactar al servicio de reranking en {self.base_url}: {exc}"
            ) from exc
