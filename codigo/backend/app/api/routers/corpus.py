import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.rbac import RBACMiddleware
from app.db.session import get_db
from app.models.corpus_metadata import CorpusFileType, CorpusIndexStatus, CorpusMetadata
from app.models.corpus_version import CorpusVersion, CorpusVersionAction
from app.models.user import User, UserRole
from app.schemas.corpus import (
    BatchUploadItem,
    BatchUploadResponse,
    CorpusDocumentStatus,
    CorpusLastUpdatedResponse,
    CorpusStatusResponse,
    CorpusVersionEntry,
    CorpusVersionsResponse,
    DeleteBatchResponse,
    DeleteRequest,
    DeleteResponse,
    ReplaceResponse,
    TitleUpdateRequest,
    UploadResponse,
)
from app.services.embeddings.embedding_client import EmbeddingClientError, EmbeddingServiceClient
from pipeline.corpus_quality_validator import CorpusQualityValidator
from pipeline.document_ingester import DocumentIngester, DocumentIngestError
from pipeline.text_chunker import TextChunker
from pipeline.vector_index_manager import VectorIndexError, VectorIndexManager

logger = logging.getLogger(__name__)
router = APIRouter()

CORPUS_DIR = Path(settings.corpus_dir)

ALLOWED_EXTENSIONS = {
    ".pdf": CorpusFileType.pdf,
    ".docx": CorpusFileType.word,
    ".md": CorpusFileType.markdown,
}


def _resolve_file_type(filename: str | None) -> CorpusFileType:
    if not filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Solo se aceptan archivos PDF, DOCX o MD")

    file_type = ALLOWED_EXTENSIONS.get(Path(filename).suffix.lower())
    if file_type is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Solo se aceptan archivos PDF, DOCX o MD")

    return file_type


def _next_version_number(db: Session, corpus_metadata_id: str) -> int:
    last = (
        db.query(func.max(CorpusVersion.version_number))
        .filter(CorpusVersion.corpus_metadata_id == corpus_metadata_id)
        .scalar()
    )
    return (last or 0) + 1


async def _require_embedding_service() -> None:
    """Comprueba que el servicio de embeddings responde ANTES de tocar el indice.

    El servicio corre fuera de Docker y `iniciar_sistema.bat` lo levanta despues del
    backend: una reindexacion lanzada demasiado pronto fallaria documento a
    documento. Fallar aqui cuesta un mensaje; fallar despues cuesta el corpus.
    """
    client = EmbeddingServiceClient(base_url=settings.embedding_service_url)
    try:
        disponible = await client.health_check()
    except Exception:  # noqa: BLE001 -- cualquier fallo de contacto es indisponibilidad
        disponible = False
    if not disponible:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "El servicio de embeddings no responde en "
                f"{settings.embedding_service_url}. No se ha modificado nada del corpus. "
                "Levantalo y vuelve a intentarlo."
            ),
        )


def _registrar_error(db: Session, record: CorpusMetadata, exc: Exception) -> None:
    """Deja escrito el motivo del fallo, no solo que hubo uno."""
    record.status = CorpusIndexStatus.error
    record.error_message = f"{type(exc).__name__}: {exc}"[:1000]
    db.commit()
    logger.error("Fallo al indexar '%s': %s", record.filename, record.error_message)


async def _ingest_and_index(destination: Path, environment_id: str) -> list[str]:
    """Ejecuta el pipeline completo (ingesta -> chunking -> calidad -> embeddings -> indexado)
    para un unico documento. Usado tanto por la subida inicial como por el reemplazo, de forma
    que reemplazar un documento reindexa solo ese documento, no el corpus completo.

    Devuelve los identificadores de los fragmentos generados, no solo cuantos. El
    reemplazo los necesita para saber cuales de los anteriores quedaron huerfanos:
    preguntarselo al indice no sirve, porque despues de indexar conviven los viejos
    y los nuevos bajo el mismo nombre de archivo."""
    ingester = DocumentIngester(CORPUS_DIR)
    pages = [page.to_dict() for page in ingester.ingest_file(destination)]

    chunker = TextChunker()
    chunks = chunker.chunk_texts(pages)

    quality_validator = CorpusQualityValidator()
    chunks = quality_validator.validate(chunks)["chunks"]

    embedding_client = EmbeddingServiceClient(base_url=settings.embedding_service_url)
    embedded_chunks = await embedding_client.embed_chunks(chunks)

    # Un documento que no produce ni un fragmento no esta indexado: no responde a
    # nada. Guardarlo como 'indexado' con chunk_count=0 lo esconderia -- el caso
    # realista es un PDF escaneado sin capa de texto, y con carga multiple pasaria
    # inadvertido entre los demas.
    if not embedded_chunks:
        raise DocumentIngestError(
            f"'{destination.name}' no produjo ningun fragmento indexable: "
            "puede ser un PDF sin capa de texto (escaneado) o sin contenido util."
        )

    index_manager = VectorIndexManager(host=settings.chroma_host, port=settings.chroma_port)
    index_manager.index_chunks(environment_id, embedded_chunks)
    return [chunk["chunk_id"] for chunk in embedded_chunks]


