from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import distinct, func
from sqlalchemy.orm import Session

from app.core.rbac import RBACMiddleware
from app.db.session import get_db
from app.models.conversation import Conversation, Speaker
from app.models.conversation_source import ConversationSource
from app.models.corpus_metadata import CorpusIndexStatus, CorpusMetadata
from app.models.learning_session import LearningSession
from app.models.user import User, UserRole
from app.schemas.teacher import (
    AlertsData,
    BehaviorInsights,
    DocumentMetric,
    ExtendedMetrics,
    GeneralMetrics,
    InactiveStudent,
    PeakActivityHour,
    StudentActivity,
    StudentBehavior,
    TeacherDashboardResponse,
    UnsatisfiedQuery,
    WeeklyActivityPoint,
    WeeklyBelowThresholdPoint,
)
from app.services.document_titles import humanize_filename

# Umbrales de comportamiento: el estudiante que "profundiza" promedia mas de 5
# consultas por sesion, el "superficial" menos de 2. Entre ambos (2-5) no se
# clasifica: el rango intermedio no tiene etiqueta.
DEEP_STUDENT_THRESHOLD = 5
SUPERFICIAL_STUDENT_THRESHOLD = 2
TOP_DOCUMENTS_LIMIT = 5
TOP_QUESTIONS_PER_DOCUMENT = 3
QUESTION_TRUNCATE_LENGTH = 80
# Una sola semana no forma una tendencia -- se necesitan al menos 2
# semanas con consultas de estudiante para mostrar la evolucion del ratio.
MIN_WEEKS_FOR_TREND = 2

router = APIRouter()

# Alerta de desconexion: umbral propio, deliberadamente mas corto que la
# ventana de retencion de 7 dias -- es una alerta temprana para que el docente
# intervenga antes de que el estudiante pierda el hilo, no una medida de retencion.
INACTIVITY_ALERT_DAYS = 3


def _empty_extended_insights() -> tuple[ExtendedMetrics, BehaviorInsights]:
    return ExtendedMetrics(), BehaviorInsights()


def _truncate_question(question: str) -> str:
    if len(question) <= QUESTION_TRUNCATE_LENGTH:
        return question
    return question[:QUESTION_TRUNCATE_LENGTH] + "..."


def _top_cited_documents_with_questions(
    citation_counts: dict[str, int],
    question_counts_by_filename: dict[str, Counter[str]],
    corpus_by_filename: dict[str, CorpusMetadata],
) -> list[DocumentMetric]:
    documents = _document_metrics_from_counts(citation_counts, corpus_by_filename)
    for document in documents:
        counter = question_counts_by_filename.get(document.filename)
        if not counter:
            continue
        document.top_questions = [
            _truncate_question(question) for question, _ in counter.most_common(TOP_QUESTIONS_PER_DOCUMENT)
        ]
    return documents


def _document_metrics_from_counts(
    counts: dict[str, int], corpus_by_filename: dict[str, CorpusMetadata]
) -> list[DocumentMetric]:
    ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)[:TOP_DOCUMENTS_LIMIT]
    result = []
    for filename, count in ranked:
        corpus_row = corpus_by_filename.get(filename)
        visible_title = corpus_row.visible_title if corpus_row else None
        result.append(
            DocumentMetric(
                filename=filename,
                display_title=visible_title or humanize_filename(filename),
                count=count,
            )
        )
    return result


