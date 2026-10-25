"""Daily login streak model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, utcnow


class DailyStreak(Base):
    """One row per player tracking their daily-bonus streak."""

    __tablename__ = "daily_streaks"

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        autoincrement=False,
    )
    last_claimed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    current_streak: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )

    def __repr__(self) -> str:
        return (
            f"DailyStreak(user_id={self.user_id!r}, "
            f"streak={self.current_streak!r}, "
            f"last={self.last_claimed_at!r})"
        )
