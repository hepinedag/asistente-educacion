import enum
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.sql import func

from app.db.base import Base


class ArtifactType(str, enum.Enum):
    resumen = "resumen"
    mapa_conceptual = "mapa_conceptual"
    ejercicio_aplicacion = "ejercicio_aplicacion"
    caso_practico = "caso_practico"
    autovaloracion = "autovaloracion"
    glosario = "glosario"
    # El tipo vive tambien como valor del ENUM artifacttype en PostgreSQL:
    # create_all no altera tipos existentes, asi que en una base ya creada se
    # anade con ALTER TYPE ... ADD VALUE.
    flash_cards = "flash_cards"
    cuestionario = "cuestionario"
    otro = "otro"


class ArtifactFormat(str, enum.Enum):
    markdown = "markdown"
    structured = "structured"
    table = "table"


class Artifact(Base):
    __tablename__ = "artifacts"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    student_id = Column(String, ForeignKey("users.id"), nullable=False)
    environment_id = Column(String, ForeignKey("environments.id"), nullable=False)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=True)
    artifact_type = Column(SAEnum(ArtifactType), nullable=False)
    # Tema sobre el que se genero: es lo que identifica al artefacto en el
    # portafolio del estudiante, donde el tipo y la fecha no bastan para saber
    # de que trata. Es tambien la consulta con la que se recupero el corpus.
    topic = Column(String, nullable=True)
    content = Column(Text, nullable=False)
    # Temas de continuacion que el modelo propone al cerrar el artefacto, uno por
    # linea. Van en columna aparte y no dentro de content para que la descarga en
    # .md sea el documento y nada mas.
    suggestions = Column(Text, nullable=True)
    format = Column(SAEnum(ArtifactFormat), nullable=False, default=ArtifactFormat.markdown)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    # Fecha en que el estudiante lo retiro de su portafolio. NULL = vigente.
    # Se retira, no se borra: el perfil se evaluara sobre los artefactos vigentes,
    # y artifact_sources -- que fragmentos sustentaron cada artefacto -- es el
    # unico dato del portafolio que no se puede reconstruir despues.
    retired_at = Column(DateTime(timezone=True), nullable=True)