@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    environment_id: str = Form(...),
    file: UploadFile = File(...),
    visible_title: str | None = Form(None),
    current_user: User = Depends(RBACMiddleware(UserRole.teacher, UserRole.admin)),
    db: Session = Depends(get_db),
):
    """Sube un documento. Un solo comportamiento, el mismo que la carga multiple.

    Antes creaba SIEMPRE una fila nueva, asi que subir dos veces el mismo archivo
    producia dos documentos. Ahora delega en `_procesar_uno`, que trata el archivo
    ya registrado como reemplazo con su numero de version. Es ademas lo unico
    compatible con el indice unico sobre (environment_id, filename).
    """
    _resolve_file_type(file.filename)
    await _require_embedding_service()
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)

    item = await _procesar_uno(db, environment_id, file, current_user.id)
    if not item.ok:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=item.error)

    trimmed_title = visible_title.strip() if visible_title else None
    if trimmed_title:
        record = db.query(CorpusMetadata).filter(CorpusMetadata.id == item.document_id).first()
        record.visible_title = trimmed_title
        db.commit()

    return UploadResponse(
        document_id=item.document_id,
        filename=item.filename,
        visible_title=trimmed_title,
        chunks_created=item.chunks_created or 0,
    )


MAX_BATCH_FILES = 30


async def _procesar_uno(
    db: Session,
    environment_id: str,
    file: UploadFile,
    user_id: str,
) -> BatchUploadItem:
    """Procesa un archivo dentro de una carga multiple.

    Si el documento YA esta registrado en el entorno se trata como reemplazo, con
    su numero de version, y no como documento nuevo. Sin esa regla, cargar dos
    veces la misma carpeta duplicaria el corpus entero.
    """
    nombre = file.filename or "<sin nombre>"
    try:
        file_type = _resolve_file_type(file.filename)
    except HTTPException as exc:
        return BatchUploadItem(filename=nombre, ok=False, error=exc.detail)

    destination = CORPUS_DIR / file.filename
    try:
        destination.write_bytes(await file.read())
    except OSError as exc:
        return BatchUploadItem(filename=nombre, ok=False, error=f"No se pudo guardar el archivo: {exc}")

    record = (
        db.query(CorpusMetadata)
        .filter(
            CorpusMetadata.environment_id == environment_id,
            CorpusMetadata.filename == file.filename,
            CorpusMetadata.status != CorpusIndexStatus.eliminado,
        )
        .order_by(CorpusMetadata.uploaded_at.desc())
        .first()
    )
    es_reemplazo = record is not None

    index_manager = VectorIndexManager(host=settings.chroma_host, port=settings.chroma_port)
    ids_previos: set[str] = set()
    if es_reemplazo:
        record.status = CorpusIndexStatus.procesando
        db.commit()
        try:
            ids_previos = set(index_manager.ids_by_filename(environment_id, file.filename))
        except VectorIndexError as exc:
            _registrar_error(db, record, exc)
            return BatchUploadItem(filename=nombre, ok=False, error=str(exc))
    else:
        record = CorpusMetadata(
            environment_id=environment_id,
            filename=file.filename,
            file_type=file_type,
            status=CorpusIndexStatus.procesando,
        )
        db.add(record)
        db.commit()
        db.refresh(record)

    try:
        ids_nuevos = await _ingest_and_index(destination, environment_id)
        # Mismo criterio que en replace_document: los huerfanos se calculan contra
        # los ids que la ingesta acaba de producir, no contra el indice.
        huerfanos = sorted(ids_previos - set(ids_nuevos))
        if huerfanos:
            index_manager.delete_by_ids(environment_id, huerfanos)
    except (DocumentIngestError, EmbeddingClientError, VectorIndexError) as exc:
        _registrar_error(db, record, exc)
        return BatchUploadItem(filename=nombre, ok=False, document_id=record.id, error=str(exc))

    record.file_type = file_type
    record.status = CorpusIndexStatus.indexado
    record.error_message = None
    record.chunk_count = len(ids_nuevos)
    record.indexed_at = datetime.now(timezone.utc)
    db.commit()

    version_number = _next_version_number(db, record.id)
    accion = CorpusVersionAction.update if es_reemplazo else CorpusVersionAction.add
    db.add(
        CorpusVersion(
            corpus_metadata_id=record.id,
            version_number=version_number,
            action=accion,
            created_by=user_id,
            chunk_count=len(ids_nuevos),
            notes=(
                f"Carga multiple: documento '{file.filename}' "
                + ("reemplazado." if es_reemplazo else "indexado por primera vez.")
            ),
        )
    )
    db.commit()

    return BatchUploadItem(
        filename=nombre,
        ok=True,
        document_id=record.id,
        chunks_created=len(ids_nuevos),
        version_number=version_number,
        action=accion.value,
    )


