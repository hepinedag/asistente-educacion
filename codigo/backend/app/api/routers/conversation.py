import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rbac import RBACMiddleware
from app.db.session import get_db
from app.models.conversation import Conversation, Speaker
from app.models.conversation_source import ConversationSource
from app.models.corpus_metadata import CorpusIndexStatus, CorpusMetadata
from app.models.learning_session import LearningSession, SessionStatus
from app.models.user import User, UserRole
from app.schemas.conversation import (
    ConversationHistoryResponse,
    HistoryMessage,
    LearningProgressResponse,
    MessageRequest,
    MessageResponse,
    ProgressDocument,
    SourceCitation,
    WelcomeResponse,
)
from app.services.conversation_orchestrator import ConversationOrchestrator, ConversationOrchestratorError
from app.services.embeddings.embedding_client import EmbeddingServiceClient
from app.services.llm.factory import get_llm_client
from app.services.prompt_builder import PromptBuilder
from app.services.document_titles import humanize_filename
from app.services.reranking.reranker_client import RerankerServiceClient
from app.services.response_post_processor import ResponsePostProcessor
from app.services.welcome_narrative_engine import WelcomeNarrativeEngine, WelcomeNarrativeEngineError
from pipeline.semantic_retriever import SemanticRetriever
from pipeline.semantic_validator import DEFAULT_RELEVANCE_THRESHOLD, SemanticValidator
from pipeline.vector_index_manager import VectorIndexManager

logger = logging.getLogger(__name__)
router = APIRouter()

# Cada proveedor de reranking produce scores en una escala distinta (ver semantic_validator.py).
# Umbral de fallback (0.5) calibrado para similitud coseno, usado cuando el reranker falla.
RERANKER_THRESHOLDS = {
    "cohere": 0.002,
    "cross-encoder": -4.0,
}

# Criterio CT-5: "el contexto recuperado incluye correctamente
# los ultimos 5 intercambios". Un intercambio = 1 mensaje del estudiante + 1 del sistema.
MAX_HISTORY_EXCHANGES = 5


def _build_orchestrator() -> ConversationOrchestrator:
    embedding_client = EmbeddingServiceClient(base_url=settings.embedding_service_url)
    vector_index_manager = VectorIndexManager(host=settings.chroma_host, port=settings.chroma_port)
    semantic_retriever = SemanticRetriever(embedding_client, vector_index_manager)
    prompt_builder = PromptBuilder()
    llm_client = get_llm_client()
    response_post_processor = ResponsePostProcessor()
    reranker = RerankerServiceClient(base_url=settings.embedding_service_url)
    reranker_threshold = RERANKER_THRESHOLDS.get(settings.reranker_provider, DEFAULT_RELEVANCE_THRESHOLD)
    semantic_validator = SemanticValidator(relevance_threshold=reranker_threshold)
    # fallback_validator usa el umbral original de similitud coseno (0.5) para cuando el
    # reranker falla y los chunks conservan su score de coseno, no de rerank.
    fallback_validator = SemanticValidator(relevance_threshold=0.5)
    return ConversationOrchestrator(
        semantic_retriever,
        semantic_validator,
        prompt_builder,
        llm_client,
        response_post_processor,
        reranker,
        fallback_validator,
    )


def _get_or_create_session(db: Session, student_id: str, environment_id: str) -> LearningSession:
    session = (
        db.query(LearningSession)
        .filter(
            LearningSession.student_id == student_id,
            LearningSession.environment_id == environment_id,
            LearningSession.status == SessionStatus.active,
        )
        .order_by(LearningSession.started_at.desc())
        .first()
    )
    if session:
        return session

    session = LearningSession(student_id=student_id, environment_id=environment_id)
    db.add(session)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El entorno especificado no existe",
        ) from exc
    db.refresh(session)
    return session


def _get_recent_history(
    db: Session, session_id: str, max_exchanges: int = MAX_HISTORY_EXCHANGES
) -> list[dict]:
    # Se buscan los ultimos max_exchanges*2 mensajes (1 intercambio = student + system)
    # de ESTA sesion unicamente, en orden descendente, y se revierten a orden
    # cronologico para que el prompt los lea en la secuencia real de la conversacion.
    rows = (
        db.query(Conversation)
        .filter(Conversation.session_id == session_id)
        .order_by(Conversation.created_at.desc())
        .limit(max_exchanges * 2)
        .all()
    )
    rows.reverse()
    return [{"speaker": row.speaker.value, "text": row.message} for row in rows]


