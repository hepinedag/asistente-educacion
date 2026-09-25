from datetime import datetime

from pydantic import BaseModel


class UploadResponse(BaseModel):
    document_id: str
    filename: str
    visible_title: str | None = None
    chunks_created: int


class CorpusDocumentStatus(BaseModel):
    document_id: str
    filename: str
    visible_title: str | None = None
    status: str
    chunk_count: int | None
    uploaded_at: datetime | None
    indexed_at: datetime | None
    # Motivo del fallo cuando status == 'error'. Sin esto, guardarlo no sirve de
    # nada: el docente ve "error" y no puede hacer nada con esa palabra.
    error_message: str | None = None


class CorpusStatusResponse(BaseModel):
    documents: list[CorpusDocumentStatus]
    total_documents: int
    total_chunks: int


class ReplaceResponse(BaseModel):
    document_id: str
    filename: str
    chunks_created: int
    version_number: int


class BatchUploadItem(BaseModel):
    """Resultado de UN archivo dentro de una carga multiple."""
    filename: str
    ok: bool
    document_id: str | None = None
    chunks_created: int | None = None
    version_number: int | None = None
    # 'add' cuando el documento es nuevo, 'update' cuando ya estaba registrado y
    # se trata como reemplazo. Sin esto el docente no sabe si duplico o sustituyo.
    action: str | None = None
    error: str | None = None


class BatchUploadResponse(BaseModel):
    results: list[BatchUploadItem]
    total: int
    indexed: int
    failed: int


class DeleteRequest(BaseModel):
    document_ids: list[str]


class DeleteResponse(BaseModel):
    document_id: str
    filename: str
    chunks_deleted: int
    version_number: int


class DeleteBatchResponse(BaseModel):
    deleted: list[DeleteResponse]
    not_found: list[str]
    total_chunks_deleted: int


class CorpusVersionEntry(BaseModel):
    version_id: str
    corpus_metadata_id: str
    filename: str
    version_number: int
    action: str
    created_at: datetime
    created_by: str
    chunk_count: int | None
    notes: str | None


class CorpusVersionsResponse(BaseModel):
    versions: list[CorpusVersionEntry]


class CorpusLastUpdatedResponse(BaseModel):
    last_updated_at: datetime | None


class TitleUpdateRequest(BaseModel):
    """Titulo tematico que escribe el docente. Vacio devuelve el documento a
    mostrarse por su nombre de archivo."""
    visible_title: str | None = None
