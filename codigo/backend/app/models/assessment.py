import enum
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.db.base import Base


class AssessmentType(str, enum.Enum):
    preguntas_rubrica = "preguntas_rubrica"
    sintesis_escrita = "sintesis_escrita"
    caso_aplicacion = "caso_aplicacion"
    proyecto_integrador = "proyecto_integrador"


class Assessment(Base):
    __tablename__ = "assessments"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    environment_id = Column(String, ForeignKey("environments.id"), nullable=False)
    student_id = Column(String, ForeignKey("users.id"), nullable=True)
    assessment_type = Column(SAEnum(AssessmentType), nullable=False)
    content = Column(JSONB, nullable=False)
    period_label = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
