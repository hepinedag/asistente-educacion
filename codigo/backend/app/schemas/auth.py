from pydantic import BaseModel, ConfigDict, EmailStr

from app.models.user import UserRole


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserPublic(BaseModel):
    id: str
    email: EmailStr
    full_name: str
    role: UserRole
    environment_id: str | None = None

    model_config = ConfigDict(from_attributes=True)
