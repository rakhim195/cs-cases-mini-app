"""ORM package: importing this module registers every model on Base.metadata."""

from models.base import Base
from models.battle import (
    BATTLE_FINISHED,
    BATTLE_IN_PROGRESS,
    BATTLE_WAITING,
    BOT_USER_ID,
    Battle,
    BattleRound,
)
from models.daily import DailyStreak
from models.inventory import InventoryItem
from models.referral import Referral
from models.user import User

__all__ = [
    "Base",
    "BATTLE_FINISHED",
    "BATTLE_IN_PROGRESS",
    "BATTLE_WAITING",
    "BOT_USER_ID",
    "Battle",
    "BattleRound",
    "DailyStreak",
    "InventoryItem",
    "Referral",
    "User",
]
