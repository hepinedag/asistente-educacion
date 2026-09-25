import enum
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.sql import func

from app.db.base import Base


class SessionStatus(str, enum.Enum):
    active = "active"
    closed = "closed"


class LearningSession(Base):
    __tablename__ = "sessions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    student_id = Column(String, ForeignKey("users.id"), nullable=False)
    environment_id = Column(String, ForeignKey("environments.id"), nullable=False)
    status = Column(SAEnum(SessionStatus), nullable=False, default=SessionStatus.active)
    compressed_context = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    ended_at = Column(DateTime(timezone=True), nullable=True)
