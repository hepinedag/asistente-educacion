import enum
import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.sql import func

from app.db.base import Base


class Speaker(str, enum.Enum):
    student = "student"
    system = "system"


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    student_id = Column(String, ForeignKey("users.id"), nullable=False)
    speaker = Column(SAEnum(Speaker), nullable=False)
    message = Column(Text, nullable=False)
    cycle = Column(String, nullable=True)
    below_threshold = Column(Boolean, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
