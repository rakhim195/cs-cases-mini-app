"""Unboxed skin inventory model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, utcnow

RARITY_MIL_SPEC = "Mil-Spec"
RARITY_RESTRICTED = "Restricted"
RARITY_CLASSIFIED = "Classified"
RARITY_COVERT = "Covert"
RARITY_SPECIAL = "Special"
RARITIES: tuple[str, ...] = (
    RARITY_MIL_SPEC,
    RARITY_RESTRICTED,
    RARITY_CLASSIFIED,
    RARITY_COVERT,
    RARITY_SPECIAL,
)

WEAR_FACTORY_NEW = "Factory New"
WEAR_MINIMAL_WEAR = "Minimal Wear"
WEAR_FIELD_TESTED = "Field-Tested"
WEAR_WELL_WORN = "Well-Worn"
WEAR_BATTLE_SCARRED = "Battle-Scarred"
WEARS: tuple[str, ...] = (
    WEAR_FACTORY_NEW,
    WEAR_MINIMAL_WEAR,
    WEAR_FIELD_TESTED,
    WEAR_WELL_WORN,
    WEAR_BATTLE_SCARRED,
)


class InventoryItem(Base):
    """A skin unboxed from a case and owned by a user until sold."""

    __tablename__ = "inventory_items"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    skin_id: Mapped[str] = mapped_column(String(64), nullable=False)
    case_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    rarity: Mapped[str] = mapped_column(String(32), nullable=False)
    wear: Mapped[str] = mapped_column(String(32), nullable=False)
    is_stat_trak: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    price: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0.0"
    )
    is_sold: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    def __repr__(self) -> str:
        return (
            f"InventoryItem(id={self.id!r}, user_id={self.user_id!r}, "
            f"name={self.name!r}, rarity={self.rarity!r}, price={self.price!r})"
        )
