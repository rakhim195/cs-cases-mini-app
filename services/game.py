"""Gameplay operations: user provisioning, case opening and item selling."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from collections.abc import Mapping
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import InventoryItem, Referral, User
from services import rng
from services.catalog import CaseNotFoundError, get_case, list_cases

# Tail after the winner (REEL_LENGTH - winner index) stays >= 25 items.
REEL_LENGTH = 101
REEL_WINNER_MIN_INDEX = 70
REEL_WINNER_MAX_INDEX = 75
NEAR_MISS_BUDGET_RARITIES = frozenset({"Mil-Spec", "Restricted"})
NEAR_MISS_ULTRA_RARITIES = frozenset({"Covert", "Special"})
REFERRAL_PAYOUT_RATE = 0.05


class CooldownError(Exception):
    """Daily free case is still on cooldown."""

    def __init__(self, available_at: datetime) -> None:
        self.available_at = available_at
        super().__init__(f"free case available at {available_at.isoformat()}")


class InsufficientFundsError(Exception):
    """User balance is below the case price."""

    def __init__(self, price: float) -> None:
        self.price = price
        super().__init__(f"insufficient funds: case costs {price}")


class ItemNotFoundError(LookupError):
    """Item id is unknown or belongs to another user."""


class ItemAlreadySoldError(RuntimeError):
    """Item has already been sold."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    """SQLite round-trips datetimes naive; they are stored as UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


async def get_or_create_user(session: AsyncSession, user_id: int) -> User:
    user = await session.get(User, user_id)
    if user is None:
        user = User(id=user_id, first_name="")
        session.add(user)
        await session.flush()
    return user


async def user_profile(session: AsyncSession, user_id: int) -> dict[str, Any]:
    """Profile payload for the header; provisions the user on first call."""
    user = await get_or_create_user(session, user_id)
    inventory_count = await session.scalar(
        select(func.count())
        .select_from(InventoryItem)
        .where(
            InventoryItem.user_id == user.id,
            InventoryItem.is_sold.is_(False),
        )
    )
    available_at: str | None = None
    if user.last_free_case_at is not None:
        for case in list_cases():
            if case.is_free and case.cooldown_hours:
                ready_at = _as_utc(user.last_free_case_at) + timedelta(
                    hours=case.cooldown_hours
                )
                if _utcnow() < ready_at:
                    available_at = ready_at.isoformat()
                break
    await session.commit()
    return {
        "id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        "balance": user.balance,
        "free_spins": user.free_spins,
        "cases_opened": user.cases_opened,
        "inventory_count": int(inventory_count or 0),
        "free_case_available_at": available_at,
    }


def _pool_display(
    item: Mapping[str, Any], case_id: str, **extra: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "skin_id": item["skin_id"],
        "name": item["name"],
        "rarity": item["rarity"],
        "base_price": item["base_price"],
        "case_id": case_id,
    }
    for key in ("name_en", "image", "min_float", "max_float"):
        if key in item:
            payload[key] = item[key]
    payload.update(extra)
    return payload


async def _pay_referrer(
    session: AsyncSession, friend: User, item_name: str, item_price: float
) -> float:
    """Credit 5% of a referred friend's drop to their referrer.

    Returns the payout amount (0.0 when there is no valid referrer).
    """
    referrer_id = friend.referrer_id
    if not referrer_id or referrer_id == friend.id:
        return 0.0
    referrer = await session.get(User, referrer_id)
    if referrer is None:
        return 0.0
    payout = round(float(item_price) * REFERRAL_PAYOUT_RATE, 2)
    if payout <= 0:
        return 0.0
    referrer.referral_balance = round(referrer.referral_balance + payout, 2)
    session.add(
        Referral(
            referrer_id=referrer.id,
            friend_id=friend.id,
            friend_name=(friend.first_name or friend.username or str(friend.id))[:128],
            item_name=item_name[:255],
            item_price=float(item_price),
        )
    )
    return payout


