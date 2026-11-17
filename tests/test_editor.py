import base64
import io
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from agent.editor_builder import build_editor
from agent.facebook_card import render_facebook_card, render_instagram_card
from agent.image_designer import render_pin

BRAND = json.loads((Path(__file__).resolve().parents[1] / "brand/summer_section.json").read_text())
FB = {"headline": "Stop drafts the easy way", "tips": ["Measure the gap under the door first", "Pick a stopper that fits", "Check it every season"], "post": "p", "hashtags": ["#a"]}
IG = {"headline": "The 20-second gap test", "tips": ["A card slid under the gap", "Snug fit beats low price", "Re-check each season"], "caption": "c", "hashtags": [], "alt_text": "alt"}


def make_campaign(root: Path):
    out = root / "demo-campaign"
    (out / "assets").mkdir(parents=True)
    photo = Image.new("RGB", (1200, 1600))
    d = ImageDraw.Draw(photo)
    for y in range(1600):
        d.line([(0, y), (1200, y)], fill=(40 + y // 12, 90 + y // 20, 140 - y // 25))
    d.ellipse((300, 400, 900, 1000), fill=(230, 200, 120))
    photo.save(out / "assets" / "bg_02.jpg", quality=90)
    pins = [
        {"number": 1, "headline": "Stop door drafts the easy way", "subheadline": "What to check before you buy", "title": "t", "description": "d", "board": "Home"},
        {"number": 2, "headline": "How to stop cold air coming in under every exterior door this winter", "subheadline": "", "style": {"background": "asset:bg_02.jpg"}, "title": "t", "description": "d", "board": "Home"},
        {"number": 3, "headline": "Three mistakes", "subheadline": "Avoid these", "style": {"template": 1, "text_scale": 1.2, "accent": "blush", "base": "cream"}, "title": "t", "description": "d", "board": "Home"},
        {"number": 4, "headline": "Photo on template three", "subheadline": "Lighter overlay", "style": {"template": 3, "background": "asset:bg_02.jpg", "overlay": 60}, "title": "t", "description": "d", "board": "Home"},
    ]
    for p in pins:
        p["style"] = render_pin(p, BRAND, out / f"pin_{p['number']:02d}.png", [], assets_dir=out / "assets")["style"]
    render_facebook_card(FB, BRAND, out / "facebook_card.png")
    render_instagram_card(IG, BRAND, out / "instagram_card.png")
    path = build_editor(out, BRAND, {"pins": pins}, [{"name": "Home Cooling"}], facebook=FB, instagram=IG)
    return out, pins, path


def mean_diff(png_bytes, ref):
    a = np.asarray(Image.open(io.BytesIO(png_bytes)).convert("RGB"), dtype=float)
    b = np.asarray(Image.open(ref).convert("RGB"), dtype=float)
    return None if a.shape != b.shape else float(np.abs(a - b).mean())


def test_editor_html_is_self_contained_and_escapes_data(tmp_path):
    out, pins, path = make_campaign(tmp_path)
    html = path.read_text(encoding="utf-8")
    assert "__FONT_CSS__" not in html and "/*__DATA__*/" not in html and "data:image/jpeg;base64," in html
    assert "http://" not in html.replace("http://www.w3.org", "") and "src=\"http" not in html
    pins[0]["headline"] = "</script><b>tricky</b>"
    path = build_editor(out, BRAND, {"pins": pins}, [], facebook=None, instagram=None)
    assert "</script><b>" not in path.read_text(encoding="utf-8")


def test_browser_rendering_matches_the_python_renderer_and_exports_edits(tmp_path):
    try:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.launch()
    except Exception:
        return                                                    # no headless browser available: skip
    try:
        out, pins, path = make_campaign(tmp_path)
        page = browser.new_page(viewport={"width": 1400, "height": 950})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(path.as_uri())
        page.wait_for_function("window.__editorReady === true", timeout=20000)
        for p in pins:
            url = page.evaluate("(n) => { const it = window.__editor.items.find(i => i.kind==='pin' && i.data.number===n); const c = document.createElement('canvas'); window.__editor.renderPin(c, it.data); return c.toDataURL('image/png'); }", p["number"])
            diff = mean_diff(base64.b64decode(url.split(",")[1]), out / f"pin_{p['number']:02d}.png")
            assert diff is not None and diff < 3, (p["number"], diff)
        for kind, ref in (("fb", "facebook_card.png"), ("ig", "instagram_card.png")):
            url = page.evaluate("(k) => { const it = window.__editor.items.find(i => i.kind===k); const c = document.createElement('canvas'); window.__editor.renderCard(c, it.data, k==='fb' ? window.__editor.DATA.footers.fb : window.__editor.DATA.footers.ig); return c.toDataURL('image/png'); }", kind)
            diff = mean_diff(base64.b64decode(url.split(",")[1]), out / ref)
            assert diff is not None and diff < 3, (kind, diff)
        # typing in the form marks the item as edited and shows up in the exported edits
        page.fill("#panel textarea >> nth=0", "Typed in the box")
        page.select_option("#panel select >> nth=0", "3")
        edits = page.evaluate("() => window.__editor.editsObject()")
        assert edits["slug"] == "demo-campaign" and edits["pins"]["1"]["headline"] == "Typed in the box"
        assert edits["pins"]["1"]["style"]["template"] == 3 and "facebook" not in edits
        page.click(".thumb[data-i='4']")
        assert page.evaluate("() => window.__editor.items[4].kind") == "fb"
        assert errors == []
    finally:
        browser.close()
        pw.stop()