@router.post(
    "/upload_batch",
    response_model=BatchUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_batch(
    environment_id: str = Form(...),
    files: list[UploadFile] = File(...),
    current_user: User = Depends(RBACMiddleware(UserRole.teacher, UserRole.admin)),
    db: Session = Depends(get_db),
):
    """Carga varios documentos en una sola operacion, uno a uno y en primer plano.

    Deliberadamente sincrona: un corpus de una asignatura se carga en menos de un
    minuto. Un
    sistema de tareas en segundo plano costaria mas que la funcionalidad entera y
    anadiria una superficie de fallo nueva.

    El fallo de un archivo NO detiene los demas: cada uno lleva su resultado.
    """
    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No se recibio ningun archivo")
    if len(files) > MAX_BATCH_FILES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximo {MAX_BATCH_FILES} archivos por operacion; se recibieron {len(files)}",
        )

    # Una sola vez, al principio: si el servicio no responde no se toca nada.
    await _require_embedding_service()
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)

    resultados = [await _procesar_uno(db, environment_id, f, current_user.id) for f in files]
    indexados = sum(1 for r in resultados if r.ok)
    logger.info("Carga multiple: %d de %d indexados", indexados, len(resultados))

    return BatchUploadResponse(
        results=resultados,
        total=len(resultados),
        indexed=indexados,
        failed=len(resultados) - indexados,
    )


