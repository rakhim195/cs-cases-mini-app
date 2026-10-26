"""Server-rendered 1080x1920 story cards.

Telegram's shareToStory requires a real public HTTPS image URL — dataURLs
render as a black screen on iOS — so the card is composed server-side with
Pillow and served as image/png.
"""

from __future__ import annotations

import io
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from services.catalog import get_skin

W = 1080
H = 1920

FONTS_DIR = Path(__file__).resolve().parents[1] / "static" / "fonts"

RARITY_COLORS: dict[str, str] = {
    "Mil-Spec": "#4b69ff",
    "Restricted": "#8847ff",
    "Classified": "#d32ce6",
    "Covert": "#eb4b4b",
    "Special": "#ffd700",
}

WEAR_RU: dict[str, str] = {
    "Factory New": "Прямо с завода",
    "Minimal Wear": "Немного поношенное",
    "Field-Tested": "После полевых испытаний",
    "Well-Worn": "Поношенное",
    "Battle-Scarred": "Закалённое в боях",
}

WEAR_FLOAT_BANDS: dict[str, tuple[float, float]] = {
    "Factory New": (0.0, 0.07),
    "Minimal Wear": (0.07, 0.15),
    "Field-Tested": (0.15, 0.38),
    "Well-Worn": (0.38, 0.45),
    "Battle-Scarred": (0.45, 1.0),
}

# Steam/Telegram hosts the shared image fetcher may retrieve (SSRF guard).
ALLOWED_IMAGE_HOSTS = frozenset(
    {
        "community.akamai.steamstatic.com",
        "community.cloudflare.steamstatic.com",
        "cdn.akamai.steamstatic.com",
        "cdn.cloudflare.steamstatic.com",
        "cdn.steamcommunity.com",
    }
)
FETCH_MAX_BYTES = 8 * 1024 * 1024

_FONT_CACHE: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    key = ("b" if bold else "r", size)
    if key not in _FONT_CACHE:
        name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
        _FONT_CACHE[key] = ImageFont.truetype(str(FONTS_DIR / name), size)
    return _FONT_CACHE[key]


def hex_rgba(color: str, alpha: int) -> tuple[int, int, int, int]:
    color = color.lstrip("#")
    return (
        int(color[0:2], 16),
        int(color[2:4], 16),
        int(color[4:6], 16),
        alpha,
    )


def hex_rgb(color: str) -> tuple[int, int, int]:
    return hex_rgba(color, 255)[:3]