def _compute_extended_insights(
    db: Session, environment_id: str, students: list[User]
) -> tuple[ExtendedMetrics, BehaviorInsights]:
    student_ids = [s.id for s in students]
    student_map = {s.id: s for s in students}

    sessions = (
        db.query(LearningSession)
        .filter(
            LearningSession.environment_id == environment_id,
            LearningSession.student_id.in_(student_ids),
        )
        .all()
    )
    session_ids = [s.id for s in sessions]
    if not session_ids:
        return _empty_extended_insights()

    all_messages = (
        db.query(Conversation)
        .filter(Conversation.session_id.in_(session_ids))
        .order_by(Conversation.created_at.asc())
        .all()
    )
    if not all_messages:
        return _empty_extended_insights()

    student_messages = [m for m in all_messages if m.speaker == Speaker.student]

    system_message_ids = [m.id for m in all_messages if m.speaker == Speaker.system]
    source_rows = (
        db.query(ConversationSource).filter(ConversationSource.conversation_id.in_(system_message_ids)).all()
        if system_message_ids
        else []
    )
    sources_by_conversation_id: dict[str, list[ConversationSource]] = defaultdict(list)
    for row in source_rows:
        sources_by_conversation_id[row.conversation_id].append(row)

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

    # "Documentos con mas below_threshold" -- una respuesta below_threshold
    # no tiene fuentes propias (no se encontro nada). Se le atribuye al documento que
    # el ESTUDIANTE tenia mas reciente en su sesion justo antes de la pregunta sin
    # respuesta -- el tema que estaba explorando cuando encontro el vacio del corpus.
    # "Documentos que generan seguimiento" -- mismo documento citado en
    # dos respuestas de sistema consecutivas dentro de la misma sesion.
    below_threshold_counts: Counter[str] = Counter()
    followup_counts: Counter[str] = Counter()

    # "Temas mas consultados" -- conteo total de citas por documento, una
    # fila de conversation_sources por cada vez que ese documento fue citado en
    # una respuesta del sistema, sin distincion de below_threshold o seguimiento.
    citation_counts: Counter[str] = Counter(
        row.filename for row in source_rows if row.filename
    )

    messages_by_session: dict[str, list[Conversation]] = defaultdict(list)
    for message in all_messages:
        messages_by_session[message.session_id].append(message)

    # Pregunta del estudiante que antecede inmediatamente a
    # cada respuesta del sistema -- es la pregunta que disparo esa cita concreta.
    question_by_system_message_id: dict[str, str] = {}

    for session_messages in messages_by_session.values():
        last_cited_filename: str | None = None
        previous_system_filename: str | None = None
        last_student_message: str | None = None
        for message in session_messages:
            if message.speaker == Speaker.system:
                if last_student_message:
                    question_by_system_message_id[message.id] = last_student_message
                sources = sources_by_conversation_id.get(message.id, [])
                current_filename = sources[0].filename if sources else None
                if current_filename:
                    last_cited_filename = current_filename
                    if previous_system_filename == current_filename:
                        followup_counts[current_filename] += 1
                    previous_system_filename = current_filename
                else:
                    previous_system_filename = None
            elif message.speaker == Speaker.student:
                last_student_message = message.message
                if message.below_threshold and last_cited_filename:
                    below_threshold_counts[last_cited_filename] += 1

    # Agrupa las preguntas por documento citado -- cada fila
    # de conversation_sources hereda la pregunta de la respuesta del sistema a la
    # que pertenece, sin importar cuantos documentos distintos cite esa respuesta.
    question_counts_by_filename: dict[str, Counter[str]] = defaultdict(Counter)
    for row in source_rows:
        if not row.filename:
            continue
        question = question_by_system_message_id.get(row.conversation_id)
        if question:
            question_counts_by_filename[row.filename][question] += 1

    # Promedio de consultas (mensajes del estudiante) por estudiante registrado.
    avg_queries_per_student = round(len(student_messages) / len(student_ids), 1) if student_ids else None

    # Hora pico de actividad del grupo (hora UTC con mas mensajes, ambos hablantes).
    hour_counts = Counter(message.created_at.hour for message in all_messages if message.created_at)
    peak_activity_hour = None
    if hour_counts:
        peak_hour, peak_count = max(hour_counts.items(), key=lambda item: item[1])
        peak_activity_hour = PeakActivityHour(hour=peak_hour, message_count=peak_count)

    # Evolucion de actividad semanal (semana calendario ISO, lunes como inicio).
    weekly_counts: dict = defaultdict(int)
    for message in all_messages:
        if not message.created_at:
            continue
        week_start = message.created_at.date() - timedelta(days=message.created_at.weekday())
        weekly_counts[week_start] += 1
    weekly_activity = [
        WeeklyActivityPoint(week_start=week_start, message_count=count)
        for week_start, count in sorted(weekly_counts.items())
    ]

    # Evolucion semanal del ratio below_threshold -- solo consultas del
    # estudiante (below_threshold no aplica a respuestas del sistema), ratio =
    # below_threshold de la semana / total de consultas de esa misma semana.
    weekly_query_totals: dict = defaultdict(int)
    weekly_below_threshold_totals: dict = defaultdict(int)
    for message in student_messages:
        if not message.created_at:
            continue
        week_start = message.created_at.date() - timedelta(days=message.created_at.weekday())
        weekly_query_totals[week_start] += 1
        if message.below_threshold:
            weekly_below_threshold_totals[week_start] += 1

    weekly_below_threshold = (
        [
            WeeklyBelowThresholdPoint(
                week_start=week_start,
                ratio_pct=round(weekly_below_threshold_totals.get(week_start, 0) / total * 100, 1),
                total_queries=total,
                below_threshold_queries=weekly_below_threshold_totals.get(week_start, 0),
            )
            for week_start, total in sorted(weekly_query_totals.items())
        ]
        if len(weekly_query_totals) >= MIN_WEEKS_FOR_TREND
        else []
    )

    extended_metrics = ExtendedMetrics(
        avg_queries_per_student=avg_queries_per_student,
        top_below_threshold_documents=_document_metrics_from_counts(below_threshold_counts, corpus_by_filename),
        peak_activity_hour=peak_activity_hour,
        weekly_activity=weekly_activity,
        top_cited_documents=_top_cited_documents_with_questions(
            citation_counts, question_counts_by_filename, corpus_by_filename
        ),
        weekly_below_threshold=weekly_below_threshold,
    )

    # Consultas por sesion promedio por estudiante, solo para
    # estudiantes que ya tienen al menos una sesion (sin sesiones no se clasifican).
    sessions_per_student: Counter[str] = Counter(s.student_id for s in sessions)
    student_message_counts: Counter[str] = Counter(m.student_id for m in student_messages)

    deep_students = []
    superficial_students = []
    for student_id, session_count in sessions_per_student.items():
        if session_count == 0 or student_id not in student_map:
            continue
        avg_per_session = student_message_counts.get(student_id, 0) / session_count
        behavior = StudentBehavior(
            student_id=student_id,
            full_name=student_map[student_id].full_name,
            avg_queries_per_session=round(avg_per_session, 1),
        )
        if avg_per_session > DEEP_STUDENT_THRESHOLD:
            deep_students.append(behavior)
        elif avg_per_session < SUPERFICIAL_STUDENT_THRESHOLD:
            superficial_students.append(behavior)

    deep_students.sort(key=lambda b: b.avg_queries_per_session, reverse=True)
    superficial_students.sort(key=lambda b: b.avg_queries_per_session)

    behavior_insights = BehaviorInsights(
        deep_students=deep_students,
        superficial_students=superficial_students,
        followed_up_documents=_document_metrics_from_counts(followup_counts, corpus_by_filename),
    )

    return extended_metrics, behavior_insights


