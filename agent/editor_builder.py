"""Writes editor.html next to a campaign's files: a single self-contained page (no server, works offline)
for editing pin text, look, boards and the Facebook/Instagram cards, then downloading PNGs or an edits.json."""
from __future__ import annotations
import base64
import json
from pathlib import Path

TEMPLATE = Path(__file__).with_name("editor_template.html")
FONTS = {700: ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
         400: ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]}


def _font_css() -> str:
    css = []
    for weight, paths in FONTS.items():
        for p in paths:
            if Path(p).is_file():
                b64 = base64.b64encode(Path(p).read_bytes()).decode()
                css.append('@font-face{font-family:"EditorSans";font-weight:%d;src:url(data:font/ttf;base64,%s) format("truetype")}'
                           % (weight, b64))
                break
    return "\n".join(css)


def _data_uri(path: Path) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode()


def build_editor(out_dir: Path, brand: dict, campaign: dict, boards: list[dict], *, facebook: dict | None = None,
                 instagram: dict | None = None, cta_label: str = "READ THE FULL GUIDE",
                 fb_footer: str = "READ THE FULL GUIDE", ig_footer: str = "FULL GUIDE: LINK IN BIO") -> Path:
    keep = ("number", "headline", "subheadline", "title", "description", "board", "board_status", "alt_text", "style")
    pins = [{k: p.get(k, "" if k != "style" else {}) for k in keep} for p in campaign["pins"]]
    backgrounds = {p.name: _data_uri(p) for p in sorted((out_dir / "assets").glob("bg_*.jpg"))}

    def block(b, band):
        if not b:
            return None
        return {**{k: b.get(k) for k in ("headline", "tips", "post", "caption", "hashtags", "alt_text") if k in b},
                "band": b.get("band", band)}

    data = {"slug": out_dir.name,
            "brand": {"name": brand.get("brand", "Summer Section"),
                      "domain": brand.get("display_domain") or "summersection.com", "colors": brand["colors"]},
            "cta_label": cta_label, "footers": {"fb": fb_footer, "ig": ig_footer},
            "pins": pins, "boards": [b["name"] for b in boards], "backgrounds": backgrounds,
            "facebook": block(facebook, "sage"), "instagram": block(instagram, "blush")}
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", payload).replace("__FONT_CSS__", _font_css())
    path = out_dir / "editor.html"
    path.write_text(html, encoding="utf-8")
    return path
