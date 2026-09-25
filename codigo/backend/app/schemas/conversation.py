from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class MessageRequest(BaseModel):
    message: str
    environment_id: str


class SourceCitation(BaseModel):
    chunk_id: str | None = None
    filename: str | None = None
    page_number: int | None = None
    score: float | None = None


class MessageResponse(BaseModel):
    answer: str
    sources: list[SourceCitation]
    below_threshold: bool
    suggestions: list[str] = []


class HistoryMessage(BaseModel):
    speaker: str
    text: str
    below_threshold: Optional[bool] = None
    created_at: datetime
    sources: list[SourceCitation] = []


class ConversationHistoryResponse(BaseModel):
    messages: list[HistoryMessage]


class WelcomeResponse(BaseModel):
    message: str
    has_history: bool


class ProgressDocument(BaseModel):
    filename: str
    visible_title: str | None = None
    display_title: str


class LearningProgressResponse(BaseModel):
    active: Optional[ProgressDocument] = None
    completed: list[ProgressDocument]
    pending: list[ProgressDocument]
