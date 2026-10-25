"""Aiogram dispatcher assembly."""

from __future__ import annotations

from aiogram import Dispatcher
from aiogram.filters import Command, CommandStart
from aiogram.types import Message


def build_dispatcher() -> Dispatcher:
    """Build the dispatcher with the Phase 1 command set."""
    dispatcher = Dispatcher(name="csgo_rng_bot")

    @dispatcher.message(CommandStart())
    async def handle_start(message: Message) -> None:
        await message.answer(
            "CS:GO Case Battle backend is online.\n"
            "The Mini App interface launches in the next phase — stay tuned."
        )

    @dispatcher.message(Command("health"))
    async def handle_health(message: Message) -> None:
        await message.answer("Backend status: ok (phase 1).")

    return dispatcher
