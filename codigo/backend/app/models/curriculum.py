import enum
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.db.base import Base


class CurriculumStatus(str, enum.Enum):
    borrador = "borrador"
    aprobado = "aprobado"


class Curriculum(Base):
    __tablename__ = "curricula"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    environment_id = Column(String, ForeignKey("environments.id"), nullable=False)
    structure = Column(JSONB, nullable=False)
    status = Column(SAEnum(CurriculumStatus), nullable=False, default=CurriculumStatus.borrador)
    generated_at = Column(DateTime(timezone=True), server_default=func.now())
    approved_at = Column(DateTime(timezone=True), nullable=True)