@router.post("/message", response_model=MessageResponse)
async def send_message(
    payload: MessageRequest,
    current_user: User = Depends(RBACMiddleware(UserRole.student)),
    db: Session = Depends(get_db),
):
    session = _get_or_create_session(db, current_user.id, payload.environment_id)

    # Se recupera el historial ANTES de persistir el mensaje nuevo del estudiante,
    # para que el "punto de retorno" refleje unicamente intercambios ya completados
    # (pregunta + respuesta), no la pregunta actual todavia sin responder.
    conversation_history = _get_recent_history(db, session.id)
    logger.info(
        "Punto de retorno inteligente: %d mensaje(s) de historial (%d intercambio(s)) "
        "inyectados para session=%s",
        len(conversation_history),
        len(conversation_history) // 2,
        session.id,
    )

    student_msg = Conversation(
        session_id=session.id,
        student_id=current_user.id,
        speaker=Speaker.student,
        message=payload.message,
    )
    db.add(student_msg)
    db.commit()
    db.refresh(student_msg)

    orchestrator = _build_orchestrator()

    try:
        result = await orchestrator.handle_message(
            payload.environment_id, current_user.id, payload.message, conversation_history
        )
    except ConversationOrchestratorError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    student_msg.below_threshold = result["below_threshold"]
    system_msg = Conversation(
        session_id=session.id,
        student_id=current_user.id,
        speaker=Speaker.system,
        message=result["answer"],
    )
    db.add(system_msg)
    db.commit()
    db.refresh(system_msg)

    # Las fuentes se persisten ligadas a la respuesta del sistema (no a la
    # pregunta) porque son las que sustentan esa respuesta.
    for source in result["sources"]:
        db.add(
            ConversationSource(
                conversation_id=system_msg.id,
                chunk_id=source.get("chunk_id"),
                filename=source.get("filename"),
                page_number=source.get("page_number"),
                score=source.get("score"),
            )
        )
    db.commit()

    return MessageResponse(
        answer=result["answer"],
        sources=result["sources"],
        below_threshold=result["below_threshold"],
        suggestions=result["suggestions"],
    )


@router.get("/history", response_model=ConversationHistoryResponse)
def conversation_history(
    environment_id: str = Query(...),
    current_user: User = Depends(RBACMiddleware(UserRole.student)),
    db: Session = Depends(get_db),
):
    session = (
        db.query(LearningSession)
        .filter(
            LearningSession.student_id == current_user.id,
            LearningSession.environment_id == environment_id,
            LearningSession.status == SessionStatus.active,
        )
        .order_by(LearningSession.started_at.desc())
        .first()
    )
    if not session:
        return ConversationHistoryResponse(messages=[])

    messages = (
        db.query(Conversation)
        .filter(Conversation.session_id == session.id)
        .order_by(Conversation.created_at.asc())
        .all()
    )

    # Las fuentes se guardan ligadas al mensaje del sistema
    # (ver ConversationSource en send_message) -- se recuperan aqui en un solo
    # query agrupado por conversation_id en vez de uno por mensaje.
    system_message_ids = [msg.id for msg in messages if msg.speaker == Speaker.system]
    sources_by_message: dict[str, list[SourceCitation]] = {}
    if system_message_ids:
        source_rows = (
            db.query(ConversationSource)
            .filter(ConversationSource.conversation_id.in_(system_message_ids))
            .all()
        )
        for row in source_rows:
            sources_by_message.setdefault(row.conversation_id, []).append(
                SourceCitation(
                    chunk_id=row.chunk_id,
                    filename=row.filename,
                    page_number=row.page_number,
                    score=row.score,
                )
            )

    return ConversationHistoryResponse(
        messages=[
            HistoryMessage(
                speaker=msg.speaker.value,
                text=msg.message,
                below_threshold=msg.below_threshold,
                created_at=msg.created_at,
                sources=sources_by_message.get(msg.id, []),
            )
            for msg in messages
        ]
    )


