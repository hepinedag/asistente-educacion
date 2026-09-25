from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import artifacts, auth, conversation, corpus, environments, health, teacher
from app.core.config import settings
from app.db.base import Base
from app.db.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


def create_app() -> FastAPI:
    # /docs, /redoc y /openapi.json apagados a proposito: la vitrina
    # interactiva de la API no debe estar al alcance de nadie salvo de quien
    # mantiene el sistema. Se reactiva devolviendo estas rutas a su valor por
    # defecto si hiciera falta para mantenimiento.
    app = FastAPI(
        title="Asistente de Educacion API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, tags=["health"])
    app.include_router(auth.router, prefix="/auth", tags=["auth"])
    app.include_router(corpus.router, prefix="/corpus", tags=["corpus"])
    app.include_router(conversation.router, prefix="/conversation", tags=["conversation"])
    app.include_router(teacher.router, prefix="/teacher", tags=["teacher"])
    app.include_router(environments.router, prefix="/environments", tags=["environments"])
    app.include_router(artifacts.router, prefix="/artifacts", tags=["artifacts"])

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
