"""Gameplay HTTP API."""

from __future__ import annotations

import asyncio
import urllib.request
from datetime import datetime, timezone
from math import ceil
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import get_session
from services import battle, daily, game, upgrade
from services.catalog import CaseNotFoundError, case_public, list_cases

router = APIRouter(prefix="/api", tags=["gameplay"])

# Steam/Telegram image hosts the proxy is allowed to fetch (SSRF guard).
ALLOWED_IMAGE_HOSTS = frozenset(
    {
        "community.akamai.steamstatic.com",
        "community.cloudflare.steamstatic.com",
        "cdn.akamai.steamstatic.com",
        "cdn.cloudflare.steamstatic.com",
        "cdn.steamcommunity.com",
    }
)
PROXY_MAX_BYTES = 8 * 1024 * 1024


class OpenCaseRequest(BaseModel):
    user_id: int
    case_id: str


class UpgradeRequest(BaseModel):
    user_id: int
    selected_item_id: int
    target_skin_id: str


class DailyClaimRequest(BaseModel):
    user_id: int


class BattleCreateRequest(BaseModel):
    user_id: int
    case_id: str
    rounds: int
    is_bot_opponent: bool = False


class BattleJoinRequest(BaseModel):
    user_id: int


class SellItemRequest(BaseModel):
    user_id: int
    item_id: int


@router.get("/cases")
async def get_cases() -> dict:
    """Full case catalog with prices and item pools."""
    return {"cases": [case_public(case) for case in list_cases()]}


@router.get("/config")
async def get_config() -> dict:
    """Public Mini App configuration (referral deep-link base, etc.)."""
    return {"bot_username": settings.bot_username}


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


@router.get("/upgrade/catalog")
async def get_upgrade_catalog() -> dict:
    """Skins available as upgrade targets, sorted by price (desc)."""
    return await upgrade.upgrade_catalog()


@router.post("/upgrade")
async def upgrade_skin(
    body: UpgradeRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    """Stake an owned skin for a chance to win a catalog target."""
    try:
        return await upgrade.upgrade_item(
            session, body.user_id, body.selected_item_id, body.target_skin_id
        )
    except upgrade.UpgradeItemNotFoundError:
        raise HTTPException(
            status_code=404, detail="Скин для апгрейда не найден"
        ) from None
    except upgrade.UpgradeTargetNotFoundError:
        raise HTTPException(
            status_code=404, detail="Целевой скин не найден"
        ) from None


@router.get("/battles/active")
async def get_active_battles(
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Open 1v1 lobbies waiting for an opponent."""
    return await battle.list_active_battles(session)


@router.post("/battles/create")
async def create_battle(
    body: BattleCreateRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    """Open a battle lobby, or instantly duel the bot."""
    try:
        return await battle.create_battle(
            session, body.user_id, body.case_id, body.rounds, body.is_bot_opponent
        )
    except CaseNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"Кейс «{body.case_id}» не найден"
        ) from None
    except battle.BattleValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except game.InsufficientFundsError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Недостаточно средств: нужно {exc.price:.0f} ₽",
        ) from None


@router.post("/battles/{battle_id}/join")
async def join_battle(
    battle_id: int,
    body: BattleJoinRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Player 2 pays the entry; the battle resolves instantly."""
    try:
        return await battle.join_battle(session, battle_id, body.user_id)
    except battle.BattleNotFoundError:
        raise HTTPException(status_code=404, detail="Битва не найдена") from None
    except battle.BattleNotJoinableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except game.InsufficientFundsError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Недостаточно средств: нужно {exc.price:.0f} ₽",
        ) from None


@router.get("/battles/{battle_id}/state")
async def get_battle_state(
    battle_id: int, session: AsyncSession = Depends(get_session)
) -> dict:
    """Rounds, drops and the winner (hidden until the battle finishes)."""
    try:
        return await battle.battle_state(session, battle_id)
    except battle.BattleNotFoundError:
        raise HTTPException(status_code=404, detail="Битва не найдена") from None


@router.get("/proxy-image")
async def proxy_image(url: str) -> Response:
    """Same-origin image proxy for canvas/story use.

    Telegram's story renderer and the canvas API both misbehave with raw
    Steam CDN URLs (black media / tainted canvas). Serving the bytes from
    our own origin with a clean Content-Type fixes both.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https" or (parsed.hostname or "") not in ALLOWED_IMAGE_HOSTS:
        raise HTTPException(status_code=400, detail="Хост изображения не разрешён")

    def fetch() -> tuple[bytes, str]:
        request = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (compatible; CaseBattleBot)"}
        )
        with urllib.request.urlopen(request, timeout=12) as resp:
            data = resp.read(PROXY_MAX_BYTES + 1)
        if len(data) > PROXY_MAX_BYTES:
            raise ValueError("image too large")
        return data, resp.headers.get_content_type()

    try:
        data, content_type = await asyncio.to_thread(fetch)
    except ValueError:
        raise HTTPException(status_code=413, detail="Изображение слишком большое") from None
    except Exception:
        raise HTTPException(status_code=502, detail="Не удалось загрузить изображение") from None

    if not content_type.startswith("image/"):
        content_type = "image/png"
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=86400",
        },
    )


@router.get("/daily/status/{user_id}")
async def get_daily_status(
    user_id: int, session: AsyncSession = Depends(get_session)
) -> dict:
    """Streak progress, next-claim countdown and the 7-day reward track."""
    return await daily.daily_status(session, user_id)


@router.post("/daily/claim")
async def claim_daily(
    body: DailyClaimRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    """Claim today's streak reward (coins, or a free case on day 7)."""
    try:
        return await daily.claim_daily(session, body.user_id)
    except daily.DailyCooldownError as exc:
        remaining_seconds = max(
            1,
            ceil(
                (exc.available_at - datetime.now(timezone.utc)).total_seconds()
            ),
        )
        raise HTTPException(
            status_code=429,
            detail=(
                "Бонус уже получен. Следующий через "
                f"{remaining_seconds // 3600} ч "
                f"{(remaining_seconds % 3600) // 60:02d} мин"
            ),
        ) from None
