import logging

import chromadb

logger = logging.getLogger(__name__)


class VectorIndexError(Exception):
    pass


class VectorIndexManager:
    def __init__(self, host: str = "localhost", port: int = 8001):
        self.host = host
        self.port = port
        try:
            self._client = chromadb.HttpClient(host=host, port=port)
        except Exception as exc:
            raise VectorIndexError(f"No se pudo conectar a ChromaDB en {host}:{port}: {exc}") from exc

    def get_or_create_collection(self, environment_id: str):
        collection_name = self._collection_name(environment_id)
        try:
            # hnsw:space=cosine es obligatorio aqui: SemanticRetriever interpreta la
            # "distance" que devuelve ChromaDB como distancia coseno (score = 1 - distance).
            return self._client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"},
            )
        except Exception as exc:
            raise VectorIndexError(f"No se pudo crear/recuperar la coleccion '{collection_name}': {exc}") from exc

    def index_chunks(self, environment_id: str, chunks: list[dict]) -> int:
        if not chunks:
            return 0

        collection = self.get_or_create_collection(environment_id)

        ids: list[str] = []
        embeddings: list[list[float]] = []
        documents: list[str] = []
        metadatas: list[dict] = []

        for chunk in chunks:
            if "embedding" not in chunk:
                raise VectorIndexError(f"Chunk sin embedding, no se puede indexar: {chunk.get('chunk_id', '<sin id>')}")

            ids.append(chunk["chunk_id"])
            embeddings.append(chunk["embedding"])
            documents.append(chunk["text"])
            metadatas.append(
                {
                    "filename": chunk["filename"],
                    "page_number": chunk["page_number"],
                    "chunk_index": chunk["chunk_index"],
                    "token_count": chunk["token_count"],
                }
            )

        try:
            collection.upsert(ids=ids, embeddings=embeddings, metadatas=metadatas, documents=documents)
        except Exception as exc:
            raise VectorIndexError(f"Error al indexar chunks en '{collection.name}': {exc}") from exc

        return len(ids)

    def ids_by_filename(self, environment_id: str, filename: str) -> list[str]:
        """Identificadores de los fragmentos que hay ahora mismo para ese documento.

        Se usa para reemplazar sin destruir: se anotan los ids viejos ANTES de
        generar los nuevos, y solo despues se borran los que dejaron de existir.
        """
        collection = self.get_or_create_collection(environment_id)
        try:
            existing = collection.get(where={"filename": filename}, include=[])
        except Exception as exc:
            raise VectorIndexError(
                f"No se pudieron consultar los chunks de '{filename}' en '{collection.name}': {exc}"
            ) from exc
        return list(existing.get("ids") or [])

    def delete_by_ids(self, environment_id: str, ids: list[str]) -> int:
        """Borra fragmentos concretos. Con lista vacia no hace nada."""
        if not ids:
            return 0
        collection = self.get_or_create_collection(environment_id)
        try:
            collection.delete(ids=ids)
        except Exception as exc:
            raise VectorIndexError(
                f"No se pudieron eliminar {len(ids)} chunks en '{collection.name}': {exc}"
            ) from exc
        return len(ids)

    def delete_by_filename(self, environment_id: str, filename: str) -> int:
        collection = self.get_or_create_collection(environment_id)

        try:
            existing = collection.get(where={"filename": filename}, include=[])
            count = len(existing.get("ids") or [])
            if count:
                collection.delete(where={"filename": filename})
        except Exception as exc:
            raise VectorIndexError(
                f"No se pudieron eliminar los chunks de '{filename}' en '{collection.name}': {exc}"
            ) from exc

        return count

    def delete_collection(self, environment_id: str) -> bool:
        """Elimina la coleccion entera del entorno, no solo sus vectores.

        Hace falta porque la dimension del vector es una propiedad de la COLECCION,
        fijada al crearla con el primer embedding que recibe. Borrar todos los
        vectores deja la coleccion viva y con su dimension anterior, de modo que un
        cambio de proveedor de embeddings -1024 de Cohere a 384 del modelo local-
        falla en la primera carga con "Collection expecting embedding with dimension
        of 1024, got 384", y el entorno queda sin corpus y sin manera de volver a
        indexarlo. Sin esto, el sistema no puede cambiar de modo nube a modo local.

        Devuelve False si la coleccion no existia, que no es un error.
        """
        collection_name = self._collection_name(environment_id)
        try:
            self._client.delete_collection(name=collection_name)
        except Exception as exc:
            if "does not exist" in str(exc).lower() or "not found" in str(exc).lower():
                logger.info("La coleccion '%s' no existia; nada que eliminar", collection_name)
                return False
            raise VectorIndexError(
                f"No se pudo eliminar la coleccion '{collection_name}': {exc}"
            ) from exc

        logger.info("Coleccion '%s' eliminada", collection_name)
        return True

    @staticmethod
    def _collection_name(environment_id: str) -> str:
        return f"corpus_{environment_id}"
