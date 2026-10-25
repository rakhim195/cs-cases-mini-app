"""Skin upgrader: risk an owned skin for a shot at a catalog target."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from models import InventoryItem
from services import rng
from services.catalog import all_skins, get_skin

# House edge: the success curve is scaled down from a fair 1:1 price ratio
# and clamped so upgrades are never free wins nor impossible ones.
CHANCE_FACTOR = 0.95
CHANCE_MIN = 0.01
CHANCE_MAX = 0.80


class UpgradeItemNotFoundError(LookupError):
    """Staked item id is unknown, sold, or belongs to another user."""


class UpgradeTargetNotFoundError(LookupError):
    """Target skin_id is absent from the catalog."""


def success_chance(selected_price: float, target_price: float) -> float:
    """min(0.80, max(0.01, selected/target * 0.95)) — mirrored client-side."""
    if target_price <= 0:
        return CHANCE_MAX
    chance = (float(selected_price) / float(target_price)) * CHANCE_FACTOR
    return round(min(CHANCE_MAX, max(CHANCE_MIN, chance)), 4)


async def upgrade_catalog() -> dict[str, Any]:
    """Every skin reachable as an upgrade target, priciest first."""
    return {"items": [dict(skin) for skin in all_skins()]}


async def upgrade_item(
    session: AsyncSession,
    user_id: int,
    selected_item_id: int,
    target_skin_id: str,
) -> dict[str, Any]:
    """Burn the staked item and roll for the target.

    The roll is a uniform pointer angle in [0, 360); the win arc spans the
    first chance*360 degrees, so the client can replay the exact outcome on
    its circular ticker with no separate win flag to trust.
    """
    stake = await session.get(InventoryItem, selected_item_id)
    if stake is None or stake.user_id != user_id or stake.is_sold:
        raise UpgradeItemNotFoundError(selected_item_id)
    target = get_skin(target_skin_id)
    if target is None:
        raise UpgradeTargetNotFoundError(target_skin_id)

    chance = success_chance(stake.price, target["base_price"])
    roll_degree = round(rng.secure_uniform() * 360.0, 2)
    win = roll_degree < chance * 360.0

    payload: dict[str, Any] = {
        "status": "win" if win else "lose",
        "chance": chance,
        "roll_degree": roll_degree,
        "consumed_item_id": stake.id,
    }

    await session.delete(stake)

    if win:
        wear_name, wear_float = rng.roll_wear(
            target.get("min_float", 0.0), target.get("max_float", 1.0)
        )
        is_stat_trak = rng.roll_stat_trak()
        price = rng.compute_price(target["base_price"], is_stat_trak)
        won = InventoryItem(
            user_id=user_id,
            skin_id=target["skin_id"],
            case_id=target["case_id"],
            name=target["name"],
            rarity=target["rarity"],
            wear=wear_name,
            is_stat_trak=is_stat_trak,
            price=price,
            is_sold=False,
        )
        session.add(won)
        await session.flush()
        payload["target_item"] = {
            "item_id": won.id,
            "skin_id": won.skin_id,
            "case_id": won.case_id,
            "name": won.name,
            "rarity": won.rarity,
            "wear": wear_name,
            "wear_float": wear_float,
            "is_stat_trak": is_stat_trak,
            "price": price,
            "base_price": target["base_price"],
            "name_en": target.get("name_en"),
            "image": target.get("image"),
        }

    await session.commit()
    return payload
