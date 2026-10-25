"""Telegram player profile model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, utcnow

STARTING_BALANCE = 1000.0
STARTING_FREE_SPINS = 25


class User(Base):
    """A Telegram user of the Mini App."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=False
    )
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str] = mapped_column(
        String(128), nullable=False, default=""
    )
    balance: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=STARTING_BALANCE,
        server_default=str(STARTING_BALANCE),
    )
    free_spins: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=STARTING_FREE_SPINS,
        server_default=str(STARTING_FREE_SPINS),
    )
    cases_opened: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    referrer_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, index=True
    )
    referral_balance: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0.0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    def __repr__(self) -> str:
        return (
            f"User(id={self.id!r}, username={self.username!r}, "
            f"balance={self.balance!r}, free_spins={self.free_spins!r})"
        )
