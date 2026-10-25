"""Application entrypoint: FastAPI service with supervised Telegram polling."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from bot.lifecycle import launch_bot, stop_bot_task
from core.config import settings
from core.database import dispose_engine, init_db
from core.logging import setup_logging

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
    title="CS:GO Case Battle & Upgrade RNG",
    description="Backend for the CS:GO case battle and upgrade Telegram Mini App.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict[str, str | int]:
    """Liveness probe."""
    return {"status": "ok", "phase": PHASE, "service": SERVICE_NAME}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=settings.port)