def _build_reel(
    case_items: tuple[Mapping[str, Any], ...],
    winner: Mapping[str, Any],
    case_id: str,
) -> tuple[list[dict[str, Any]], int]:
    """Assemble the decorative reel with the winner buried mid-strip.

    The winner lands at a random index in [70, 75] so the strip keeps
    scrolling well past the needle — no empty void after the stop. When the
    winner is a budget skin, an ultra-rare pool item is placed directly
    adjacent to it for the near-miss thrill.
    """
    winner_index = rng.uniform_int(
        REEL_WINNER_MIN_INDEX, REEL_WINNER_MAX_INDEX
    )
    reel = [
        _pool_display(rng.uniform_choice(case_items), case_id)
        for _ in range(REEL_LENGTH)
    ]

    near_miss_slot: int | None = None
    if winner["rarity"] in NEAR_MISS_BUDGET_RARITIES:
        ultra_pool = [
            item
            for item in case_items
            if item["rarity"] in NEAR_MISS_ULTRA_RARITIES
        ]
        if ultra_pool:
            # Land the tease just behind the winner: it slides past the
            # needle a heartbeat before the result card locks in.
            near_miss_slot = winner_index - 1
            reel[near_miss_slot] = _pool_display(
                rng.uniform_choice(ultra_pool), case_id
            )

    reel[winner_index] = winner
    return reel, winner_index


async def open_case(
    session: AsyncSession, user_id: int, case_id: str
) -> dict[str, Any]:
    """Charge (or cooldown-check), roll the drop and persist the result."""
    user = await get_or_create_user(session, user_id)
    case = get_case(case_id)
    now = _utcnow()

    if case.is_free:
        if case.cooldown_hours and user.last_free_case_at is not None:
            ready_at = _as_utc(user.last_free_case_at) + timedelta(
                hours=case.cooldown_hours
            )
            if now < ready_at:
                raise CooldownError(ready_at)
        user.last_free_case_at = now
    else:
        if user.balance < case.price:
            raise InsufficientFundsError(case.price)
        user.balance = round(user.balance - case.price, 2)

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

    display_name = ("StatTrak™ " if is_stat_trak else "") + pool_item["name"]
    referral_payout = await _pay_referrer(session, user, display_name, price)

    winner = _pool_display(
        pool_item,
        case.id,
        item_id=item.id,
        wear=wear_name,
        wear_float=wear_float,
        is_stat_trak=is_stat_trak,
        price=price,
    )
    reel, winner_index = _build_reel(case.items, winner, case.id)

    await session.commit()
    return {
        "winner": winner,
        "reel": reel,
        "winner_index": winner_index,
        "new_balance": user.balance,
        "referral_payout": referral_payout,
    }


async def sell_item(
    session: AsyncSession, user_id: int, item_id: int
) -> dict[str, Any]:
    """Mark an owned item as sold and credit its price to the balance."""
    item = await session.get(InventoryItem, item_id)
    if item is None or item.user_id != user_id:
        raise ItemNotFoundError(item_id)
    if item.is_sold:
        raise ItemAlreadySoldError(item_id)
    user = await session.get(User, user_id)
    if user is None:
        raise ItemNotFoundError(user_id)
    item.is_sold = True
    user.balance = round(user.balance + item.price, 2)
    await session.commit()
    return {"new_balance": user.balance, "sold_price": item.price}


def _inventory_public(item: InventoryItem) -> dict[str, Any]:
    return {
        "item_id": item.id,
        "skin_id": item.skin_id,
        "case_id": item.case_id,
        "name": item.name,
        "rarity": item.rarity,
        "wear": item.wear,
        "is_stat_trak": bool(item.is_stat_trak),
        "price": item.price,
        "created_at": (
            item.created_at.isoformat() if item.created_at else None
        ),
    }


async def inventory_list(
    session: AsyncSession, user_id: int
) -> dict[str, Any]:
    """Active (un-sold) inventory items, newest first."""
    items = (
        (
            await session.execute(
                select(InventoryItem)
                .where(
                    InventoryItem.user_id == user_id,
                    InventoryItem.is_sold.is_(False),
                )
                .order_by(InventoryItem.id.desc())
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [_inventory_public(item) for item in items],
        "count": len(items),
    }
