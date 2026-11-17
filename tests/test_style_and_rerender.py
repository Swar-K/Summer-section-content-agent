import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageColor
from agent import image_designer as idz
from agent import main as m
from agent import rerender
from agent.image_designer import effective_style, render_pin
from test_main_flow import patch_all

BRAND = json.loads((Path(__file__).resolve().parents[1] / "brand/summer_section.json").read_text())


def test_style_overrides_change_the_render(tmp_path):
    pin = {"number": 1, "headline": "Hello there", "subheadline": ""}
    render_pin(pin, BRAND, tmp_path / "a.png", [])
    render_pin({**pin, "style": {"template": 3, "accent": "blush"}}, BRAND, tmp_path / "b.png", [])
    band = Image.open(tmp_path / "b.png").convert("RGB").getpixel((500, 100))
    assert band == ImageColor.getrgb(BRAND["colors"]["blush"])
    render_pin({**pin, "style": {"text_scale": 1.3}}, BRAND, tmp_path / "c.png", [])
    render_pin({**pin, "style": {"text_scale": 0.7}}, BRAND, tmp_path / "d.png", [])
    assert (tmp_path / "c.png").read_bytes() != (tmp_path / "d.png").read_bytes() != (tmp_path / "a.png").read_bytes()
    meta = render_pin({**pin, "style": {"template": 2}}, BRAND, tmp_path / "e.png", [])
    assert meta["template_variant"] == 2 and meta["style"]["background"] == "none"


def test_effective_style_clamps_bad_values():
    s = effective_style({"number": 2, "style": {"template": 9, "overlay": 999, "text_scale": "x", "base": "nope", "accent": "blush", "bogus": 1}})
    assert s["template"] == 3 and s["overlay"] == 255 and s["text_scale"] == 1.0 and s["base"] == "cream" and s["accent"] == "blush"
    assert "bogus" not in s


def test_background_is_saved_once_and_reused_without_downloading(tmp_path, monkeypatch):
    monkeypatch.setattr(idz, "_download_image", lambda url, min_side=500: Image.new("RGB", (800, 1200), (10, 120, 200)))
    pin = {"number": 1, "headline": "Hello there", "subheadline": "sub"}
    meta = render_pin(pin, BRAND, tmp_path / "a.png", ["http://x/i.jpg"], assets_dir=tmp_path / "assets")
    assert meta["background_file"] == "bg_01.jpg" and (tmp_path / "assets/bg_01.jpg").exists()
    assert meta["style"]["background"] == "asset:bg_01.jpg" and meta["background_source"] == "article_image"
    monkeypatch.setattr(idz, "_download_image", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no download expected")))
    meta2 = render_pin({**pin, "style": meta["style"]}, BRAND, tmp_path / "b.png", [], assets_dir=tmp_path / "assets")
    a, b = (np.asarray(Image.open(tmp_path / n).convert("RGB"), dtype=float) for n in ("a.png", "b.png"))
    assert meta2["background_source"] == "asset" and np.abs(a - b).mean() < 3
    gone = render_pin({**pin, "style": {"background": "asset:missing.jpg"}}, BRAND, tmp_path / "c.png", [], assets_dir=tmp_path / "assets")
    assert gone["style"]["background"] == "none"                          # a missing asset falls back to the brand colour


# ---------------------------------------------------------------- re-render from edits.json
def build_campaign(tmp_path, monkeypatch):
    patch_all(monkeypatch, tmp_path)
    assert m.run() == 0
    return tmp_path / "out" / "best-draft-stoppers"


def test_rerender_applies_pin_card_and_text_edits(tmp_path, monkeypatch):
    out = build_campaign(tmp_path, monkeypatch)
    before = (out / "pin_01.png").read_bytes(), (out / "pin_02.png").read_bytes()
    edits = {"slug": "best-draft-stoppers",
             "pins": {"1": {"headline": "Edited headline", "board": "winter tips", "style": {"template": 3, "accent": "blush"}}},
             "facebook": {"headline": "New Facebook headline", "post": "New post text?"},
             "instagram": {"caption": "New caption", "band": "sage"}}
    res = rerender.apply_edits(out, edits, BRAND, [{"name": "Winter Tips"}], tmp_path / "drafts", rebuild_videos=False)
    assert res["changed_pins"] == [1] and res["facebook"] and res["instagram"] and res.get("draft_updated")
    assert (out / "pin_01.png").read_bytes() != before[0] and (out / "pin_02.png").read_bytes() == before[1]
    camp = json.loads((out / "pinterest_campaign.json").read_text())
    p1 = camp["pins"][0]
    assert (p1["headline"], p1["board"], p1["board_status"]) == ("Edited headline", "Winter Tips", "existing")
    assert p1["style"]["template"] == 3 and p1["style"]["accent"] == "blush"
    fb = json.loads((out / "facebook_post.json").read_text())
    assert "New post text?" in fb["message"] and "utm_source=facebook" in fb["message"] and fb["content"]["headline"] == "New Facebook headline"
    draft = json.loads(next((tmp_path / "drafts").iterdir()).joinpath("draft.json").read_text())
    assert draft["facebook_message"] == fb["message"]
    assert "New caption" in json.loads((out / "instagram_post.json").read_text())["caption"]
    assert "Edited headline" in (out / "editor.html").read_text()
    assert "Board: Winter Tips (existing board)" in (out / "CAMPAIGN_SUMMARY.md").read_text()
    assert json.loads((out / "edits_applied.json").read_text())["result"]["changed_pins"] == [1]
    assert json.loads((out / "boards_report.json").read_text())["existing"][0]["board"] == "Winter Tips"


def test_rerender_rejects_edits_for_another_campaign(tmp_path, monkeypatch):
    out = build_campaign(tmp_path, monkeypatch)
    try:
        rerender.apply_edits(out, {"slug": "some-other-campaign", "pins": {}}, BRAND, [], None, False)
        assert False, "should have raised"
    except ValueError as e:
        assert "some-other-campaign" in str(e)


def test_rerender_skips_unknown_pins_and_reports_clipped_text(tmp_path, monkeypatch):
    out = build_campaign(tmp_path, monkeypatch)
    res = rerender.apply_edits(out, {"pins": {"99": {"headline": "x"}, "2": {"headline": "word " * 80}}}, BRAND, [], None, False)
    assert res["changed_pins"] == [2]
    assert any("Pin 99" in i for i in res["issues"]) and any("Pin 2" in i and "cut off" in i for i in res["issues"])


def test_rerender_command_line(tmp_path, monkeypatch, capsys):
    out = build_campaign(tmp_path, monkeypatch)
    f = tmp_path / "edits.json"
    f.write_text(json.dumps({"slug": out.name, "pins": {"3": {"title": "A better title"}}}))
    code = rerender.main(["--campaign", str(out), "--edits", str(f), "--drafts", str(tmp_path / "drafts"), "--no-videos"])
    assert code == 0 and "Re-rendered pins [3]" in capsys.readouterr().out
    assert json.loads((out / "pinterest_campaign.json").read_text())["pins"][2]["title"] == "A better title"
    assert rerender.main(["--campaign", str(tmp_path / "nope"), "--edits", str(f)]) == 1
