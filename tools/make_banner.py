"""Generate the 640x360 BotFather banner: static/img/bot_banner_640x360.png.

Composition: dark esports gradient background, gold radial glow, subtle
diagonal streaks, the official 3D case artwork (fetched from the Steam CDN
entry in data/cases.json) centered, gold-gradient «КЕЙСИК» title, tagline
and bot link. Falls back to a stylized vector crate when the CDN is
unreachable, so the script always produces a usable banner offline.

Usage:
    python tools/make_banner.py [case_id]   # default: knife_duel
"""

from __future__ import annotations

import io
import json
import sys
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
CASES_JSON = ROOT / "data" / "cases.json"
FONTS_DIR = ROOT / "static" / "fonts"
OUT_PATH = ROOT / "static" / "img" / "bot_banner_640x360.png"

W, H = 640, 360
DEFAULT_CASE_ID = "knife_duel"
IMAGE_SUFFIX = "/360fx360f"
FETCH_TIMEOUT = 12

TOP_COLOR = (10, 13, 20)      # #0a0d14
BOTTOM_COLOR = (18, 22, 32)   # #121620
GOLD = (255, 194, 51)
GOLD_LIGHT = (255, 226, 122)
GOLD_DEEP = (255, 138, 0)

_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    key = ("b" if bold else "r", size)
    if key not in _font_cache:
        name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
        _font_cache[key] = ImageFont.truetype(str(FONTS_DIR / name), size)
    return _font_cache[key]


def case_image_url(case_id: str | None) -> str | None:
    """Resolve the Steam CDN URL of a case from the local catalog."""
    try:
        data = json.loads(CASES_JSON.read_text(encoding="utf-8"))
    except OSError:
        return None
    cases = data.get("cases", [])
    chosen = None
    for kase in cases:
        if kase.get("id") == case_id:
            chosen = kase
            break
    if chosen is None:
        # Fall back to the priciest gold-accent case, else the first one.
        gold = [k for k in cases if k.get("accent") == "#ffd700"]
        chosen = (gold[-1] if gold else cases[0]) if cases else None
    if not chosen or not chosen.get("image"):
        return None
    return chosen["image"] + IMAGE_SUFFIX


def fetch_case_image(url: str) -> Image.Image | None:
    request = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (compatible; KeysikBot)"}
    )
    try:
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as resp:
            data = resp.read(8 * 1024 * 1024)
        return Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        return None


