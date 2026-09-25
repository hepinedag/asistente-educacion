import enum
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.sql import func

from app.db.base import Base


class CorpusVersionAction(str, enum.Enum):
    add = "add"
    update = "update"
    delete = "delete"


class CorpusVersion(Base):
    __tablename__ = "corpus_versions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    corpus_metadata_id = Column(String, ForeignKey("corpus_metadata.id"), nullable=False)
    version_number = Column(Integer, nullable=False)
    action = Column(SAEnum(CorpusVersionAction), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    created_by = Column(String, ForeignKey("users.id"), nullable=False)
    chunk_count = Column(Integer, nullable=True)
    notes = Column(Text, nullable=True)
