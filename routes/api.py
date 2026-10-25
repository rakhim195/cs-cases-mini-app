"""Gameplay HTTP API."""

from __future__ import annotations

from datetime import datetime, timezone
from math import ceil

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_session
from services import game
from services.catalog import CaseNotFoundError, case_public, list_cases

router = APIRouter(prefix="/api", tags=["gameplay"])


class OpenCaseRequest(BaseModel):
    user_id: int
    case_id: str


class SellItemRequest(BaseModel):
    user_id: int
    item_id: int


@router.get("/cases")
async def get_cases() -> dict:
    """Full case catalog with prices and item pools."""
    return {"cases": [case_public(case) for case in list_cases()]}


@router.get("/user/{user_id}")
async def get_user(
    user_id: int, session: AsyncSession = Depends(get_session)
) -> dict:
    """Player profile for the header; provisions the user on first call."""
    return await game.user_profile(session, user_id)


@router.post("/cases/open")
async def open_case(
    body: OpenCaseRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    """Open a case: charge or cooldown-check, roll RNG, persist the drop."""
    try:
        return await game.open_case(session, body.user_id, body.case_id)
    except CaseNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"Кейс «{body.case_id}» не найден"
        ) from None
    except game.CooldownError as exc:
        remaining_minutes = max(
            1,
            ceil(
                (exc.available_at - datetime.now(timezone.utc)).total_seconds()
                / 60
            ),
        )
        raise HTTPException(
            status_code=429,
            detail=(
                "Бесплатный кейс будет доступен через "
                f"{remaining_minutes // 60} ч {remaining_minutes % 60:02d} мин"
            ),
        ) from None
    except game.InsufficientFundsError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Недостаточно средств: цена кейса {exc.price:.0f} ₽",
        ) from None


@router.post("/items/sell")
async def sell_item(
    body: SellItemRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    """Sell an inventory item and credit its price to the balance."""
    try:
        return await game.sell_item(session, body.user_id, body.item_id)
    except game.ItemNotFoundError:
        raise HTTPException(status_code=404, detail="Предмет не найден") from None
    except game.ItemAlreadySoldError:
        raise HTTPException(status_code=409, detail="Предмет уже продан") from None


@router.get("/inventory/{user_id}")
async def get_inventory(
    user_id: int, session: AsyncSession = Depends(get_session)
) -> dict:
    """Active (un-sold) inventory items, newest first."""
    return await game.inventory_list(session, user_id)
