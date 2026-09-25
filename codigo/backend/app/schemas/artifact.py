from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.models.artifact import ArtifactType


class ArtifactRequest(BaseModel):
    environment_id: str
    # Preguntas que el estudiante hizo sobre el tema, cuando el artefacto nace de
    # una propuesta del sistema: el artefacto se centra en ellas.
    focus: list[str] = []
    # Documento que motivo la propuesta: el artefacto se ancla a el.
    anchor_filename: str | None = None
    # El tema sobre el que se genera: es tambien la consulta con la que se
    # recupera el material del corpus.
    topic: str
    # Opcional: si no viene, se infiere del texto de topic (ver
    # infer_artifact_type en artifact_generation_engine).
    artifact_type: Optional[ArtifactType] = None


class ArtifactSourceCitation(BaseModel):
    chunk_id: str | None = None
    filename: str | None = None
    page_number: int | None = None
    score: float | None = None


class ArtifactResponse(BaseModel):
    id: str
    artifact_type: str
    format: str
    topic: str
    content: str
    sources: list[ArtifactSourceCitation] = []
    suggestions: list[str] = []
    created_at: datetime


class ArtifactSummary(BaseModel):
    id: str
    artifact_type: str
    format: str
    topic: str
    created_at: datetime
    source_count: int


class ArtifactListResponse(BaseModel):
    artifacts: list[ArtifactSummary]


class ArtifactSuggestion(BaseModel):
    """Propuesta del sistema: paso 1 del ciclo por la via no iniciada por el estudiante."""

    should_propose: bool
    topic: str | None = None
    # Las preguntas que sustentan la propuesta, para que el artefacto trate los
    # puntos que el estudiante trabajo y no el tema entero del corpus.
    focus: list[str] = []
    # Documento cuyas citas motivaron la propuesta, para anclar la generacion.
    anchor_filename: str | None = None
    artifact_type: str | None = None
    # Por que se propone, en lenguaje del estudiante: la propuesta tiene que poder
    # justificarse sola, o parece que el sistema adivina.
    reason: str | None = None
    citations: int = 0


class RetireResponse(BaseModel):
    """Cuantos artefactos se retiraron del portafolio. Retirar no es borrar."""
    retired: int
