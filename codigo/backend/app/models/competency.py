import enum
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.sql import func

from app.db.base import Base


class CompetencyStatus(str, enum.Enum):
    comprende = "comprende"
    en_construccion = "en_construccion"
    confusion = "confusion"
    no_demostrado = "no_demostrado"


class Competency(Base):
    __tablename__ = "competencies"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    student_id = Column(String, ForeignKey("users.id"), nullable=False)
    environment_id = Column(String, ForeignKey("environments.id"), nullable=False)
    concept = Column(String, nullable=False)
    status = Column(SAEnum(CompetencyStatus), nullable=False)
    evidence_source = Column(String, nullable=True)
    detected_at = Column(DateTime(timezone=True), server_default=func.now())
