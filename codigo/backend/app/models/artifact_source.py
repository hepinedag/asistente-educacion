import uuid

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.sql import func

from app.db.base import Base


class ArtifactSource(Base):
    """Chunks del corpus que sustentaron la generacion de un artefacto.

    Espejo de ConversationSource, que hace lo mismo para las respuestas del
    chat. Se persiste desde el principio por una razon concreta: la inteligencia
    evolutiva del sistema interpretara el artefacto como evidencia de
    competencia, y para eso necesita saber sobre que material se construyo.
    Un artefacto generado sin sus fuentes no se puede reinterpretar despues:
    habria que regenerarlo o descartarlo como evidencia.
    """

    __tablename__ = "artifact_sources"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    artifact_id = Column(String, ForeignKey("artifacts.id"), nullable=False)
    chunk_id = Column(String, nullable=True)
    filename = Column(String, nullable=True)
    page_number = Column(Integer, nullable=True)
    score = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
