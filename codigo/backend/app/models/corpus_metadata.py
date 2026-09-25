import enum
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.sql import func, text

from app.db.base import Base


class CorpusFileType(str, enum.Enum):
    pdf = "pdf"
    word = "word"
    markdown = "markdown"


class CorpusIndexStatus(str, enum.Enum):
    pendiente = "pendiente"
    procesando = "procesando"
    indexado = "indexado"
    error = "error"
    eliminado = "eliminado"


class CorpusMetadata(Base):
    __tablename__ = "corpus_metadata"
    # Un documento por entorno y nombre de archivo. Sin esta restriccion, subir dos
    # veces el mismo archivo crearia dos documentos, y el panel contaria mal.
    # Parcial a proposito: los eliminados quedan fuera, porque hay que poder borrar
    # un documento y volver a subirlo.
    __table_args__ = (
        Index(
            "ux_corpus_metadata_entorno_archivo",
            "environment_id",
            "filename",
            unique=True,
            postgresql_where=text("status <> 'eliminado'"),
        ),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    environment_id = Column(String, ForeignKey("environments.id"), nullable=False)
    filename = Column(String, nullable=False)
    visible_title = Column(String, nullable=True)
    file_type = Column(SAEnum(CorpusFileType), nullable=False)
    status = Column(SAEnum(CorpusIndexStatus), nullable=False, default=CorpusIndexStatus.pendiente)
    # Motivo del ultimo fallo de indexacion. Con solo status='error' el motivo se
    # perderia en la respuesta HTTP y no quedaria forma de saber por que fallo un
    # documento. Se limpia al indexar con exito.
    error_message = Column(String, nullable=True)
    chunk_count = Column(Integer, nullable=True)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())
    indexed_at = Column(DateTime(timezone=True), nullable=True)
