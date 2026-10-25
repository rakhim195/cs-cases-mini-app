"""Aiogram dispatcher assembly: /start entry point and Mini App launcher."""

from __future__ import annotations

import logging

from aiogram import Dispatcher
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    User as TgUser,
    WebAppInfo,
)

from core.config import settings
from core.database import SessionFactory
from services.game import get_or_create_user

logger = logging.getLogger("app.bot")

WEBAPP_BUTTON_TEXT = "🎮 Открыть Кейсы"

WELCOME_TEXT = (
    "🎯 <b>CS Case Battle</b> — арена скинов прямо в Telegram!\n\n"
    "🎁 При регистрации тебя ждёт <b>1 000 ₽</b> на баланс и "
    "бесплатный кейс каждые 24 часа.\n"
    "🔪 Выбивай ножи и перчатки, продавай скины и зови друзей — "
    "с каждого их дропа тебе <b>5%</b>.\n\n"
    "Жми кнопку и погнали! 🔥"
)

REFERRAL_NOTE = (
    "\n\n💛 Ты зашёл по ссылке друга — он теперь получает "
    "<b>5% с каждого твоего дропа</b>."
)


def _webapp_url(user_id: int) -> str | None:
    """Per-user Mini App URL, or None when no public base URL is configured."""
    if not settings.webapp_base_url:
        return None
    return f"{settings.webapp_base_url}?user_id={user_id}"


def _webapp_keyboard(user_id: int) -> InlineKeyboardMarkup | None:
    url = _webapp_url(user_id)
    if url is None:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=WEBAPP_BUTTON_TEXT, web_app=WebAppInfo(url=url))]
        ]
    )


async def _persist_user_and_referral(
    tg_user: TgUser, referrer_id: int | None
) -> bool:
    """Provision the player row and attach the referrer on first visit.

    Returns True when a referral link was newly applied.
    """
    applied = False
    async with SessionFactory() as session:
        user = await get_or_create_user(session, tg_user.id)
        user.first_name = (tg_user.first_name or "")[:128]
        user.username = (tg_user.username or "")[:64]
        if (
            referrer_id is not None
            and referrer_id != user.id
            and user.referrer_id is None
        ):
            user.referrer_id = referrer_id
            applied = True
        await session.commit()
    return applied


def _parse_referrer_payload(text: str | None) -> int | None:
    """Extract the referrer id from a `/start r<user_id>` deep link."""
    if not text:
        return None
    parts = text.split()
    if len(parts) < 2 or not parts[0].startswith("/start"):
        return None
    payload = parts[1]
    if not payload.startswith("r") or not payload[1:].isdigit():
        return None
    referrer_id = int(payload[1:])
    return referrer_id or None


def build_dispatcher() -> Dispatcher:
    """Build the dispatcher with the Mini App command set."""
    dispatcher = Dispatcher(name="csgo_rng_bot")

    @dispatcher.message(CommandStart())
    async def handle_start(message: Message) -> None:
        if message.from_user is None:
            return
        referrer_id = _parse_referrer_payload(message.text)
        try:
            referral_applied = await _persist_user_and_referral(
                message.from_user, referrer_id
            )
        except Exception:  # noqa: BLE001 -- a broken DB write must not block /start
            logger.exception("Failed to persist user/referral on /start")
            referral_applied = False

        text = WELCOME_TEXT + (REFERRAL_NOTE if referral_applied else "")
        keyboard = _webapp_keyboard(message.from_user.id)
        if keyboard is not None:
            await message.answer(text, reply_markup=keyboard)
        else:
            await message.answer(
                text + "\n\n⚠️ Mini App пока не настроена (WEBAPP_BASE_URL)."
            )

    @dispatcher.message(Command("health"))
    async def handle_health(message: Message) -> None:
        await message.answer("Backend status: ok ✅")

    return dispatcher


__all__ = ["WEBAPP_BUTTON_TEXT", "build_dispatcher"]
