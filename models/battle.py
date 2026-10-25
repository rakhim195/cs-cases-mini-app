"""1v1 case battle models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, utcnow

BATTLE_WAITING = "waiting"
BATTLE_IN_PROGRESS = "in_progress"
BATTLE_FINISHED = "finished"

BOT_USER_ID = 0


class Battle(Base):
    """A 1v1 case-opening duel; the higher total drop value takes all."""

    __tablename__ = "battles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    creator_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    opponent_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    case_id: Mapped[str] = mapped_column(String(64), nullable=False)
    rounds: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=BATTLE_WAITING
    )
    winner_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_p1_value: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
    total_p2_value: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    def __repr__(self) -> str:
        return (
            f"Battle(id={self.id!r}, creator={self.creator_id!r}, "
            f"opponent={self.opponent_id!r}, case={self.case_id!r}, "
            f"status={self.status!r})"
        )


class BattleRound(Base):
    """One round of a battle: both players' drops (p2 fills on join)."""

    __tablename__ = "battle_rounds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    battle_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("battles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    p1_skin_id: Mapped[str] = mapped_column(String(64), nullable=False)
    p1_skin_price: Mapped[float] = mapped_column(Float, nullable=False)
    p1_wear: Mapped[str] = mapped_column(String(32), nullable=False, default="Factory New")
    p1_is_stat_trak: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    p2_skin_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    p2_skin_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    p2_wear: Mapped[str | None] = mapped_column(String(32), nullable=True)
    p2_is_stat_trak: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