@router.put(
    "/document/{document_id}",
    response_model=ReplaceResponse,
)
async def replace_document(
    document_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(RBACMiddleware(UserRole.teacher, UserRole.admin)),
    db: Session = Depends(get_db),
):
    record = db.query(CorpusMetadata).filter(CorpusMetadata.id == document_id).first()
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Documento no encontrado")

    new_file_type = _resolve_file_type(file.filename)
    await _require_embedding_service()
    old_filename = record.filename

    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    destination = CORPUS_DIR / file.filename

    try:
        contents = await file.read()
        destination.write_bytes(contents)
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"No se pudo guardar el archivo: {exc}",
        ) from exc

    record.status = CorpusIndexStatus.procesando
    db.commit()

    # PRIMERO SE CONSTRUYE, DESPUES SE DESTRUYE. Borrar los fragmentos del
    # documento y solo entonces generar los nuevos dejaria, si algo falla en medio,
    # el documento en el indice con cero fragmentos y sin forma de recuperarlo
    # salvo volviendo a subirlo. Se anotan los ids viejos, se indexa lo nuevo -- que sobrescribe
    # por id, porque el identificador del fragmento es determinista -- y solo al final
    # se borran los que quedaron huerfanos. Si falla la ingesta, lo viejo sigue intacto.
    try:
        index_manager = VectorIndexManager(host=settings.chroma_host, port=settings.chroma_port)
        ids_previos = set(index_manager.ids_by_filename(record.environment_id, old_filename))

        ids_nuevos = await _ingest_and_index(destination, record.environment_id)
        chunks_created = len(ids_nuevos)

        # Contra los ids que la ingesta acaba de producir, NO contra los que el
        # indice devuelve por nombre de archivo: si el nombre no cambia, ahi
        # conviven los viejos y los nuevos y la resta saldria vacia.
        huerfanos = sorted(ids_previos - set(ids_nuevos))
        if huerfanos:
            index_manager.delete_by_ids(record.environment_id, huerfanos)
            logger.info(
                "Reemplazo de '%s': %d fragmentos nuevos, %d huerfanos eliminados",
                old_filename, chunks_created, len(huerfanos),
            )
    except (DocumentIngestError, EmbeddingClientError, VectorIndexError) as exc:
        _registrar_error(db, record, exc)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    record.filename = file.filename
    record.file_type = new_file_type
    record.status = CorpusIndexStatus.indexado
    record.error_message = None
    record.chunk_count = chunks_created
    record.indexed_at = datetime.now(timezone.utc)
    db.commit()

    version_number = _next_version_number(db, record.id)
    db.add(
        CorpusVersion(
            corpus_metadata_id=record.id,
            version_number=version_number,
            action=CorpusVersionAction.update,
            created_by=current_user.id,
            chunk_count=chunks_created,
            notes=f"Documento reemplazado: '{old_filename}' -> '{file.filename}'.",
        )
    )
    db.commit()

    return ReplaceResponse(
        document_id=record.id,
        filename=record.filename,
        chunks_created=chunks_created,
        version_number=version_number,
    )


def _eliminar(db: Session, record: CorpusMetadata, user_id: str, nota: str) -> DeleteResponse:
    """Saca un documento del indice y lo marca como eliminado, dejando version.

    El registro NO se borra y las citas historicas de `conversation_sources`
    tampoco: son evidencia de lo que el estudiante hizo de verdad. Lo que se
    destruye son los fragmentos, para que el documento deje de responder.
    """
    index_manager = VectorIndexManager(host=settings.chroma_host, port=settings.chroma_port)
    chunks_deleted = index_manager.delete_by_filename(record.environment_id, record.filename)

    record.status = CorpusIndexStatus.eliminado
    record.chunk_count = 0
    db.commit()

    version_number = _next_version_number(db, record.id)
    db.add(
        CorpusVersion(
            corpus_metadata_id=record.id,
            version_number=version_number,
            action=CorpusVersionAction.delete,
            created_by=user_id,
            chunk_count=0,
            notes=nota,
        )
    )
    db.commit()

    return DeleteResponse(
        document_id=record.id,
        filename=record.filename,
        chunks_deleted=chunks_deleted,
        version_number=version_number,
    )


@router.delete("/documents", response_model=DeleteBatchResponse)
def delete_documents(
    payload: DeleteRequest,
    current_user: User = Depends(RBACMiddleware(UserRole.teacher, UserRole.admin)),
    db: Session = Depends(get_db),
):
    """Depuracion parcial: elimina los documentos seleccionados."""
    if not payload.document_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No se recibio ningun documento")

    eliminados: list[DeleteResponse] = []
    no_encontrados: list[str] = []
    for document_id in payload.document_ids:
        record = (
            db.query(CorpusMetadata)
            .filter(
                CorpusMetadata.id == document_id,
                CorpusMetadata.status != CorpusIndexStatus.eliminado,
            )
            .first()
        )
        if not record:
            no_encontrados.append(document_id)
            continue
        try:
            eliminados.append(
                _eliminar(db, record, current_user.id, f"Documento '{record.filename}' eliminado por seleccion.")
            )
        except VectorIndexError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    return DeleteBatchResponse(
        deleted=eliminados,
        not_found=no_encontrados,
        total_chunks_deleted=sum(d.chunks_deleted for d in eliminados),
    )


