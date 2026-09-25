import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rbac import RBACMiddleware
from app.db.session import get_db
from app.models.artifact import Artifact, ArtifactType
from app.models.artifact_source import ArtifactSource
from app.models.conversation import Conversation, Speaker
from app.models.conversation_source import ConversationSource
from app.models.learning_session import LearningSession, SessionStatus
from app.models.user import User, UserRole
from app.schemas.artifact import (
    ArtifactListResponse,
    ArtifactRequest,
    ArtifactResponse,
    ArtifactSourceCitation,
    ArtifactSuggestion,
    ArtifactSummary,
    RetireResponse,
)
from app.services.artifact_generation_engine import (
    ARTIFACT_MIN_TOP_SCORES,
    ArtifactGenerationEngine,
    ArtifactGenerationEngineError,
    infer_artifact_type,
)
from app.services.embeddings.embedding_client import EmbeddingServiceClient
from app.services.llm.factory import get_llm_client
from app.services.reranking.reranker_client import RerankerServiceClient
from pipeline.semantic_retriever import SemanticRetriever
from pipeline.semantic_validator import DEFAULT_RELEVANCE_THRESHOLD, SemanticValidator
from pipeline.vector_index_manager import VectorIndexManager

logger = logging.getLogger(__name__)
router = APIRouter()

# Mismos umbrales por proveedor que usa el chat (ver routers/conversation.py):
# cada escala de score tiene el suyo y mezclarlos deja pasar material irrelevante.
RERANKER_THRESHOLDS = {
    "cohere": 0.002,
    "cross-encoder": -4.0,
}

# El artefacto se apoya en lo ultimo trabajado para saber con que enfoque se
# abordo el tema. No es fuente de contenido: eso siempre sale del corpus.
MAX_HISTORY_EXCHANGES = 5

# Cuantas respuestas de la sesion deben apoyarse en el mismo documento para que el
# sistema considere que el tema "se ha trabajado bastante" y ofrezca un artefacto.
# Con top_k=5 por respuesta, 4 citas al mismo documento significan que el tema
# volvio varias veces, no que aparecio de refilon una vez.
MIN_CITATIONS_TO_PROPOSE = 4

# El resumen es el artefacto mas neutro: el que menos presupone sobre lo que el
# estudiante necesita. La propuesta abre la puerta; el tipo lo decide el.
SUGGESTED_TYPE = ArtifactType.resumen


def _build_engine() -> ArtifactGenerationEngine:
    embedding_client = EmbeddingServiceClient(base_url=settings.embedding_service_url)
    vector_index_manager = VectorIndexManager(host=settings.chroma_host, port=settings.chroma_port)
    semantic_retriever = SemanticRetriever(embedding_client, vector_index_manager)
    reranker = RerankerServiceClient(base_url=settings.embedding_service_url)
    reranker_threshold = RERANKER_THRESHOLDS.get(settings.reranker_provider, DEFAULT_RELEVANCE_THRESHOLD)
    semantic_validator = SemanticValidator(relevance_threshold=reranker_threshold)
    fallback_validator = SemanticValidator(relevance_threshold=0.5)
    return ArtifactGenerationEngine(
        semantic_retriever,
        semantic_validator,
        get_llm_client(),
        reranker,
        fallback_validator,
        min_top_score=ARTIFACT_MIN_TOP_SCORES.get(settings.reranker_provider),
    )


def _active_session(db: Session, student_id: str, environment_id: str) -> LearningSession | None:
    return (
        db.query(LearningSession)
        .filter(
            LearningSession.student_id == student_id,
            LearningSession.environment_id == environment_id,
            LearningSession.status == SessionStatus.active,
        )
        .order_by(LearningSession.started_at.desc())
        .first()
    )


