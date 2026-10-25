"""Bot bootstrap, polling supervision and graceful shutdown."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError, TelegramUnauthorizedError
from aiogram.types import (
    BotCommand,
    BotCommandScopeDefault,
    MenuButtonWebApp,
    WebAppInfo,
)

from bot.dispatcher import WEBAPP_BUTTON_TEXT, build_dispatcher
from core.config import settings

logger = logging.getLogger("app.bot")

TOKEN_VALIDATION_TIMEOUT_SECONDS = 10.0
NETWORK_RETRY_BACKOFF_START = 3.0
NETWORK_RETRY_BACKOFF_MAX = 15.0
# Tried in rotation on every supervisor cycle: direct first, then the known
# local proxies. The first candidate whose get_me succeeds starts polling;
# when it dies the supervisor moves on to the next one.
PROXY_CANDIDATES: tuple[str | None, ...] = (
    None,  # direct connection
    "socks5://127.0.0.1:1080",
    "http://127.0.0.1:10809",
)
POLLING_TASK_NAME = "telegram-bot-poller"


async def _configure_bot_profile(bot: Bot) -> None:
    """Register bot commands and the WebApp menu button (best effort)."""
    try:
        await bot.set_my_commands(
            [
                BotCommand(command="start", description="Открыть кейсы 🎁"),
                BotCommand(command="health", description="Статус сервиса"),
            ],
            scope=BotCommandScopeDefault(),
        )
    except Exception as exc:  # noqa: BLE001 -- cosmetic setup must not kill the bot
        logger.warning(
            "Could not set bot commands",
            extra={"event": "bot_commands_failed", "detail": repr(exc)},
        )
    if settings.webapp_base_url:
        try:
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text=WEBAPP_BUTTON_TEXT,
                    web_app=WebAppInfo(url=settings.webapp_base_url),
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Could not set the WebApp menu button",
                extra={"event": "bot_menu_failed", "detail": repr(exc)},
            )
    else:
        logger.warning(
            "WEBAPP_BASE_URL is not set: /start will reply without the "
            "Mini App button",
            extra={"event": "webapp_url_missing"},
        )


SUPERVISOR_TASK_NAME = "telegram-bot-supervisor"


async def launch_bot() -> asyncio.Task | None:
    """Spawn the detached bot supervisor and return its task.

    The supervisor validates the token, configures the bot profile and runs
    polling; on network-level failures (a flapping local proxy, Telegram
    outages) it retries forever with capped backoff. Returns None only when
    the bot cannot run at all (missing token). Never blocks app startup and
    never raises: the web server must stay operational regardless.
    """
    if not settings.bot_token:
        logger.warning(
            "Telegram bot disabled: BOT_TOKEN is not set; "
            "continuing without the bot",
            extra={"event": "bot_disabled", "reason": "missing_token"},
        )
        return None
    return asyncio.create_task(_launch_forever(), name=SUPERVISOR_TASK_NAME)


async def _launch_forever() -> None:
    """Run the bot forever, self-healing across proxy/network outages.

    Each cycle tries the next connection candidate (direct, then local
    proxies); the retry delay is short and capped so the bot never sits
    idle for a minute waiting to re-check a recovered proxy.
    """
    candidates: tuple[str | None, ...] = PROXY_CANDIDATES
    if settings.telegram_proxy:
        # An explicitly configured proxy wins the first slot.
        candidates = (settings.telegram_proxy,) + tuple(
            c for c in PROXY_CANDIDATES if c != settings.telegram_proxy
        )
    delay = NETWORK_RETRY_BACKOFF_START
    attempt = 0
    while True:
        attempt += 1
        proxy = candidates[(attempt - 1) % len(candidates)]
        bot: Bot | None = None
        try:
            session = None
            if proxy:
                session = AiohttpSession(proxy=proxy)
            bot = Bot(
                token=settings.bot_token,
                session=session,
                default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            )
            me = await asyncio.wait_for(
                bot.get_me(), timeout=TOKEN_VALIDATION_TIMEOUT_SECONDS
            )
            await _configure_bot_profile(bot)
            dispatcher = build_dispatcher()
            logger.info(
                "Telegram bot polling started",
                extra={
                    "event": "bot_started",
                    "bot_id": me.id,
                    "bot_username": me.username,
                    "startup_attempts": attempt,
                    "via": proxy or "direct",
                },
            )
            await _poll_forever(bot, dispatcher)
            # Polling gave up (unrecoverable error) — rebuild and retry with
            # a fresh session instead of leaving the bot dead.
            logger.warning(
                "Telegram polling ended; restarting with a fresh session",
                extra={"event": "bot_polling_restart"},
            )
        except TelegramUnauthorizedError as exc:
            logger.warning(
                "Telegram bot disabled: Telegram rejected BOT_TOKEN as invalid",
                extra={
                    "event": "bot_disabled",
                    "reason": "unauthorized",
                    "detail": str(exc),
                },
            )
            await _close_quietly(bot)
            return
        except asyncio.CancelledError:
            await _close_quietly(bot)
            raise
        except Exception as exc:  # noqa: BLE001 -- the supervisor must keep retrying
            logger.warning(
                "Telegram bot startup failed; will retry",
                extra={
                    "event": "bot_startup_retry",
                    "attempt": attempt,
                    "via": proxy or "direct",
                    "delay_seconds": delay,
                    "detail": repr(exc),
                },
            )
        await _close_quietly(bot)
        await asyncio.sleep(delay)


async def _close_quietly(bot: Bot | None) -> None:
    if bot is None:
        return
    try:
        await bot.session.close()
    except Exception:  # noqa: BLE001 -- shutdown must never raise
        pass


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
