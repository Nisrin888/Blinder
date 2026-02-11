import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from db.database import init_db
from api.routes import sessions, documents, chat, models

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Blinder API")

    # Safety checks
    if not settings.blinder_master_key:
        logger.warning(
            "BLINDER_MASTER_KEY is not set! Vault encryption will fail. "
            "Generate one with: openssl rand -hex 32"
        )
    elif len(settings.blinder_master_key) < 32:
        logger.warning(
            "BLINDER_MASTER_KEY looks too short (%d chars). "
            "Use a 64-char hex string (256 bits).",
            len(settings.blinder_master_key),
        )

    await init_db()
    yield
    logger.info("Shutting down Blinder API")


app = FastAPI(
    title="Blinder — Legal AI",
    description="Privacy-preserving legal reasoning with local LLM",
    version="0.1.0",
    lifespan=lifespan,
)

cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Requested-With"],
)

app.include_router(sessions.router, prefix="/api/sessions", tags=["sessions"])
app.include_router(documents.router, prefix="/api/sessions", tags=["documents"])
app.include_router(chat.router, prefix="/api/sessions", tags=["chat"])
app.include_router(models.router, prefix="/api/models", tags=["models"])


@app.get("/api/health")
async def health():
    return {"status": "ok"}