def _questions_about(db: Session, session_id: str, filename: str) -> list[str]:
    """Preguntas del estudiante cuyas respuestas se apoyaron en ese documento.

    La ultima es el tema del artefacto; todas juntas son el foco, lo que el
    estudiante trabajo de verdad. Sin ellas el resumen cubriria el tema tal como
    lo trata el corpus, que no es lo mismo que lo que el pregunto.

    El titulo del documento NO sirve como tema: "Presentacion Sesion 13" no es
    contenido, y la busqueda en el corpus no encuentra nada relevante para el
    -- comprobado, la barrera de relevancia lo rechaza. La pregunta del estudiante,
    en cambio, ya demostro recuperar ese material, y ademas es como el estudiante
    nombra el tema.
    """
    mensajes = (
        db.query(Conversation)
        .filter(Conversation.session_id == session_id)
        .order_by(Conversation.created_at.asc())
        .all()
    )
    citantes = {
        row.conversation_id
        for row in db.query(ConversationSource.conversation_id)
        .join(Conversation, ConversationSource.conversation_id == Conversation.id)
        .filter(Conversation.session_id == session_id, ConversationSource.filename == filename)
        .all()
    }

    preguntas: list[str] = []
    pregunta_pendiente = None
    for mensaje in mensajes:
        if mensaje.speaker == Speaker.student:
            pregunta_pendiente = mensaje.message
        elif mensaje.id in citantes and pregunta_pendiente:
            limpia = pregunta_pendiente.strip().rstrip("?¿").strip()[:120]
            if limpia and limpia not in preguntas:
                preguntas.append(limpia)
            pregunta_pendiente = None
    return preguntas


def _recent_history(db: Session, session_id: str) -> list[dict]:
    rows = (
        db.query(Conversation)
        .filter(Conversation.session_id == session_id)
        .order_by(Conversation.created_at.desc())
        .limit(MAX_HISTORY_EXCHANGES * 2)
        .all()
    )
    rows.reverse()
    return [{"speaker": row.speaker.value, "text": row.message} for row in rows]


@router.post("", response_model=ArtifactResponse, status_code=status.HTTP_201_CREATED)
async def create_artifact(
    payload: ArtifactRequest,
    current_user: User = Depends(RBACMiddleware(UserRole.student)),
    db: Session = Depends(get_db),
):
    # Paso 2 del ciclo: si el cliente no declara el tipo, se deduce del texto.
    artifact_type = payload.artifact_type or infer_artifact_type(payload.topic)

    session = _active_session(db, current_user.id, payload.environment_id)
    conversation_history = _recent_history(db, session.id) if session else []

    engine = _build_engine()
    try:
        result = await engine.generate(
            payload.environment_id,
            artifact_type,
            payload.topic,
            conversation_history,
            focus=payload.focus or None,
            prefer_filename=payload.anchor_filename,
        )
    except ArtifactGenerationEngineError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    # Sin material suficiente no se persiste nada: un artefacto vacio en el
    # portafolio es peor que ningun artefacto, y no es evidencia de nada.
    if result["below_threshold"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result["content"])

    artifact = Artifact(
        student_id=current_user.id,
        environment_id=payload.environment_id,
        session_id=session.id if session else None,
        artifact_type=artifact_type,
        topic=payload.topic.strip(),
        content=result["content"],
        suggestions="\n".join(result.get("suggestions") or []) or None,
        format=result["format"],
    )
    db.add(artifact)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El entorno especificado no existe",
        ) from exc
    db.refresh(artifact)

    for source in result["sources"]:
        db.add(
            ArtifactSource(
                artifact_id=artifact.id,
                chunk_id=source.get("chunk_id"),
                filename=source.get("filename"),
                page_number=source.get("page_number"),
                score=source.get("score"),
            )
        )
    db.commit()

    logger.info(
        "Artefacto '%s' generado para el estudiante '%s' en el entorno '%s' con %d fuente(s)",
        artifact_type.value,
        current_user.id,
        payload.environment_id,
        len(result["sources"]),
    )

    return ArtifactResponse(
        id=artifact.id,
        artifact_type=artifact.artifact_type.value,
        format=artifact.format.value,
        topic=artifact.topic,
        content=artifact.content,
        sources=[ArtifactSourceCitation(**source) for source in result["sources"]],
        suggestions=result.get("suggestions") or [],
        created_at=artifact.created_at,
    )


