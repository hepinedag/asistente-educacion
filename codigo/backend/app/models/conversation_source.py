import uuid

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.sql import func

from app.db.base import Base


class ConversationSource(Base):
    __tablename__ = "conversation_sources"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(String, ForeignKey("conversations.id"), nullable=False)
    chunk_id = Column(String, nullable=True)
    filename = Column(String, nullable=True)
    page_number = Column(Integer, nullable=True)
    score = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
