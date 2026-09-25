from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class EnvironmentCreate(BaseModel):
    name: str
    description: Optional[str] = None


class EnvironmentPublic(BaseModel):
    id: str
    teacher_id: str
    name: str
    description: Optional[str] = None
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
