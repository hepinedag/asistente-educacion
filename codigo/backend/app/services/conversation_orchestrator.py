import logging

from app.services.llm.base import LLMClient
from app.services.prompt_builder import PromptBuilder
from app.services.reranking.reranker_client import RerankerClientError, RerankerServiceClient
from app.services.response_post_processor import ResponsePostProcessor
from pipeline.semantic_retriever import SemanticRetriever, SemanticRetrieverError
from pipeline.semantic_validator import SemanticValidator

logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 5
NO_INFORMATION_MESSAGE = "No encontre informacion suficiente en el corpus de este entorno para responder esa pregunta."


class ConversationOrchestratorError(Exception):
    pass


class ConversationOrchestrator:
    def __init__(
        self,
        semantic_retriever: SemanticRetriever,
        semantic_validator: SemanticValidator,
        prompt_builder: PromptBuilder,
        llm_client: LLMClient,
        response_post_processor: ResponsePostProcessor,
        reranker: RerankerServiceClient,
        fallback_validator: SemanticValidator,
        top_k: int = DEFAULT_TOP_K,
    ):
        self.semantic_retriever = semantic_retriever
        self.semantic_validator = semantic_validator
        self.prompt_builder = prompt_builder
        self.llm_client = llm_client
        self.response_post_processor = response_post_processor
        self.reranker = reranker
        self.fallback_validator = fallback_validator
        self.top_k = top_k

    async def handle_message(
        self,
        environment_id: str,
        user_id: str,
        message: str,
        conversation_history: list[dict] | None = None,
    ) -> dict:
        if not message or not message.strip():
            raise ConversationOrchestratorError("El mensaje no puede estar vacio")

        try:
            chunks = await self.semantic_retriever.retrieve(environment_id, message, top_k=self.top_k)
        except SemanticRetrieverError as exc:
            raise ConversationOrchestratorError(f"Error al recuperar contexto del corpus: {exc}") from exc

        reranked = False
        if chunks:
            try:
                chunks = await self.reranker.rerank(message, chunks)
                reranked = True
            except RerankerClientError as exc:
                logger.warning(
                    "ReRanker fallo, se continua con el orden de SemanticRetriever sin reordenar: %s", exc
                )

        # Los scores de chunks reordenados por Cohere Rerank y los scores de similitud coseno
        # (cuando el ReRanker falla y no se reordena) viven en escalas completamente distintas.
        # Usar el validador equivocado con cada escala deja pasar contenido irrelevante.
        validator = self.semantic_validator if reranked else self.fallback_validator
        validation = validator.validate(chunks)

        if validation["below_threshold"]:
            logger.info(
                "Sin contexto suficiente para el usuario '%s' en el entorno '%s'",
                user_id,
                environment_id,
            )
            return self.response_post_processor.process(NO_INFORMATION_MESSAGE, validation["chunks"], True)

        validated_chunks = validation["chunks"]

        try:
            prompt_messages = self.prompt_builder.build(message, validated_chunks, conversation_history)
        except ValueError as exc:
            raise ConversationOrchestratorError(f"No se pudo construir el prompt: {exc}") from exc

        try:
            answer = await self.llm_client.chat(prompt_messages)
        except Exception as exc:
            raise ConversationOrchestratorError(f"Error al generar la respuesta del LLM: {exc}") from exc

        return self.response_post_processor.process(answer, validated_chunks, False)