@router.delete("/environment/{environment_id}", response_model=DeleteBatchResponse)
def delete_environment_corpus(
    environment_id: str,
    current_user: User = Depends(RBACMiddleware(UserRole.teacher, UserRole.admin)),
    db: Session = Depends(get_db),
):
    """Depuracion total: vacia el corpus del entorno.

    No hay papelera ni deshacer: fuera del indice es fuera. El historial de
    versiones queda, de modo que siempre se puede saber que hubo y cuando dejo
    de haberlo.
    """
    registros = (
        db.query(CorpusMetadata)
        .filter(
            CorpusMetadata.environment_id == environment_id,
            CorpusMetadata.status != CorpusIndexStatus.eliminado,
        )
        .order_by(CorpusMetadata.filename)
        .all()
    )

    eliminados: list[DeleteResponse] = []
    for record in registros:
        try:
            eliminados.append(
                _eliminar(db, record, current_user.id, f"Documento '{record.filename}' eliminado al vaciar el entorno.")
            )
        except VectorIndexError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    # Vaciar el entorno elimina tambien la COLECCION, no solo sus vectores. La
    # dimension del vector es propiedad de la coleccion y se fija al crearla: si
    # sobrevive al vaciado, conserva la dimension del proveedor anterior y la
    # siguiente carga falla con "Collection expecting embedding with dimension de
    # 1024, got 384". Es lo que impedia pasar de modo nube a modo local: el corpus
    # quedaba vacio y sin manera de reindexarlo. Se hace al final, cuando los
    # registros ya estan marcados, y la siguiente carga la recrea.
    try:
        index_manager = VectorIndexManager(host=settings.chroma_host, port=settings.chroma_port)
        index_manager.delete_collection(environment_id)
    except VectorIndexError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    logger.info("Corpus del entorno '%s' vaciado: %d documentos", environment_id, len(eliminados))
    return DeleteBatchResponse(
        deleted=eliminados,
        not_found=[],
        total_chunks_deleted=sum(d.chunks_deleted for d in eliminados),
    )


@router.patch("/document/{document_id}", response_model=CorpusDocumentStatus)
def update_document_title(
    document_id: str,
    payload: TitleUpdateRequest,
    current_user: User = Depends(RBACMiddleware(UserRole.teacher, UserRole.admin)),
    db: Session = Depends(get_db),
):
    """El docente escribe o corrige el titulo tematico del documento.

    El titulo que el sistema propone al cargar sale del propio documento y es una
    SUGERENCIA, no una afirmacion: la autoridad sobre como se llama un tema es del
    docente. Vaciar el campo devuelve el documento a mostrarse por su nombre de
    archivo.
    """
    record = (
        db.query(CorpusMetadata)
        .filter(
            CorpusMetadata.id == document_id,
            CorpusMetadata.status != CorpusIndexStatus.eliminado,
        )
        .first()
    )
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Documento no encontrado")

    limpio = (payload.visible_title or "").strip()
    record.visible_title = limpio or None
    db.commit()

    return CorpusDocumentStatus(
        document_id=record.id,
        filename=record.filename,
        visible_title=record.visible_title,
        status=record.status.value,
        error_message=record.error_message,
        chunk_count=record.chunk_count,
        uploaded_at=record.uploaded_at,
        indexed_at=record.indexed_at,
    )


@router.delete(
    "/document/{document_id}",
    response_model=DeleteResponse,
)
def delete_document(
    document_id: str,
    current_user: User = Depends(RBACMiddleware(UserRole.teacher, UserRole.admin)),
    db: Session = Depends(get_db),
):
    record = db.query(CorpusMetadata).filter(CorpusMetadata.id == document_id).first()
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Documento no encontrado")

    try:
        index_manager = VectorIndexManager(host=settings.chroma_host, port=settings.chroma_port)
        chunks_deleted = index_manager.delete_by_filename(record.environment_id, record.filename)
    except VectorIndexError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    record.status = CorpusIndexStatus.eliminado
    record.chunk_count = 0
    db.commit()

    version_number = _next_version_number(db, record.id)
    db.add(
        CorpusVersion(
            corpus_metadata_id=record.id,
            version_number=version_number,
            action=CorpusVersionAction.delete,
            created_by=current_user.id,
            chunk_count=chunks_deleted,
            notes=f"Documento '{record.filename}' eliminado del corpus.",
        )
    )
    db.commit()

    return DeleteResponse(
        document_id=record.id,
        filename=record.filename,
        chunks_deleted=chunks_deleted,
        version_number=version_number,
    )