@router.get("/progress", response_model=LearningProgressResponse)
def conversation_progress(
    environment_id: str = Query(...),
    current_user: User = Depends(RBACMiddleware(UserRole.student)),
    db: Session = Depends(get_db),
):
    # "completado"/"activo"/"pendiente" se define por documentos del
    # corpus_metadata de este entorno ya CITADOS a este estudiante (via
    # ConversationSource, a traves de todas sus sesiones en este entorno, no
    # solo la activa) vs. los que aun no se le han citado. El mas reciente
    # citado es el "activo"; el resto de citados son "completados".
    corpus_rows = (
        db.query(CorpusMetadata)
        .filter(
            CorpusMetadata.environment_id == environment_id,
            CorpusMetadata.status == CorpusIndexStatus.indexado,
        )
        .order_by(CorpusMetadata.indexed_at.desc())
        .all()
    )
    corpus_by_filename: dict[str, CorpusMetadata] = {}
    for row in corpus_rows:
        corpus_by_filename.setdefault(row.filename, row)

    cited_rows = (
        db.query(ConversationSource.filename, func.max(ConversationSource.created_at).label("last_cited_at"))
        .join(Conversation, ConversationSource.conversation_id == Conversation.id)
        .join(LearningSession, Conversation.session_id == LearningSession.id)
        .filter(
            Conversation.student_id == current_user.id,
            LearningSession.environment_id == environment_id,
            ConversationSource.filename.isnot(None),
        )
        .group_by(ConversationSource.filename)
        .order_by(func.max(ConversationSource.created_at).desc())
        .all()
    )
    # Un documento que el docente elimino del corpus deja de ser un tema del
    # temario, aunque el estudiante lo haya trabajado: `conversation_sources` es
    # independiente de `corpus_metadata`, asi que sin este filtro seguia
    # apareciendo en "completados" y ademas con el nombre crudo del archivo, ya
    # que su fila deja de estar entre las indexadas. La cita historica no se
    # toca: sigue visible bajo la respuesta donde se hizo.
    eliminados = {
        row.filename
        for row in db.query(CorpusMetadata.filename)
        .filter(
            CorpusMetadata.environment_id == environment_id,
            CorpusMetadata.status == CorpusIndexStatus.eliminado,
        )
        .all()
    } - set(corpus_by_filename)

    cited_filenames = [row.filename for row in cited_rows if row.filename not in eliminados]

    def _to_progress_document(filename: str) -> ProgressDocument:
        corpus_row = corpus_by_filename.get(filename)
        visible_title = corpus_row.visible_title if corpus_row else None
        return ProgressDocument(
            filename=filename,
            visible_title=visible_title,
            display_title=visible_title or humanize_filename(filename),
        )

    active = _to_progress_document(cited_filenames[0]) if cited_filenames else None
    completed = [_to_progress_document(filename) for filename in cited_filenames[1:]]
    pending = [
        _to_progress_document(filename)
        for filename in corpus_by_filename
        if filename not in cited_filenames
    ]

    return LearningProgressResponse(active=active, completed=completed, pending=pending)


@router.get("/welcome", response_model=WelcomeResponse)
async def conversation_welcome(
    environment_id: str = Query(...),
    current_user: User = Depends(RBACMiddleware(UserRole.student)),
    db: Session = Depends(get_db),
):
    # Se busca la sesion mas reciente del estudiante en ESTE entorno, sin filtrar
    # por status: el objetivo es detectar si existe historial previo alguno, no
    # solo el de la sesion activa. El filtro por student_id + environment_id es
    # lo que garantiza que nunca se mezcle contexto de otro estudiante ni de otro
    # entorno (CP-5).
    session = (
        db.query(LearningSession)
        .filter(
            LearningSession.student_id == current_user.id,
            LearningSession.environment_id == environment_id,
        )
        .order_by(LearningSession.started_at.desc())
        .first()
    )

    messages: list[dict] = []
    if session:
        rows = (
            db.query(Conversation)
            .filter(Conversation.session_id == session.id)
            .order_by(Conversation.created_at.asc())
            .all()
        )
        messages = [{"speaker": row.speaker.value, "text": row.message} for row in rows]

    engine = WelcomeNarrativeEngine(get_llm_client())
    try:
        result = await engine.generate(messages)
    except WelcomeNarrativeEngineError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    return WelcomeResponse(message=result["message"], has_history=result["has_history"])
