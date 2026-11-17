from __future__ import annotations
from pathlib import Path
from PIL import Image, ImageDraw
from .image_designer import _clean, _font, _fit_text

W, H = 1080, 1350


def render_card(content: dict, brand: dict, destination: Path, band: str = "sage",
                footer: str = "READ THE FULL GUIDE") -> dict:
    """1080x1350 (4:5) tip card in the Summer Section brand colours: headline plus three numbered points.
    `band` picks the accent colour so the Facebook and Instagram cards do not look identical."""
    colors = brand["colors"]
    ink, muted = colors["ink"], colors["muted"]
    accent = colors.get(band, colors["sage"])
    img = Image.new("RGB", (W, H), colors["ivory"])
    d = ImageDraw.Draw(img)
    margin = 80
    clipped = False

    d.rectangle((0, 0, W, 150), fill=accent)
    d.text((margin, 56), str(brand.get("brand", "Summer Section")).upper(), font=_font(32, True), fill=ink)

    headline = _clean(content.get("headline")) or "Helpful buying tips"
    font, size, lines, c = _fit_text(d, headline, [84, 72, 62, 54], W - 2 * margin, 3, True)
    clipped = clipped or c
    y = 205
    for line in lines:
        d.text((margin, y), line, font=font, fill=ink)
        y += int(size * 1.24)

    top = 560
    for i, tip in enumerate([_clean(t) for t in content.get("tips", [])][:3], 1):
        d.rounded_rectangle((60, top, W - 60, top + 190), radius=32, fill=colors["cream"],
                            outline=colors["champagne"], width=3)
        d.ellipse((92, top + 55, 172, top + 135), fill=accent)
        nf = _font(44, True)
        num = str(i)
        box = d.textbbox((0, 0), num, font=nf)
        d.text((132 - (box[2] - box[0]) / 2 - box[0], top + 95 - (box[3] - box[1]) / 2 - box[1]),
               num, font=nf, fill=ink)
        tf, ts, tlines, c = _fit_text(d, tip, [38, 34, 30, 27], 785, 3, False)
        clipped = clipped or c
        total = len(tlines) * int(ts * 1.3)
        ty = top + (190 - total) / 2
        for line in tlines:
            d.text((205, ty), line, font=tf, fill=ink)
            ty += int(ts * 1.3)
        top += 218

    domain = str(brand.get("display_domain") or "summersection.com")
    d.line((margin, 1235, W - margin, 1235), fill=colors["champagne"], width=3)
    d.text((margin, 1255), footer, font=_font(27), fill=ink)
    d.text((margin, 1295), domain, font=_font(24), fill=muted)

    destination.parent.mkdir(parents=True, exist_ok=True)
    img.save(destination)
    return {"path": str(destination), "width": W, "height": H, "clipped": clipped}


def render_facebook_card(block: dict, brand: dict, destination: Path, footer: str = "READ THE FULL GUIDE") -> dict:
    return render_card(block, brand, destination, block.get("band") or "sage", footer)


def render_instagram_card(block: dict, brand: dict, destination: Path,
                          footer: str = "FULL GUIDE: LINK IN BIO") -> dict:
    return render_card(block, brand, destination, block.get("band") or "blush", footer)
