"""Referral activity ledger model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, utcnow


class Referral(Base):
    """An item unboxed by a referred friend, recorded in the referrer's ledger."""

    __tablename__ = "referrals"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    referrer_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    friend_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    friend_name: Mapped[str] = mapped_column(String(128), nullable=False)
    item_name: Mapped[str] = mapped_column(String(255), nullable=False)
    item_price: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0.0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    def __repr__(self) -> str:
        return (
            f"Referral(id={self.id!r}, referrer_id={self.referrer_id!r}, "
            f"friend_id={self.friend_id!r}, item_name={self.item_name!r}, "
            f"item_price={self.item_price!r})"
        )