def fetch_image_bytes(url: str) -> tuple[bytes, str]:
    """Guarded image fetch used by both the proxy route and story cards."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme != "https" or (parsed.hostname or "") not in ALLOWED_IMAGE_HOSTS:
        raise ValueError("host not allowed")
    request = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (compatible; CaseBattleBot)"}
    )
    with urllib.request.urlopen(request, timeout=12) as resp:
        data = resp.read(FETCH_MAX_BYTES + 1)
    if len(data) > FETCH_MAX_BYTES:
        raise ValueError("image too large")
    return data, resp.headers.get_content_type()


def _derived_float(item_id: int, wear: str, min_float: float, max_float: float) -> str:
    band_lo, band_hi = WEAR_FLOAT_BANDS.get(wear, (0.0, 1.0))
    lo = max(band_lo, min_float)
    hi = min(band_hi, max_float)
    if hi <= lo:
        lo, hi = 0.0, 1.0
    seed = ((item_id * 2654435761) % 10000) / 10000
    value = min(lo + seed * (hi - lo), hi - 0.0001)
    return f"{value:.4f}"


def _vertical_gradient(top: str, bottom: str) -> Image.Image:
    strip = Image.new("RGB", (1, H))
    r1, g1, b1 = hex_rgb(top)
    r2, g2, b2 = hex_rgb(bottom)
    for y in range(H):
        k = y / (H - 1)
        strip.putpixel((0, y), (
            int(r1 + (r2 - r1) * k),
            int(g1 + (g2 - g1) * k),
            int(b1 + (b2 - b1) * k),
        ))
    return strip.resize((W, H))


def _radial_glow(color: str, radius: int, max_alpha: int) -> Image.Image:
    size = radius * 2
    mask = Image.new("L", (size, size))
    mask.putdata([
        int(max_alpha * max(0.0, 1.0 - ((x - radius) ** 2 + (y - radius) ** 2) ** 0.5 / radius) ** 1.4)
        for y in range(size)
        for x in range(size)
    ])
    glow = Image.new("RGBA", (size, size), hex_rgba(color, 255))
    glow.putalpha(mask)
    return glow


def _fetch_weapon_render(image_url: str | None) -> Image.Image | None:
    if not image_url:
        return None
    try:
        data, _ctype = fetch_image_bytes(image_url + "/512fx512f")
        return Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        return None


def _draw_vector_fallback(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: str) -> None:
    import math

    points = []
    for i in range(6):
        a = math.pi / 6 + i * math.pi / 3
        points.append((cx + math.cos(a) * 230, cy + math.sin(a) * 145))
    draw.polygon(points, outline=hex_rgb(color), width=8)
    draw.text((cx, cy), "CS", font=font(96), fill=hex_rgb("#ffffff"), anchor="mm")


def render_story_card(item: dict[str, Any]) -> bytes:
    """Compose the 1080x1920 PNG story card for one inventory item."""
    skin = get_skin(item["skin_id"]) or {}
    color = RARITY_COLORS.get(item["rarity"], "#8b93a7")
    price_rub = int(round(float(item["price"])))

    base = _vertical_gradient("#0b0e14", "#121824").convert("RGBA")
    glow = _radial_glow(color, 540, 110)
    base.alpha_composite(glow, (W // 2 - 540, 750 - 540))

    weapon = _fetch_weapon_render(skin.get("image"))
    if weapon is not None:
        max_w, max_h = 840, 560
        k = min(max_w / weapon.width, max_h / weapon.height)
        weapon = weapon.resize(
            (int(weapon.width * k), int(weapon.height * k)), Image.LANCZOS
        )
        base.alpha_composite(weapon, (W // 2 - weapon.width // 2, 760 - weapon.height // 2))

    draw = ImageDraw.Draw(base)

    # Header
    draw.text((W // 2, 200), "CS CASE BATTLE", font=font(64),
              fill=hex_rgb("#ffc233"), anchor="mm")
    draw.text((W // 2, 272), "ВЫБИЛ В @KeysikAppBot", font=font(40),
              fill=hex_rgb("#8b93a7"), anchor="mm")

    if weapon is None:
        _draw_vector_fallback(draw, W // 2, 760, color)

    # Name (auto-shrink), rarity, wear + StatTrak
    name = item["name"]
    size = 58
    name_font = font(size)
    while draw.textlength(name, font=name_font) > W - 90 and size > 26:
        size -= 2
        name_font = font(size)
    draw.text((W // 2, 1112), name, font=name_font,
              fill=hex_rgb("#ffffff"), anchor="mm")
    draw.text((W // 2, 1186), item["rarity"].upper(), font=font(38),
              fill=hex_rgb(color), anchor="mm")

    float_text = _derived_float(
        item["item_id"], item["wear"],
        float(skin.get("min_float", 0.0)), float(skin.get("max_float", 1.0)),
    )
    # Wear badge (pill) + StatTrak badge side by side under the rarity.
    wear_label = f"{WEAR_RU.get(item['wear'], item['wear'])} • {float_text}"
    badge_font = font(30)
    wear_w = draw.textlength(wear_label, font=badge_font)
    badge_y = 1250
    draw.rounded_rectangle(
        (W // 2 - wear_w / 2 - 26, badge_y - 32, W // 2 + wear_w / 2 + 26, badge_y + 32),
        radius=32, outline=hex_rgb("#8b93a7"), width=2,
    )
    draw.text((W // 2, badge_y), wear_label, font=badge_font,
              fill=hex_rgb("#8b93a7"), anchor="mm")
    if item["is_stat_trak"]:
        st_label = "StatTrak™"
        st_w = draw.textlength(st_label, font=badge_font)
        st_y = badge_y + 86
        draw.rounded_rectangle(
            (W // 2 - st_w / 2 - 26, st_y - 32, W // 2 + st_w / 2 + 26, st_y + 32),
            radius=32, fill=hex_rgba("#ff9d2e", 60), outline=hex_rgb("#ff9d2e"), width=2,
        )
        draw.text((W // 2, st_y), st_label, font=badge_font,
                  fill=hex_rgb("#ff9d2e"), anchor="mm")

    # Big gold price
    draw.text((W // 2, 1430), f"{price_rub:,} ₽".replace(",", " "),
              font=font(110), fill=hex_rgb("#f59e0b"), anchor="mm")

    # Bottom CTA banner with the bot link
    banner_y = 1600
    for y in range(banner_y, H):
        k = (y - banner_y) / (H - banner_y)
        alpha = int(26 + 40 * k)
        draw.line([(0, y), (W, y)], fill=hex_rgba("#ffc233", alpha))
    draw.line([(0, banner_y), (W, banner_y)], fill=hex_rgba("#ffc233", 102), width=3)
    draw.text((W // 2, 1706), "ЗАБИРАЙ СВОЙ БЕСПЛАТНЫЙ КЕЙС", font=font(48),
              fill=hex_rgb("#ffc233"), anchor="mm")
    draw.text((W // 2, 1782), "t.me/KeysikAppBot", font=font(40, bold=False),
              fill=hex_rgb("#8b93a7"), anchor="mm")

    out = io.BytesIO()
    base.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()


def render_referral_card() -> bytes:
    """1080x1920 invite banner for the friends tab story share."""
    base = _vertical_gradient("#0b0e14", "#121824").convert("RGBA")
    glow = _radial_glow("#ffc233", 540, 90)
    base.alpha_composite(glow, (W // 2 - 540, 700 - 540))
    draw = ImageDraw.Draw(base)

    draw.text((W // 2, 240), "CS CASE BATTLE", font=font(64),
              fill=hex_rgb("#ffc233"), anchor="mm")
    draw.text((W // 2, 700), "ЗОВИ ДРУЗЕЙ —", font=font(96),
              fill=hex_rgb("#ffffff"), anchor="mm")
    draw.text((W // 2, 830), "ПОЛУЧАЙ НАГРАДЫ", font=font(96),
              fill=hex_rgb("#ffc233"), anchor="mm")
    draw.text((W // 2, 990), "Другу сразу +100 ₽ на баланс",
              font=font(44, bold=False), fill=hex_rgb("#8b93a7"), anchor="mm")
    draw.text((W // 2, 1060), "Тебе — 5% с каждого его кейса",
              font=font(44, bold=False), fill=hex_rgb("#8b93a7"), anchor="mm")

    banner_y = 1450
    for y in range(banner_y, H):
        k = (y - banner_y) / (H - banner_y)
        alpha = int(26 + 40 * k)
        draw.line([(0, y), (W, y)], fill=hex_rgba("#ffc233", alpha))
    draw.line([(0, banner_y), (W, banner_y)], fill=hex_rgba("#ffc233", 102), width=3)
    draw.text((W // 2, 1560), "ЖМИ И ОТКРЫВАЙ КЕЙСЫ", font=font(52),
              fill=hex_rgb("#ffc233"), anchor="mm")
    draw.text((W // 2, 1650), "t.me/KeysikAppBot", font=font(48, bold=False),
              fill=hex_rgb("#ffffff"), anchor="mm")

    out = io.BytesIO()
    base.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()
