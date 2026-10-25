"""Bot bootstrap, polling supervision and graceful shutdown."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError, TelegramUnauthorizedError

from bot.dispatcher import build_dispatcher
from core.config import settings

logger = logging.getLogger("app.bot")

TOKEN_VALIDATION_TIMEOUT_SECONDS = 10.0
NETWORK_RETRY_BACKOFF_START = 2.0
NETWORK_RETRY_BACKOFF_MAX = 60.0
POLLING_TASK_NAME = "telegram-bot-poller"


async def launch_bot() -> asyncio.Task | None:
    """Validate the bot token and spawn the detached polling task.

    Returns the polling task, or None when the bot cannot run (missing or
    rejected token, unreachable Telegram API). Never raises: the web server
    must stay operational regardless of the bot state.
    """
    if not settings.bot_token:
        logger.warning(
            "Telegram bot disabled: BOT_TOKEN is not set; "
            "continuing without the bot",
            extra={"event": "bot_disabled", "reason": "missing_token"},
        )
        return None

    bot: Bot | None = None
    try:
        bot = Bot(
            token=settings.bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        me = await asyncio.wait_for(
            bot.get_me(), timeout=TOKEN_VALIDATION_TIMEOUT_SECONDS
        )
        dispatcher = build_dispatcher()
        task = asyncio.create_task(
            _poll_forever(bot, dispatcher), name=POLLING_TASK_NAME
        )
        logger.info(
            "Telegram bot polling started",
            extra={
                "event": "bot_started",
                "bot_id": me.id,
                "bot_username": me.username,
            },
        )
        return task
    except TelegramUnauthorizedError as exc:
        logger.warning(
            "Telegram bot disabled: Telegram rejected BOT_TOKEN as invalid",
            extra={
                "event": "bot_disabled",
                "reason": "unauthorized",
                "detail": str(exc),
            },
        )
    except TelegramNetworkError as exc:
        logger.warning(
            "Telegram bot disabled: Telegram API unreachable during "
            "token validation",
            extra={
                "event": "bot_disabled",
                "reason": "network",
                "detail": str(exc),
            },
        )
    except TimeoutError:
        logger.warning(
            "Telegram bot disabled: timed out validating BOT_TOKEN against "
            "the Telegram API",
            extra={"event": "bot_disabled", "reason": "validation_timeout"},
        )
    except Exception as exc:  # noqa: BLE001 -- the web server must survive any bot failure
        logger.warning(
            "Telegram bot disabled: unexpected error during bot startup",
            extra={
                "event": "bot_disabled",
                "reason": "startup_error",
                "detail": repr(exc),
            },
        )

    if bot is not None:
        await bot.session.close()
    return None


async def _poll_forever(bot: Bot, dispatcher: Dispatcher) -> None:
    """Run polling with bounded exponential backoff on transient network errors."""
    backoff = NETWORK_RETRY_BACKOFF_START
    try:
        while True:
            try:
                await dispatcher.start_polling(bot, handle_signals=False)
                return
            except TelegramNetworkError as exc:
                logger.warning(
                    "Telegram polling hit a network error; retrying",
                    extra={
                        "event": "bot_network_retry",
                        "delay_seconds": backoff,
                        "detail": str(exc),
                    },
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, NETWORK_RETRY_BACKOFF_MAX)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Telegram polling stopped: unrecoverable error")
                return
    finally:
        await bot.session.close()
        logger.info(
            "Telegram bot polling stopped", extra={"event": "bot_stopped"}
        )


async def stop_bot_task(task: asyncio.Task | None) -> None:
    """Cancel the polling task and wait for it to finish shutting down."""
    if task is None:
        return
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