@router.get("", response_model=ArtifactListResponse)
def list_artifacts(
    environment_id: str = Query(...),
    current_user: User = Depends(RBACMiddleware(UserRole.student)),
    db: Session = Depends(get_db),
):
    artifacts = (
        db.query(Artifact)
        .filter(
            Artifact.student_id == current_user.id,
            Artifact.environment_id == environment_id,
            # Solo los vigentes: los retirados siguen en la base, fuera de la vista.
            Artifact.retired_at.is_(None),
        )
        .order_by(Artifact.created_at.desc())
        .all()
    )

    counts: dict[str, int] = {}
    if artifacts:
        rows = (
            db.query(ArtifactSource.artifact_id, func.count(ArtifactSource.id))
            .filter(ArtifactSource.artifact_id.in_([a.id for a in artifacts]))
            .group_by(ArtifactSource.artifact_id)
            .all()
        )
        counts = {artifact_id: total for artifact_id, total in rows}

    return ArtifactListResponse(
        artifacts=[
            ArtifactSummary(
                id=artifact.id,
                artifact_type=artifact.artifact_type.value,
                format=artifact.format.value,
                topic=artifact.topic or "",
                created_at=artifact.created_at,
                source_count=counts.get(artifact.id, 0),
            )
            for artifact in artifacts
        ]
    )


@router.get("/suggestion", response_model=ArtifactSuggestion)
def artifact_suggestion(
    environment_id: str = Query(...),
    current_user: User = Depends(RBACMiddleware(UserRole.student)),
    db: Session = Depends(get_db),
):
    """Decide si el sistema tiene motivo para proponer un artefacto.

    La senal es el trabajo real ya registrado: cuantas respuestas del asistente se
    apoyaron en el mismo documento del corpus dentro de la sesion activa. No hay
    llamada al LLM ni heuristica opaca -- si el sistema propone, puede decir
    exactamente por que.
    """
    session = _active_session(db, current_user.id, environment_id)
    if not session:
        return ArtifactSuggestion(should_propose=False)

    # Documentos citados en las respuestas de ESTA sesion, de mas a menos citado.
    citados = (
        db.query(ConversationSource.filename, func.count(ConversationSource.id).label("total"))
        .join(Conversation, ConversationSource.conversation_id == Conversation.id)
        .filter(
            Conversation.session_id == session.id,
            ConversationSource.filename.isnot(None),
        )
        .group_by(ConversationSource.filename)
        .order_by(func.count(ConversationSource.id).desc())
        .all()
    )
    if not citados:
        return ArtifactSuggestion(should_propose=False)

    # Titulos ya cubiertos por un artefacto del estudiante en este entorno: si ya
    # lo tiene, proponerselo otra vez es ruido.
    existentes = {
        (row.topic or "").strip().lower()
        for row in db.query(Artifact.topic)
        .filter(
            Artifact.student_id == current_user.id,
            Artifact.environment_id == environment_id,
            Artifact.retired_at.is_(None),
        )
        .all()
    }

    for filename, total in citados:
        if total < MIN_CITATIONS_TO_PROPOSE:
            break  # vienen ordenados: si este no llega, ninguno de los siguientes tampoco
        preguntas = _questions_about(db, session.id, filename)
        tema = preguntas[-1] if preguntas else None
        if not tema or tema.strip().lower() in existentes:
            continue
        # El motivo NO nombra el documento, deliberadamente. La propuesta cuenta citas
        # ya registradas (que apuntaron a este `filename`), pero la generacion vuelve a
        # buscar en el corpus con el texto de la pregunta y puede apoyarse en otro
        # documento. Nombrar el documento prometeria una fuente que el artefacto
        # luego puede no usar.
        #
        # PENDIENTE, la solucion de fondo: que la generacion priorice los fragmentos del
        # documento que motivo la propuesta (filtrando o dando peso por filename en el
        # retriever), para que el artefacto quede anclado a lo que el estudiante trabajo
        # de verdad y el motivo pueda volver a ser literal. Requiere tocar la
        # recuperacion, que hoy es comun con el chat.
        return ArtifactSuggestion(
            should_propose=True,
            topic=tema,
            focus=preguntas,
            anchor_filename=filename,
            artifact_type=SUGGESTED_TYPE.value,
            reason=(
                f"Has vuelto varias veces sobre este tema en esta sesión: {total} respuestas "
                "se apoyaron en el mismo material."
            ),
            citations=total,
        )

    return ArtifactSuggestion(should_propose=False)


