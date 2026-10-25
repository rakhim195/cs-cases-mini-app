"""Case catalog loaded from data/cases.json."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "cases.json"

VALID_RARITIES = frozenset(
    {"Mil-Spec", "Restricted", "Classified", "Covert", "Special"}
)


class CaseNotFoundError(KeyError):
    """Raised when a case id is absent from the catalog."""


@dataclass(frozen=True)
class Case:
    id: str
    name: str
    price: float
    cooldown_hours: int | None
    accent: str
    items: tuple[Mapping[str, Any], ...]

    @property
    def is_free(self) -> bool:
        return self.price == 0


def _validate(case: Case) -> None:
    if not case.items:
        raise ValueError(f"case {case.id!r} has an empty item pool")
    if case.price < 0:
        raise ValueError(f"case {case.id!r} has a negative price")
    if case.price == 0 and not case.cooldown_hours:
        raise ValueError(f"free case {case.id!r} must define cooldown_hours")
    seen: set[str] = set()
    for item in case.items:
        skin_id = item.get("skin_id")
        if skin_id in seen:
            raise ValueError(f"duplicate skin_id {skin_id!r} in case {case.id!r}")
        seen.add(skin_id)
        if item.get("rarity") not in VALID_RARITIES:
            raise ValueError(
                f"invalid rarity {item.get('rarity')!r} in case {case.id!r}"
            )
        if float(item.get("base_price", -1)) < 0:
            raise ValueError(f"bad base_price for {skin_id!r} in case {case.id!r}")
        if float(item.get("weight", 0)) <= 0:
            raise ValueError(f"bad weight for {skin_id!r} in case {case.id!r}")


@lru_cache(maxsize=1)
def _catalog() -> tuple[dict[str, Case], tuple[Case, ...]]:
    raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    ordered: list[Case] = []
    by_id: dict[str, Case] = {}
    for entry in raw["cases"]:
        case = Case(
            id=entry["id"],
            name=entry["name"],
            price=float(entry["price"]),
            cooldown_hours=entry.get("cooldown_hours"),
            accent=entry.get("accent", "#4b69ff"),
            items=tuple(entry["items"]),
        )
        _validate(case)
        ordered.append(case)
        by_id[case.id] = case
    return by_id, tuple(ordered)


def list_cases() -> list[Case]:
    """All cases in catalog order."""
    return list(_catalog()[1])


def get_case(case_id: str) -> Case:
    """Fetch one case by id or raise CaseNotFoundError."""
    try:
        return _catalog()[0][case_id]
    except KeyError:
        raise CaseNotFoundError(case_id) from None


def case_public(case: Case) -> dict[str, Any]:
    """API projection of a case, including its full item pool."""
    return {
        "id": case.id,
        "name": case.name,
        "price": case.price,
        "cooldown_hours": case.cooldown_hours,
        "accent": case.accent,
        "items": [dict(item) for item in case.items],
    }
