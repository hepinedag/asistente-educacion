import enum
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.db.base import Base


class EnvironmentStatus(str, enum.Enum):
    draft = "draft"
    published = "published"


class Environment(Base):
    __tablename__ = "environments"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    teacher_id = Column(String, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    knowledge_area = Column(String, nullable=True)
    education_level = Column(String, nullable=True)
    learning_objectives = Column(JSONB, nullable=True)
    status = Column(SAEnum(EnvironmentStatus), nullable=False, default=EnvironmentStatus.draft)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
