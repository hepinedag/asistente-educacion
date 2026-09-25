from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.rbac import RBACMiddleware
from app.db.session import get_db
from app.models.environment import Environment, EnvironmentStatus
from app.models.user import User, UserRole
from app.schemas.environment import EnvironmentCreate, EnvironmentPublic

router = APIRouter()


@router.post("", response_model=EnvironmentPublic, status_code=status.HTTP_201_CREATED)
def create_environment(
    data: EnvironmentCreate,
    current_user: User = Depends(RBACMiddleware(UserRole.teacher, UserRole.admin)),
    db: Session = Depends(get_db),
):
    environment = Environment(
        teacher_id=current_user.id,
        name=data.name,
        description=data.description,
        status=EnvironmentStatus.published,
    )
    db.add(environment)
    db.flush()

    current_user.environment_id = environment.id
    db.commit()
    db.refresh(environment)
    return environment


@router.get("/{environment_id}", response_model=EnvironmentPublic)
def get_environment(
    environment_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Mismo criterio de aislamiento que teacher_dashboard: un usuario
    # solo puede consultar su propio entorno; admin conserva acceso transversal.
    if current_user.role != UserRole.admin and current_user.environment_id != environment_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tiene permisos para ver este entorno",
        )

    environment = db.query(Environment).filter(Environment.id == environment_id).first()
    if not environment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entorno no encontrado")

    return environment