def vector_case_fallback() -> Image.Image:
    """Stylized 3D crate used when the CDN render cannot be fetched."""
    scale = 4
    w, h = 64 * scale, 44 * scale
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    body_top, body_bottom = (30, 38, 54), (18, 22, 32)
    for y in range(h):
        k = y / (h - 1)
        row = tuple(int(a + (b - a) * k) for a, b in zip(body_top, body_bottom))
        draw.line([(0, y), (w, y)], fill=row + (255,))
    # Lid seam and edge highlights for a 3D read.
    draw.rectangle([0, int(h * 0.32), w - 1, int(h * 0.34)], fill=(12, 15, 22, 255))
    draw.rectangle([0, int(h * 0.34), w - 1, int(h * 0.355)], fill=(90, 100, 130, 255))
    draw.rectangle([0, 0, w - 1, h - 1], outline=(255, 194, 51, 200), width=scale)
    # Gold latch.
    lw, lh = 10 * scale, 7 * scale
    draw.rectangle(
        [(w - lw) // 2, int(h * 0.30), (w + lw) // 2, int(h * 0.30) + lh],
        fill=(255, 194, 51, 255),
        outline=(120, 70, 0, 255),
        width=scale // 2,
    )
    return img.resize((w // scale * 3, h // scale * 3), Image.LANCZOS)


def background() -> Image.Image:
    base = Image.new("RGB", (W, H))
    px = base.load()
    for y in range(H):
        k = y / (H - 1)
        row = tuple(int(a + (b - a) * k) for a, b in zip(TOP_COLOR, BOTTOM_COLOR))
        for x in range(W):
            px[x, y] = row
    return base.convert("RGBA")


def radial_glow(color: tuple[int, int, int], radius: int, max_alpha: int) -> Image.Image:
    size = radius * 2
    mask = Image.new("L", (size, size), 0)
    mpx = mask.load()
    for y in range(size):
        dy = y - radius
        for x in range(size):
            dx = x - radius
            dist = (dx * dx + dy * dy) ** 0.5 / radius
            if dist < 1.0:
                mpx[x, y] = int(max_alpha * (1.0 - dist) ** 1.6)
    glow = Image.new("RGBA", (size, size), color + (255,))
    glow.putalpha(mask)
    return glow


def diagonal_streaks() -> Image.Image:
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for i, alpha in ((-60, 16), (40, 10), (150, 14), (300, 8), (470, 12)):
        draw.line([(i, H + 40), (i + 220, -40)], fill=(255, 255, 255, alpha), width=2)
    return layer.filter(ImageFilter.GaussianBlur(1))


def gold_gradient_text(text: str, size: int) -> Image.Image:
    """Text filled with a vertical gold gradient plus a soft outer glow."""
    ref = font(size)
    bbox = ref.getbbox(text)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad = size // 3

    mask = Image.new("L", (tw + pad * 2, th + pad * 2), 0)
    ImageDraw.Draw(mask).text(
        (pad - bbox[0], pad - bbox[1]), text, font=ref, fill=255
    )

    gradient = Image.new("RGBA", mask.size)
    gpx = gradient.load()
    stops = (GOLD_LIGHT, GOLD, GOLD_DEEP)
    for y in range(mask.size[1]):
        k = y / (mask.size[1] - 1)
        if k < 0.5:
            t = k / 0.5
            a, b = stops[0], stops[1]
        else:
            t = (k - 0.5) / 0.5
            a, b = stops[1], stops[2]
        row = tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))
        for x in range(mask.size[0]):
            gpx[x, y] = row + (255,)
    gradient.putalpha(mask)

    # Soft warm glow behind the letters.
    glow = Image.new("RGBA", mask.size, (0, 0, 0, 0))
    glow.paste(Image.new("RGBA", mask.size, GOLD_DEEP + (110,)), (0, 0), mask)
    glow = glow.filter(ImageFilter.GaussianBlur(7))
    combined = Image.new("RGBA", mask.size, (0, 0, 0, 0))
    combined.alpha_composite(glow)
    combined.alpha_composite(gradient)
    return combined


def underline(width: int) -> Image.Image:
    bar = Image.new("RGBA", (width, 6), (0, 0, 0, 0))
    draw = ImageDraw.Draw(bar)
    for x in range(width):
        k = abs(x - width / 2) / (width / 2)
        alpha = int(230 * (1.0 - k) ** 0.8) + 25
        draw.line([(x, 0), (x, 5)], fill=GOLD + (min(alpha, 255),))
    return bar


def vignette(base: Image.Image) -> None:
    mask = Image.new("L", (W, H), 0)
    mpx = mask.load()
    for y in range(H):
        for x in range(W):
            dx = (x - W / 2) / (W / 2)
            dy = (y - H / 2) / (H / 2)
            mpx[x, y] = int(120 * min(1.0, (dx * dx + dy * dy) ** 0.9))
    dark = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    base.paste(Image.alpha_composite(base.crop((0, 0, W, H)), dark), (0, 0), mask)


def compose(case: Image.Image) -> Image.Image:
    base = background()
    base.alpha_composite(radial_glow(GOLD, 210, 60), (W // 2 - 210, 205 - 210))
    base.alpha_composite(radial_glow((75, 105, 255), 260, 26), (-120, -140))
    base.alpha_composite(diagonal_streaks())

    # Case artwork centered, with a soft drop shadow beneath.
    if case.width > 250 or case.height > 250:
        k = min(250 / case.width, 250 / case.height)
        case = case.resize((int(case.width * k), int(case.height * k)), Image.LANCZOS)
    case_x = W // 2 - case.width // 2
    case_y = 118 + (150 - case.height) // 2

    shadow = Image.new("RGBA", (case.width + 40, 26), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse(
        [20, 4, case.width + 20, 22], fill=(0, 0, 0, 150)
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(6))
    base.alpha_composite(shadow, (W // 2 - shadow.width // 2, case_y + case.height - 14))

    base.alpha_composite(case, (case_x, case_y))

    draw = ImageDraw.Draw(base)

    title = gold_gradient_text("КЕЙСИК", 58)
    base.alpha_composite(title, (W // 2 - title.width // 2, 12 - title.height // 4))

    bar = underline(190)
    base.alpha_composite(bar, (W // 2 - bar.width // 2, 56))

    draw.text(
        (W // 2, 86), "ОТКРЫВАЙ КЕЙСЫ • ВЫБИВАЙ НОЖИ",
        font=font(17), fill=(152, 162, 184), anchor="mm",
    )

    # Bottom CTA strip.
    strip_top = H - 44
    for y in range(strip_top, H):
        k = (y - strip_top) / (H - strip_top)
        alpha = int(26 + 46 * k)
        draw.line([(0, y), (W, y)], fill=(255, 194, 51, alpha))
    draw.line([(0, strip_top), (W, strip_top)], fill=(255, 194, 51, 110), width=2)
    draw.text(
        (W // 2, strip_top + 22), "t.me/KeysikAppBot",
        font=font(21), fill=GOLD, anchor="mm",
    )

    vignette(base)
    return base


def main() -> None:
    case_id = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CASE_ID
    url = case_image_url(case_id)
    case = fetch_case_image(url) if url else None
    if case is None:
        print(f"[make_banner] CDN render unavailable ({url!r}) — using vector crate")
        case = vector_case_fallback()
    else:
        print(f"[make_banner] Fetched case artwork: {url}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    banner = compose(case)
    banner.convert("RGB").save(OUT_PATH, format="PNG", optimize=True)
    print(f"[make_banner] Saved {OUT_PATH} ({OUT_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
