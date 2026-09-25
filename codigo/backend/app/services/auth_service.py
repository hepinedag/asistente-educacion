from datetime import timedelta

from sqlalchemy.orm import Session

from app.core import security
from app.core.config import settings
from app.models.user import User


class AuthService:
    def __init__(self, db: Session):
        self.db = db

    def authenticate(self, email: str, password: str) -> User | None:
        user = self.db.query(User).filter(User.email == email).first()
        if not user or not security.verify_password(password, user.hashed_password):
            return None
        return user

    def get_by_id(self, user_id: str) -> User | None:
        return self.db.query(User).filter(User.id == user_id).first()

    def create_access_token(self, user: User) -> str:
        payload = {
            "user_id": user.id,
            "role": user.role.value,
            "environment_id": user.environment_id,
            "token_type": "access",
        }
        return security.create_token(payload, timedelta(minutes=settings.access_token_expire_minutes))

    def create_refresh_token(self, user: User) -> str:
        payload = {
            "user_id": user.id,
            "role": user.role.value,
            "environment_id": user.environment_id,
            "token_type": "refresh",
        }
        return security.create_token(payload, timedelta(days=settings.refresh_token_expire_days))