@router.get(
    "/versions",
    response_model=CorpusVersionsResponse,
    dependencies=[Depends(RBACMiddleware(UserRole.teacher, UserRole.admin))],
)
def get_corpus_versions(environment_id: str, db: Session = Depends(get_db)):
    rows = (
        db.query(CorpusVersion, CorpusMetadata)
        .join(CorpusMetadata, CorpusVersion.corpus_metadata_id == CorpusMetadata.id)
        .filter(CorpusMetadata.environment_id == environment_id)
        .order_by(CorpusVersion.created_at.desc())
        .all()
    )

    versions = [
        CorpusVersionEntry(
            version_id=version.id,
            corpus_metadata_id=version.corpus_metadata_id,
            filename=metadata.filename,
            version_number=version.version_number,
            action=version.action.value,
            created_at=version.created_at,
            created_by=version.created_by,
            chunk_count=version.chunk_count,
            notes=version.notes,
        )
        for version, metadata in rows
    ]

    return CorpusVersionsResponse(versions=versions)


@router.get("/last_updated", response_model=CorpusLastUpdatedResponse)
def get_corpus_last_updated(
    environment_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Endpoint deliberadamente abierto a cualquier rol autenticado (no solo
    # teacher/admin como /status o /versions): el estudiante lo consulta para
    # saber si el docente actualizo el corpus, y la respuesta no expone nada
    # sensible, solo un timestamp.
    last_updated_at = (
        db.query(func.max(CorpusVersion.created_at))
        .join(CorpusMetadata, CorpusVersion.corpus_metadata_id == CorpusMetadata.id)
        .filter(CorpusMetadata.environment_id == environment_id)
        .scalar()
    )
    return CorpusLastUpdatedResponse(last_updated_at=last_updated_at)


def _total_fragmentos(environment_id: str | None, records: list[CorpusMetadata]) -> int:
    """Fragmentos que el indice tiene DE VERDAD, no la suma de una columna.

    `chunk_count` guarda lo que produjo aquella operacion y nadie lo reconcilia
    nunca contra ChromaDB: sumandolo, el panel llego a declarar 1078 fragmentos
    cuando en el indice habia 328. Preguntarselo al indice hace que el panel
    informe lo que el estudiante experimenta.

    Si el indice no responde se cae a la suma de la columna: el panel debe seguir
    mostrando algo aunque ChromaDB este caido.
    """
    entornos = [environment_id] if environment_id else sorted({r.environment_id for r in records})
    try:
        manager = VectorIndexManager(host=settings.chroma_host, port=settings.chroma_port)
        return sum(manager.get_or_create_collection(entorno).count() for entorno in entornos)
    except Exception as exc:  # noqa: BLE001 -- el recuento nunca debe tumbar el panel
        logger.warning("No se pudo leer el total de fragmentos del indice: %s", exc)
        return sum(record.chunk_count or 0 for record in records)


@router.get(
    "/status",
    response_model=CorpusStatusResponse,
    dependencies=[Depends(RBACMiddleware(UserRole.teacher, UserRole.admin))],
)
def corpus_status(environment_id: str | None = None, db: Session = Depends(get_db)):
    # Los eliminados quedan fuera: ya no son el corpus.
    query = db.query(CorpusMetadata).filter(CorpusMetadata.status != CorpusIndexStatus.eliminado)
    if environment_id:
        query = query.filter(CorpusMetadata.environment_id == environment_id)

    records = query.order_by(CorpusMetadata.uploaded_at.desc()).all()

    documents = [
        CorpusDocumentStatus(
            document_id=record.id,
            filename=record.filename,
            visible_title=record.visible_title,
            status=record.status.value,
            error_message=record.error_message,
            chunk_count=record.chunk_count,
            uploaded_at=record.uploaded_at,
            indexed_at=record.indexed_at,
        )
        for record in records
    ]
    return CorpusStatusResponse(
        documents=documents,
        # Nombres de archivo distintos, no filas. Con el indice unico esto ya no
        # puede diferir, pero protege de cualquier dato heredado.
        total_documents=len({record.filename for record in records}),
        total_chunks=_total_fragmentos(environment_id, records),
    )
