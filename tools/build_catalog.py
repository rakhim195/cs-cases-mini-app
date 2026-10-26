"""One-shot generator for the 15-case catalog (run: python tools/build_catalog.py).

Reuses the 83 verified skin entries (real RU names + Steam CDN images) from
the previous cases.json, regroups them into 15 themed cases and solves a
power-law weight profile so each case EV lands near 88% of its price.
"""

import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data" / "cases.json"

EV_TARGET_RATIO = 0.88

# case_id, name, price, accent, hype tags, theme item prices (must exist)
CASES = [
    ("daily_free", "Оружейный кейс CS:GO", 0, "#4b69ff", ["ХАЛЯВА 24Ч"], None),
    ("bomzh_start", "Бомж старт", 29, "#4b69ff", ["СТАРТ"], [2.5, 3, 3.5, 4, 5, 25, 145]),
    ("pistoletka", "Пистолетка", 59, "#4b69ff", ["ХИТ"], [5, 18, 42, 55, 70, 115, 145]),
    ("shotguns_smg", "Дробовики & SMG", 89, "#8847ff", ["ХИТ"], [3.5, 4, 25, 45, 68, 90, 98, 230, 380]),
    ("balance_boost", "Разгон баланса", 149, "#8847ff", ["ТОП"], [12, 25, 40, 48, 55, 105, 185, 230, 320, 420]),
    ("fifty_fifty", "50/50 Орел или Решка", 199, "#d32ce6", ["ХИТ"], [4, 25, 90, 1100, 1600, 2200]),
    ("ak_line", "Линейка Калашей", 249, "#8847ff", ["ТОП"], [42, 105, 230, 460, 520, 1600, 2200, 2800, 3400]),
    ("sniper_rub", "Снайперский рубеж", 299, "#eb4b4b", ["ТОП"], [62, 185, 320, 350, 850, 950, 1100, 1100]),
    ("m4_era", "Эра M4A4 / M4A1-S", 349, "#eb4b4b", ["ТОП"], [90, 130, 380, 420, 640, 1050, 2600, 3200]),
    ("knife_or_shirp", "Нож или Ширп", 399, "#ffd700", ["НОЖИ"], [3.5, 5, 25, 55, 98, 900, 1000, 1100]),
    ("neon_cyberpunk", "Неоновый киберпанк", 499, "#d32ce6", ["ХИТ"], [65, 128, 210, 360, 640, 1100, 1400]),
    ("stattrak_mania", "StatTrak мания", 799, "#eb4b4b", ["ТОП", "НОЖИ"], [380, 420, 520, 800, 850, 950, 1050]),
    ("gloves_kush", "Перчаточный куш", 1490, "#ffd700", ["НОЖИ"], [900, 1250, 2000, 230, 2500, 10500, 12500]),
    ("knife_duel", "Ножевая дуэль", 2490, "#ffd700", ["НОЖИ"], [1000, 1100, 1250, 1400, 1550, 1800, 2000, 3000, 5800, 6800]),
    ("printstream_elite", "Printstream элита", 3990, "#ffd700", ["ТОП", "НОЖИ"], [1400, 1600, 2200, 2800, 3200, 3400, 5800, 9500]),
    ("olymp_dragon_lore", "Олимп & Dragon Lore", 9900, "#ffd700", ["НОЖИ"], [6800, 6800, 7200, 9500, 9800, 10500, 12500]),
]


def solve_weights(prices, target_ev):
    """Power-law weights w=(p_min/p)^a; bisect alpha so EV hits the target."""

    def ev(alpha):
        pmin = min(prices)
        ws = [(pmin / p) ** alpha for p in prices]
        return sum(p * w for p, w in zip(prices, ws)) / sum(ws)

    lo, hi = 0.05, 30.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if ev(mid) > target_ev:
            lo = mid
        else:
            hi = mid
    alpha = (lo + hi) / 2
    pmin = min(prices)
    return [round(max(0.1, (pmin / p) ** alpha), 2) for p in prices], round(ev(alpha), 2), round(alpha, 3)


def main() -> None:
    old = json.loads(DATA.read_text(encoding="utf-8"))
    pool = []  # consuming multiset: several distinct skins share a price
    for case in old["cases"]:
        for it in case["items"]:
            pool.append((it["base_price"], it))

    out_cases = []
    for case_id, name, price, accent, tags, theme in CASES:
        if case_id == "daily_free":
            # keep the original free pool untouched
            old_free = next(c for c in old["cases"] if c["id"] == "daily_free")
            out_cases.append(old_free)
            continue
        assert len(theme) >= 6, (case_id, len(theme))
        picked = []
        working = list(pool)
        for p in theme:
            for idx, (price_, item) in enumerate(working):
                if price_ == p:
                    picked.append(item)
                    working.pop(idx)
                    break
            else:
                raise SystemExit(f"no item with price {p} for {name}")
        assert len({it['skin_id'] for it in picked}) == len(picked), name
        prices = [it["base_price"] for it in picked]
        target = price * EV_TARGET_RATIO
        assert min(prices) < target < sum(prices) / len(prices), (name, min(prices), target)
        weights, ev, alpha = solve_weights(prices, target)
        hero = max(picked, key=lambda i: i["base_price"])
        out_cases.append({
            "id": case_id,
            "name": name,
            "hype_title": name,
            "tags": tags,
            "price": price,
            "cooldown_hours": None,
            "accent": accent,
            "image": hero["image"],
            "items": [
                {**it, "weight": w}
                for it, w in zip(picked, weights)
            ],
        })
        print(f"{name:<28} {price:>6} ₽ | EV {ev:>7} ({ev/price:.0%}) | alpha {alpha} | {len(picked)} items")

    DATA.write_text(
        json.dumps({"cases": out_cases}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("written:", len(out_cases), "cases")


if __name__ == "__main__":
    main()
