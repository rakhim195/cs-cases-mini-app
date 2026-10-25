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
    name_en: str | None = None
    image: str | None = None
    hype_title: str | None = None
    tags: tuple[str, ...] = ()

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
            name_en=entry.get("name_en"),
            image=entry.get("image"),
            hype_title=entry.get("hype_title"),
            tags=tuple(entry.get("tags", ())),
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


def all_skins() -> list[dict[str, Any]]:
    """Every unique skin across all cases, priciest first.

    Each entry carries the id of the first case that contains the skin, so
    upgrader wins can be persisted with a valid case_id.
    """
    seen: dict[str, dict[str, Any]] = {}
    for case in list_cases():
        for item in case.items:
            skin_id = item["skin_id"]
            if skin_id in seen:
                continue
            seen[skin_id] = {
                "skin_id": skin_id,
                "case_id": case.id,
                "name": item["name"],
                "rarity": item["rarity"],
                "base_price": item["base_price"],
                "name_en": item.get("name_en"),
                "image": item.get("image"),
                "min_float": item.get("min_float", 0.0),
                "max_float": item.get("max_float", 1.0),
            }
    return sorted(
        seen.values(), key=lambda skin: float(skin["base_price"]), reverse=True
    )


def get_skin(skin_id: str) -> dict[str, Any] | None:
    """One catalog skin by skin_id, or None (see all_skins for fields)."""
    for skin in all_skins():
        if skin["skin_id"] == skin_id:
            return skin
    return None


def case_public(case: Case) -> dict[str, Any]:
    """API projection of a case, including its full item pool."""
    return {
        "id": case.id,
        "name": case.name,
        "name_en": case.name_en,
        "hype_title": case.hype_title,
        "tags": list(case.tags),
        "price": case.price,
        "cooldown_hours": case.cooldown_hours,
        "accent": case.accent,
        "image": case.image,
        "items": [dict(item) for item in case.items],
    }