@router.delete("/{artifact_id}", response_model=RetireResponse)
def retire_artifact(
    artifact_id: str,
    current_user: User = Depends(RBACMiddleware(UserRole.student)),
    db: Session = Depends(get_db),
):
    """Retira un artefacto del portafolio. NO lo borra.

    La fila y sus `artifact_sources` permanecen: la evaluacion del perfil se hara
    sobre los artefactos vigentes, y saber que fragmentos sustentaron cada uno es el
    unico dato del portafolio que no se puede reconstruir despues.
    """
    artifact = (
        db.query(Artifact)
        .filter(
            Artifact.id == artifact_id,
            Artifact.student_id == current_user.id,
            Artifact.retired_at.is_(None),
        )
        .first()
    )
    if not artifact:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artefacto no encontrado")

    artifact.retired_at = datetime.now(timezone.utc)
    db.commit()
    return RetireResponse(retired=1)


@router.delete("", response_model=RetireResponse)
def retire_all_artifacts(
    environment_id: str = Query(...),
    current_user: User = Depends(RBACMiddleware(UserRole.student)),
    db: Session = Depends(get_db),
):
    """Vacia el portafolio del estudiante en este entorno, retirando sin borrar."""
    ahora = datetime.now(timezone.utc)
    vigentes = (
        db.query(Artifact)
        .filter(
            Artifact.student_id == current_user.id,
            Artifact.environment_id == environment_id,
            Artifact.retired_at.is_(None),
        )
        .all()
    )
    for artifact in vigentes:
        artifact.retired_at = ahora
    db.commit()
    logger.info("Portafolio vaciado: %d artefactos retirados", len(vigentes))
    return RetireResponse(retired=len(vigentes))


@router.get("/{artifact_id}", response_model=ArtifactResponse)
def get_artifact(
    artifact_id: str,
    current_user: User = Depends(RBACMiddleware(UserRole.student)),
    db: Session = Depends(get_db),
):
    # El filtro por student_id es lo que impide que un estudiante lea el
    # artefacto de otro conociendo su id (mismo criterio de aislamiento que CP-5).
    artifact = (
        db.query(Artifact)
        .filter(
            Artifact.id == artifact_id,
            Artifact.student_id == current_user.id,
            # Un artefacto retirado sale de la vista tambien por su enlace directo.
            Artifact.retired_at.is_(None),
        )
        .first()
    )
    if not artifact:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El artefacto no existe")

    sources = db.query(ArtifactSource).filter(ArtifactSource.artifact_id == artifact.id).all()

    return ArtifactResponse(
        id=artifact.id,
        artifact_type=artifact.artifact_type.value,
        format=artifact.format.value,
        topic=artifact.topic or "",
        content=artifact.content,
        sources=[
            ArtifactSourceCitation(
                chunk_id=row.chunk_id,
                filename=row.filename,
                page_number=row.page_number,
                score=row.score,
            )
            for row in sources
        ],
        suggestions=[t for t in (artifact.suggestions or "").splitlines() if t.strip()],
        created_at=artifact.created_at,
    )
