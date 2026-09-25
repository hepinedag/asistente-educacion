import uuid

from sqlalchemy import Column, DateTime, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.db.base import Base


class StudentProfile(Base):
    __tablename__ = "student_profiles"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    student_id = Column(String, ForeignKey("users.id"), nullable=False, unique=True)
    environment_id = Column(String, ForeignKey("environments.id"), nullable=False)
    knowledge_map = Column(JSONB, nullable=True)
    progress_index = Column(Float, nullable=False, default=0.0)
    depth_index = Column(Float, nullable=False, default=0.0)
    artifact_index = Column(Float, nullable=False, default=0.0)
    autonomy_index = Column(Float, nullable=False, default=0.0)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
