"""Application entrypoint: FastAPI service with supervised Telegram polling."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from bot.lifecycle import launch_bot, stop_bot_task
from core.config import settings
from core.database import dispose_engine, init_db
from core.logging import setup_logging
from routes.api import router as api_router

setup_logging(settings.log_level)
logger = logging.getLogger("app.main")

SERVICE_NAME = "csgo-rng-backend"
PHASE = 1


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "Starting service",
        extra={"event": "startup", "service": SERVICE_NAME, "phase": PHASE},
    )
    await init_db()
    app.state.bot_task = await launch_bot()
    try:
        yield
    finally:
        await stop_bot_task(app.state.bot_task)
        await dispose_engine()
        logger.info(
            "Service stopped",
            extra={"event": "shutdown", "service": SERVICE_NAME},
        )


app = FastAPI(
    title="Кейсик (Keysik) — CS:GO кейсы и апгрейды",
    description="Backend of the Keysik («Кейсик») CS:GO cases and upgrades Telegram Mini App.",
    version="0.4.0",
    lifespan=lifespan,
)

BASE_DIR = Path(__file__).resolve().parent

app.include_router(api_router)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    """Serve the Mini App single page."""
    return FileResponse(BASE_DIR / "templates" / "index.html")


@app.get("/health")
async def health() -> dict[str, str | int]:
    """Liveness probe."""
    return {"status": "ok", "phase": PHASE, "service": SERVICE_NAME}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=settings.port)