def _compute_corpus_coverage(db: Session, environment_id: str, student_ids: list[str]) -> dict[str, float]:
    # "% del corpus citado" -- documentos DISTINTOS que
    # ConversationSource ha citado alguna vez a este estudiante en este entorno, sobre
    # el total de documentos indexados del entorno. No mide cuanto pregunto, mide
    # cuanto del material disponible ya ha tocado.
    if not student_ids:
        return {}

    # count(DISTINCT filename), no count(id): un mismo documento puede tener varias
    # filas en corpus_metadata (reemplazos/reindexados) -- contar filas infla el
    # denominador y hace que el % de cobertura parezca artificialmente bajo.
    total_indexed_documents = (
        db.query(func.count(func.distinct(CorpusMetadata.filename)))
        .filter(
            CorpusMetadata.environment_id == environment_id,
            CorpusMetadata.status == CorpusIndexStatus.indexado,
        )
        .scalar()
        or 0
    )
    if total_indexed_documents == 0:
        return {student_id: 0.0 for student_id in student_ids}

    rows = (
        db.query(Conversation.student_id, ConversationSource.filename)
        .join(ConversationSource, ConversationSource.conversation_id == Conversation.id)
        .join(LearningSession, Conversation.session_id == LearningSession.id)
        .filter(
            LearningSession.environment_id == environment_id,
            Conversation.student_id.in_(student_ids),
        )
        .distinct()
        .all()
    )
    cited_filenames_by_student: dict[str, set[str]] = defaultdict(set)
    for student_id, filename in rows:
        if filename:
            cited_filenames_by_student[student_id].add(filename)

    return {
        student_id: round(len(cited_filenames_by_student.get(student_id, set())) / total_indexed_documents * 100, 1)
        for student_id in student_ids
    }


