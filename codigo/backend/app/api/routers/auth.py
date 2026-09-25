import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.rbac import RBACMiddleware
from app.core.security import decode_token
from app.db.session import get_db
from app.models.user import User, UserRole
from app.schemas.auth import RefreshRequest, TokenPair, UserLogin, UserPublic
from app.services.auth_service import AuthService

router = APIRouter()

# No hay registro publico de usuarios (POST /auth/register): aceptaria el rol
# que enviara quien llamara -cualquiera podria darse de alta como
# administrador-. El alta de usuarios la hace el modulo de administracion
# (codigo/admin), no la API.


@router.post("/login", response_model=TokenPair)
def login(data: UserLogin, db: Session = Depends(get_db)):
    service = AuthService(db)
    user = service.authenticate(data.email, data.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales invalidas")
    return TokenPair(
        access_token=service.create_access_token(user),
        refresh_token=service.create_refresh_token(user),
    )


@router.post("/refresh", response_model=TokenPair)
def refresh(data: RefreshRequest, db: Session = Depends(get_db)):
    service = AuthService(db)
    try:
        payload = decode_token(data.refresh_token)
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token de actualizacion invalido")

    if payload.get("token_type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token de actualizacion invalido")

    user = service.get_by_id(payload.get("user_id"))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token de actualizacion invalido")

    return TokenPair(
        access_token=service.create_access_token(user),
        refresh_token=service.create_refresh_token(user),
    )


@router.get("/me", response_model=UserPublic)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.get(
    "/users",
    response_model=list[UserPublic],
    dependencies=[Depends(RBACMiddleware(UserRole.admin))],
)
def list_users(db: Session = Depends(get_db)):
    return db.query(User).all()
