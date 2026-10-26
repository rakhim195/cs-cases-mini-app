"""Referral dashboard: aggregated friend list and earnings."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Referral
from services.game import REFERRAL_PAYOUT_RATE


async def referral_dashboard(session: AsyncSession, user_id: int) -> dict[str, Any]:
    """Friends invited by the user plus totals, from the payout ledger."""
    rows = (
        (
            await session.execute(
                select(Referral)
                .where(Referral.referrer_id == user_id)
                .order_by(Referral.id.desc())
                .limit(200)
            )
        )
        .scalars()
        .all()
    )

    friends: dict[int, dict[str, Any]] = {}
    total_earned = 0.0
    for row in rows:
        payout = round(float(row.item_price) * REFERRAL_PAYOUT_RATE, 2)
        total_earned += payout
        entry = friends.setdefault(
            row.friend_id,
            {
                "user_id": row.friend_id,
                "name": row.friend_name or f"Игрок {row.friend_id}",
                "joined_at": (
                    row.created_at.isoformat() if row.created_at else None
                ),
                "brought": 0.0,
                "drops": 0,
            },
        )
        entry["brought"] = round(entry["brought"] + payout, 2)
        entry["drops"] += 1

    friend_list = sorted(
        friends.values(), key=lambda f: f["brought"], reverse=True
    )
    return {
        "friends": friend_list,
        "total_friends": len(friend_list),
        "total_earned": round(total_earned, 2),
        "payout_rate": REFERRAL_PAYOUT_RATE,
    }