@router.get("/dashboard", response_model=TeacherDashboardResponse)
def teacher_dashboard(
    environment_id: str = Query(...),
    current_user: User = Depends(RBACMiddleware(UserRole.teacher, UserRole.admin)),
    db: Session = Depends(get_db),
):
    # El rol por si solo no basta -- sin esta verificacion, cualquier
    # docente podria pasar el environment_id de OTRO docente y ver sus metricas.
    # admin conserva acceso a cualquier entorno (rol de supervision transversal).
    if current_user.role == UserRole.teacher and current_user.environment_id != environment_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tiene permisos para ver el panel de este entorno",
        )

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    seven_days_ago = now - timedelta(days=7)
    inactivity_cutoff = now - timedelta(days=INACTIVITY_ALERT_DAYS)

    students = (
        db.query(User)
        .filter(User.role == UserRole.student, User.environment_id == environment_id)
        .all()
    )
    student_ids = [s.id for s in students]
    student_map = {s.id: s for s in students}

    if not student_ids:
        empty_metrics, empty_behavior = _empty_extended_insights()
        return TeacherDashboardResponse(
            metrics=GeneralMetrics(active_students=0, retention_pct=0.0, queries_today=0),
            student_activity=[],
            alerts=AlertsData(unsatisfied_queries=[], inactive_students=[]),
            extended_metrics=empty_metrics,
            behavior_insights=empty_behavior,
        )

    recent_sessions = (
        db.query(LearningSession)
        .filter(
            LearningSession.environment_id == environment_id,
            LearningSession.student_id.in_(student_ids),
            LearningSession.started_at >= seven_days_ago,
        )
        .all()
    )

    active_student_ids: set[str] = {s.student_id for s in recent_sessions}

    days_with_session: dict[str, set] = {}
    for s in recent_sessions:
        started = s.started_at
        if started is None:
            continue
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        days_with_session.setdefault(s.student_id, set()).add(started.date())

    queries_today = (
        db.query(func.count(Conversation.id))
        .filter(
            Conversation.speaker == Speaker.student,
            Conversation.created_at >= today_start,
            Conversation.student_id.in_(student_ids),
        )
        .scalar()
        or 0
    )

    total_ever_active = (
        db.query(func.count(distinct(LearningSession.student_id)))
        .filter(
            LearningSession.environment_id == environment_id,
            LearningSession.student_id.in_(student_ids),
        )
        .scalar()
        or 0
    )
    active_count = len(active_student_ids)
    retention_pct = round(active_count / total_ever_active * 100, 1) if total_ever_active > 0 else 0.0

    last_msg_subq = (
        db.query(
            Conversation.student_id,
            func.max(Conversation.created_at).label("max_ts"),
        )
        .filter(
            Conversation.speaker == Speaker.student,
            Conversation.student_id.in_(student_ids),
        )
        .group_by(Conversation.student_id)
        .subquery()
    )
    last_convs = (
        db.query(Conversation)
        .join(
            last_msg_subq,
            (Conversation.student_id == last_msg_subq.c.student_id)
            & (Conversation.created_at == last_msg_subq.c.max_ts),
        )
        .all()
    )
    last_messages: dict[str, str] = {c.student_id: c.message[:120] for c in last_convs}

    all_sessions = (
        db.query(LearningSession)
        .filter(
            LearningSession.environment_id == environment_id,
            LearningSession.student_id.in_(student_ids),
        )
        .all()
    )
    last_session_map: dict[str, datetime] = {}
    for s in all_sessions:
        started = s.started_at
        if started is None:
            continue
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        prev = last_session_map.get(s.student_id)
        if prev is None or started > prev:
            last_session_map[s.student_id] = started

    corpus_coverage_by_student = _compute_corpus_coverage(db, environment_id, student_ids)

    student_activity = [
        StudentActivity(
            student_id=s.id,
            full_name=s.full_name,
            last_topic=last_messages.get(s.id),
            last_session_at=last_session_map.get(s.id),
            days_with_session_7d=len(days_with_session.get(s.id, set())),
            progress_pct=round(len(days_with_session.get(s.id, set())) / 7 * 100, 1),
            corpus_coverage_pct=corpus_coverage_by_student.get(s.id, 0.0),
        )
        for s in students
    ]

    bad_convs = (
        db.query(Conversation)
        .filter(
            Conversation.student_id.in_(student_ids),
            Conversation.speaker == Speaker.student,
            Conversation.below_threshold.is_(True),
            Conversation.created_at >= seven_days_ago,
        )
        .order_by(Conversation.created_at.desc())
        .limit(20)
        .all()
    )
    unsatisfied = [
        UnsatisfiedQuery(
            student_name=(
                student_map[c.student_id].full_name
                if c.student_id in student_map
                else "Desconocido"
            ),
            message=c.message[:120],
            created_at=c.created_at,
        )
        for c in bad_convs
    ]

    inactive_students = []
    for s in students:
        last_session_at = last_session_map.get(s.id)
        if last_session_at is not None and last_session_at >= inactivity_cutoff:
            continue
        days_inactive = (now - last_session_at).days if last_session_at is not None else None
        inactive_students.append(InactiveStudent(full_name=s.full_name, days_inactive=days_inactive))

    extended_metrics, behavior_insights = _compute_extended_insights(db, environment_id, students)

    return TeacherDashboardResponse(
        metrics=GeneralMetrics(
            active_students=active_count,
            retention_pct=retention_pct,
            queries_today=queries_today,
        ),
        student_activity=student_activity,
        alerts=AlertsData(
            unsatisfied_queries=unsatisfied,
            inactive_students=inactive_students,
        ),
        extended_metrics=extended_metrics,
        behavior_insights=behavior_insights,
    )
