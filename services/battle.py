"""1v1 battles: lobbies, instant bot duels, winner-takes-all payouts."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    BOT_USER_ID,
    Battle,
    BattleRound,
    BATTLE_FINISHED,
    BATTLE_WAITING,
    InventoryItem,
    User,
)
from services import rng
from services.catalog import get_case, get_skin

MIN_ROUNDS = 1
MAX_ROUNDS = 5
BOT_NAME = "Бот Кейсик"


class BattleNotFoundError(LookupError):
    """Battle id is unknown."""


class BattleNotJoinableError(RuntimeError):
    """Battle is not waiting for an opponent, or it is your own lobby."""


class BattleValidationError(ValueError):
    """Rounds out of range."""


def _roll_drop(case_items) -> dict[str, Any]:
    """Roll one drop: skin + wear + StatTrak + price (like a case open)."""
    pool_item = rng.weighted_pick(case_items)
    wear_name, _float = rng.roll_wear(
        pool_item.get("min_float", 0.0), pool_item.get("max_float", 1.0)
    )
    is_stat_trak = rng.roll_stat_trak()
    return {
        "skin_id": pool_item["skin_id"],
        "price": rng.compute_price(pool_item["base_price"], is_stat_trak),
        "wear": wear_name,
        "is_stat_trak": is_stat_trak,
    }


def _skin_display(skin_id: str, price: float, wear: str, is_stat_trak: bool):
    skin = get_skin(skin_id) or {}
    return {
        "skin_id": skin_id,
        "name": skin.get("name", skin_id),
        "rarity": skin.get("rarity"),
        "price": price,
        "wear": wear,
        "is_stat_trak": is_stat_trak,
        "image": skin.get("image"),
    }


async def _display_name(session: AsyncSession, user_id: int | None) -> str:
    if user_id is None:
        return "—"
    if user_id == BOT_USER_ID:
        return BOT_NAME
    user = await session.get(User, user_id)
    if user is None:
        return str(user_id)
    return user.first_name or user.username or f"Игрок {user_id}"


async def create_battle(
    session: AsyncSession,
    user_id: int,
    case_id: str,
    rounds: int,
    is_bot_opponent: bool,
) -> dict[str, Any]:
    """Charge the creator and open a lobby — or instantly resolve a bot duel."""
    if not MIN_ROUNDS <= rounds <= MAX_ROUNDS:
        raise BattleValidationError(
            f"Раунды должны быть от {MIN_ROUNDS} до {MAX_ROUNDS}"
        )
    case = get_case(case_id)  # raises CaseNotFoundError upstream
    cost = round(case.price * rounds, 2)

    user = await session.get(User, user_id)
    if user is None:
        from services.game import get_or_create_user

        user = await get_or_create_user(session, user_id)
    if user.balance < cost:
        from services.game import InsufficientFundsError

        raise InsufficientFundsError(cost)
    user.balance = round(user.balance - cost, 2)

    battle = Battle(
        creator_id=user_id,
        opponent_id=BOT_USER_ID if is_bot_opponent else None,
        case_id=case.id,
        rounds=rounds,
        status=BATTLE_WAITING,
    )
    session.add(battle)
    await session.flush()

    # Both sides always roll round-by-round, bots included.
    for round_number in range(1, rounds + 1):
        p1 = _roll_drop(case.items)
        p2 = _roll_drop(case.items)
        session.add(
            BattleRound(
                battle_id=battle.id,
                round_number=round_number,
                p1_skin_id=p1["skin_id"],
                p1_skin_price=p1["price"],
                p1_wear=p1["wear"],
                p1_is_stat_trak=p1["is_stat_trak"],
                p2_skin_id=p2["skin_id"],
                p2_skin_price=p2["price"],
                p2_wear=p2["wear"],
                p2_is_stat_trak=p2["is_stat_trak"],
            )
        )

    if is_bot_opponent:
        # Rounds must be flushed first: the session has autoflush=False, so
        # _resolve's SELECT would not see the pending INSERTs otherwise.
        await session.flush()
        await _resolve(session, battle)
    await session.commit()

    state = await battle_state(session, battle.id)
    state["new_balance"] = user.balance
    state["cost"] = cost
    return state


async def list_active_battles(session: AsyncSession) -> dict[str, Any]:
    """Open lobbies, newest first, with creator names for the lobby list."""
    battles = (
        (
            await session.execute(
                select(Battle)
                .where(Battle.status == BATTLE_WAITING, Battle.opponent_id.is_(None))
                .order_by(Battle.id.desc())
                .limit(30)
            )
        )
        .scalars()
        .all()
    )
    items = []
    for battle in battles:
        case = get_case(battle.case_id)
        items.append(
            {
                "id": battle.id,
                "creator_id": battle.creator_id,
                "creator_name": await _display_name(session, battle.creator_id),
                "case_id": battle.case_id,
                "case_name": case.name,
                "case_image": case.image,
                "rounds": battle.rounds,
                "cost": round(case.price * battle.rounds, 2),
                "created_at": (
                    battle.created_at.isoformat() if battle.created_at else None
                ),
            }
        )
    return {"battles": items}


async def join_battle(
    session: AsyncSession, battle_id: int, user_id: int
) -> dict[str, Any]:
    """Player 2 pays the entry and the battle resolves instantly."""
    battle = await session.get(Battle, battle_id)
    if battle is None:
        raise BattleNotFoundError(battle_id)
    if battle.status != BATTLE_WAITING or battle.opponent_id is not None:
        raise BattleNotJoinableError("К битве уже присоединились")
    if battle.creator_id == user_id:
        raise BattleNotJoinableError("Нельзя присоединиться к своей битве")

    case = get_case(battle.case_id)
    cost = round(case.price * battle.rounds, 2)
    user = await session.get(User, user_id)
    if user is None:
        from services.game import get_or_create_user

        user = await get_or_create_user(session, user_id)
    if user.balance < cost:
        from services.game import InsufficientFundsError

        raise InsufficientFundsError(cost)
    user.balance = round(user.balance - cost, 2)

    battle.opponent_id = user_id
    await _resolve(session, battle)
    await session.commit()

    state = await battle_state(session, battle.id)
    state["new_balance"] = user.balance
    state["cost"] = cost
    return state


async def _resolve(session: AsyncSession, battle: Battle) -> None:
    """Tally totals, decide the winner, and pay out every dropped skin."""
    rounds = (
        (
            await session.execute(
                select(BattleRound)
                .where(BattleRound.battle_id == battle.id)
                .order_by(BattleRound.round_number)
            )
        )
        .scalars()
        .all()
    )
    total_p1 = round(sum(r.p1_skin_price for r in rounds), 2)
    total_p2 = round(sum(r.p2_skin_price or 0.0 for r in rounds), 2)
    battle.total_p1_value = total_p1
    battle.total_p2_value = total_p2

    if total_p1 > total_p2:
        battle.winner_id = battle.creator_id
    elif total_p2 > total_p1:
        battle.winner_id = battle.opponent_id
    else:
        battle.winner_id = None  # draw: everyone keeps their own drops

    if battle.winner_id == BOT_USER_ID:
        # The bot's winnings belong to no one — they simply burn.
        pass
    elif battle.winner_id is not None:
        # Winner takes all: both sides' drops land in one inventory.
        for round_row in rounds:
            for prefix in ("p1", "p2"):
                skin_id = getattr(round_row, f"{prefix}_skin_id")
                skin = get_skin(skin_id)
                if skin is None:
                    continue
                session.add(
                    InventoryItem(
                        user_id=battle.winner_id,
                        skin_id=skin_id,
                        case_id=skin["case_id"],
                        name=skin["name"],
                        rarity=skin["rarity"],
                        wear=getattr(round_row, f"{prefix}_wear") or "Factory New",
                        is_stat_trak=bool(
                            getattr(round_row, f"{prefix}_is_stat_trak")
                        ),
                        price=getattr(round_row, f"{prefix}_skin_price") or 0.0,
                        is_sold=False,
                    )
                )
    else:
        # Draw: each player keeps exactly their own drops.
        for round_row in rounds:
            for user_id_value, prefix in (
                (battle.creator_id, "p1"),
                (battle.opponent_id, "p2"),
            ):
                if user_id_value in (None, BOT_USER_ID):
                    continue
                skin = get_skin(getattr(round_row, f"{prefix}_skin_id"))
                if skin is None:
                    continue
                session.add(
                    InventoryItem(
                        user_id=user_id_value,
                        skin_id=skin["skin_id"],
                        case_id=skin["case_id"],
                        name=skin["name"],
                        rarity=skin["rarity"],
                        wear=getattr(round_row, f"{prefix}_wear") or "Factory New",
                        is_stat_trak=bool(
                            getattr(round_row, f"{prefix}_is_stat_trak")
                        ),
                        price=getattr(round_row, f"{prefix}_skin_price") or 0.0,
                        is_sold=False,
                    )
                )

    battle.status = BATTLE_FINISHED


async def battle_state(session: AsyncSession, battle_id: int) -> dict[str, Any]:
    """Full battle payload for the arena UI."""
    battle = await session.get(Battle, battle_id)
    if battle is None:
        raise BattleNotFoundError(battle_id)
    case = get_case(battle.case_id)
    rounds = (
        (
            await session.execute(
                select(BattleRound)
                .where(BattleRound.battle_id == battle.id)
                .order_by(BattleRound.round_number)
            )
        )
        .scalars()
        .all()
    )
    is_bot = battle.opponent_id == BOT_USER_ID
    finished = battle.status == BATTLE_FINISHED
    round_items = []
    for row in rounds:
        # A waiting lobby must not leak anyone's drops (no peek-and-dodge).
        p1 = (
            _skin_display(
                row.p1_skin_id,
                row.p1_skin_price,
                row.p1_wear,
                row.p1_is_stat_trak,
            )
            if finished
            else None
        )
        p2 = (
            _skin_display(
                row.p2_skin_id,
                row.p2_skin_price or 0.0,
                row.p2_wear or "Factory New",
                bool(row.p2_is_stat_trak),
            )
            if finished and row.p2_skin_id
            else None
        )
        round_items.append({"round_number": row.round_number, "p1": p1, "p2": p2})

    return {
        "battle": {
            "id": battle.id,
            "creator_id": battle.creator_id,
            "creator_name": await _display_name(session, battle.creator_id),
            "opponent_id": battle.opponent_id,
            "opponent_name": await _display_name(session, battle.opponent_id),
            "case_id": battle.case_id,
            "case_name": case.name,
            "rounds": battle.rounds,
            "status": battle.status,
            "winner_id": battle.winner_id,
            "is_bot": is_bot,
            "total_p1_value": battle.total_p1_value,
            "total_p2_value": battle.total_p2_value,
        },
        "rounds": round_items,
        "cost": round(case.price * battle.rounds, 2),
    }
