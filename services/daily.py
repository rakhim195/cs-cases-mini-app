"""Daily login streak: escalating rewards with a 24h cooldown + 12h grace."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from models import DailyStreak, InventoryItem, User
from services import rng
from services.catalog import get_case

CLAIM_COOLDOWN = timedelta(hours=24)
STREAK_GRACE = timedelta(hours=12)  # claim window before the streak resets

# Day 1..7; after day 7 the cycle restarts at day 1.
DAILY_REWARDS: tuple[dict[str, Any], ...] = (
    {"day": 1, "type": "coins", "amount": 50.0, "label": "50 ₽"},
    {"day": 2, "type": "coins", "amount": 75.0, "label": "75 ₽"},
    {"day": 3, "type": "coins", "amount": 100.0, "label": "100 ₽"},
    {"day": 4, "type": "coins", "amount": 150.0, "label": "150 ₽"},
    {"day": 5, "type": "coins", "amount": 200.0, "label": "200 ₽"},
    {"day": 6, "type": "coins", "amount": 300.0, "label": "300 ₽"},
    {"day": 7, "type": "case", "case_id": "gloves_knives", "label": "Кейс с ножом"},
)


class DailyCooldownError(RuntimeError):
    """Claimed too soon; carries the moment the next claim unlocks."""

    def __init__(self, available_at: datetime) -> None:
        self.available_at = available_at
        super().__init__(f"daily bonus available at {available_at.isoformat()}")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def next_reward_day(streak: DailyStreak | None) -> int:
    """The day number the NEXT claim lands on (1..7)."""
    if streak is None:
        return 1
    return streak.current_streak % 7 + 1


async def daily_status(session: AsyncSession, user_id: int) -> dict[str, Any]:
    """Streak state for the daily-bonus modal."""
    from services.game import get_or_create_user

    user = await get_or_create_user(session, user_id)
    streak = await session.get(DailyStreak, user_id)
    now = _utcnow()
    can_claim = True
    next_claim_at: datetime | None = None
    if streak is not None:
        next_claim_at = _as_utc(streak.last_claimed_at) + CLAIM_COOLDOWN
        can_claim = now >= next_claim_at
    await session.commit()
    return {
        "streak": streak.current_streak if streak else 0,
        "day": next_reward_day(streak),
        "can_claim": can_claim,
        "next_claim_at": next_claim_at.isoformat() if next_claim_at else None,
        "rewards": [dict(r) for r in DAILY_REWARDS],
        "balance": user.balance,
    }


async def claim_daily(session: AsyncSession, user_id: int) -> dict[str, Any]:
    """Grant today's reward and advance (or reset) the streak."""
    from services.game import get_or_create_user

    user = await get_or_create_user(session, user_id)
    streak = await session.get(DailyStreak, user_id)
    now = _utcnow()

    if streak is not None:
        last = _as_utc(streak.last_claimed_at)
        available_at = last + CLAIM_COOLDOWN
        if now < available_at:
            raise DailyCooldownError(available_at)
        # Inside the 12h grace window the streak continues; past it, reset.
        if now - last <= CLAIM_COOLDOWN + STREAK_GRACE:
            streak.current_streak = streak.current_streak % 7 + 1
        else:
            streak.current_streak = 1
        streak.last_claimed_at = now
    else:
        streak = DailyStreak(
            user_id=user_id, last_claimed_at=now, current_streak=1
        )
        session.add(streak)

    reward = DAILY_REWARDS[streak.current_streak - 1]
    payload: dict[str, Any] = {
        "status": "ok",
        "day": streak.current_streak,
        "reward": dict(reward),
        "new_balance": None,
        "drop": None,
        "next_claim_at": (now + CLAIM_COOLDOWN).isoformat(),
    }

    if reward["type"] == "coins":
        user.balance = round(user.balance + float(reward["amount"]), 2)
        payload["new_balance"] = user.balance
    else:
        drop = await _grant_free_case(session, user, reward["case_id"])
        payload["drop"] = drop

    await session.commit()
    return payload


async def _grant_free_case(
    session: AsyncSession, user: User, case_id: str
) -> dict[str, Any]:
    """Open a paid case for free (day-7 jackpot) and return the drop payload."""
    case = get_case(case_id)
    pool_item = rng.weighted_pick(case.items)
    wear_name, wear_float = rng.roll_wear(
        pool_item.get("min_float", 0.0), pool_item.get("max_float", 1.0)
    )
    is_stat_trak = rng.roll_stat_trak()
    price = rng.compute_price(pool_item["base_price"], is_stat_trak)

    item = InventoryItem(
        user_id=user.id,
        skin_id=pool_item["skin_id"],
        case_id=case.id,
        name=pool_item["name"],
        rarity=pool_item["rarity"],
        wear=wear_name,
        is_stat_trak=is_stat_trak,
        price=price,
        is_sold=False,
    )
    session.add(item)
    user.cases_opened += 1
    await session.flush()
    return {
        "item_id": item.id,
        "skin_id": pool_item["skin_id"],
        "case_id": case.id,
        "name": pool_item["name"],
        "rarity": pool_item["rarity"],
        "wear": wear_name,
        "wear_float": wear_float,
        "is_stat_trak": is_stat_trak,
        "price": price,
        "base_price": pool_item["base_price"],
        "name_en": pool_item.get("name_en"),
        "image": pool_item.get("image"),
    }
