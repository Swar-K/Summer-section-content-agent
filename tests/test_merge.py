import json
from pathlib import Path
from PIL import Image
from agent import drafts as dr
from agent import groq_brain as gb
from agent import wp_picker
from agent.facebook_card import render_facebook_card, render_instagram_card
from agent.links import add_utm, norm_url
from agent.quality_checker import check_facebook, check_instagram, check_scripts

BRAND = json.loads((Path(__file__).resolve().parents[1] / "brand/summer_section.json").read_text())
FB = {"headline": "Stop drafts the easy way", "tips": ["Measure the gap first", "Pick a snug stopper", "Check it each season"],
      "post": "Cold air under the door? Which room is draftiest?", "hashtags": ["#Home", "Draft Stopper"]}
IG = {"headline": "The test that surprised us", "tips": ["Gap test", "Snug fit", "Seasonal check"],
      "caption": "Quick test.\nFull guide: link in bio", "hashtags": ["#a", "b c"], "alt_text": "Three tips"}
SCENE = {"visual": "v", "voiceover": "vo", "clip": ""}
SCRIPTS = {"reel": {"hook": "Feel that draft?", "scenes": [SCENE] * 3, "cta": "c"},
           "short": {"title": "Worth it?", "hook": "Wait before you buy", "scenes": [SCENE] * 3, "cta": "c",
                     "description": "d", "pinned_comment": "p"}}


def test_utm_and_url_normalising():
    u = add_utm("https://x.com/a/?p=1", "pinterest", "camp", "pin_01")
    assert "p=1" in u and "utm_source=pinterest" in u and "utm_content=pin_01" in u
    assert norm_url("HTTPS://X.com/a/?utm_source=z") == "https://x.com/a"


def test_draft_id_and_used_urls(tmp_path):
    did = dr.new_draft_id("https://x.com/a/")
    assert dr.DRAFT_ID_RE.fullmatch(did)
    folder = tmp_path / did
    folder.mkdir()
    (folder / "draft.json").write_text(json.dumps({"article_url": "https://x.com/a/", "submitted_url": "https://x.com/a?x=1"}))
    assert dr.used_urls(tmp_path) == {"https://x.com/a"}


def test_message_builders():
    msg = dr.build_facebook_message(FB, "Disclosure line.", "https://x.com/a?utm_source=facebook", "https://youtu.be/abc")
    assert "Disclosure line." in msg and "Read the full guide: https://x.com/a?utm_source=facebook" in msg
    assert "Watch the video: https://youtu.be/abc" in msg and msg.endswith("#Home #DraftStopper")
    cap = dr.build_instagram_caption(IG, "")
    assert "link in bio" in cap and "http" not in cap and cap.endswith("#a #bc")
    assert "Clip from your video" in dr.build_reel_md("T", {**SCRIPTS["reel"], "scenes": [{**SCENE, "clip": "01:00-01:20"}] * 3}, "l")


def test_cards_render_at_size_and_differ(tmp_path):
    p1, p2 = tmp_path / "fb.png", tmp_path / "ig.png"
    m1, m2 = render_facebook_card(FB, BRAND, p1), render_instagram_card(IG, BRAND, p2)
    assert Image.open(p1).size == (1080, 1350) == Image.open(p2).size
    assert m1["clipped"] is False and m2["clipped"] is False
    assert p1.read_bytes() != p2.read_bytes()
    assert check_facebook(p1, FB, "message", "https://x.com/a", m1)["passed"] is True
    assert check_instagram(p2, IG, "caption #a", m2)["passed"] is True


def test_checks_flag_problems(tmp_path):
    p = tmp_path / "x.png"
    Image.new("RGB", (500, 500)).save(p)
    r = check_facebook(p, {"headline": "", "tips": ["a"], "post": ""}, "m", "nope", {"clipped": True})
    assert r["passed"] is False and len(r["issues"]) >= 5
    r = check_instagram(p, {"headline": "h", "tips": ["a", "b", "c"], "caption": "", "alt_text": ""}, "#" * 31)
    assert r["passed"] is False
    same = {"reel": {"hook": "Same", "scenes": [SCENE] * 3}, "short": {"title": "t", "hook": "same", "scenes": [SCENE] * 3}}
    assert any("same hook" in i for i in check_scripts(same)["issues"])
    assert check_scripts(SCRIPTS)["passed"] is True


def test_picker_skips_used_articles(monkeypatch):
    class R:
        def raise_for_status(self): pass
        def json(self): return [{"link": "https://x.com/new/"}, {"link": "https://x.com/old/"}]
    monkeypatch.setattr(wp_picker.requests, "get", lambda *a, **k: R())
    assert wp_picker.pick_unused_article("https://x.com", "", {"https://x.com/new"}) == "https://x.com/old/"
    assert wp_picker.pick_unused_article("https://x.com", "", {"https://x.com/new", "https://x.com/old"}) == ""


def test_plan_posts_validates_and_retries(monkeypatch):
    good = {"facebook": FB, "instagram": IG}
    replies = [json.dumps({"facebook": {**FB, "tips": ["only one"]}, "instagram": IG}), json.dumps(good)]   # one retry is allowed
    monkeypatch.setattr(gb, "_chat", lambda *a, **k: replies.pop(0))
    out = gb.plan_posts("k", "m", {"title": "T"}, {"article_analysis": {}}, None, {"tone": ["helpful"]})
    assert out["facebook"]["headline"] == FB["headline"] and len(out["instagram"]["tips"]) == 3 and not replies


def test_plan_video_scripts_removes_invented_clip_ranges(monkeypatch):
    raw = json.loads(json.dumps(SCRIPTS))
    raw["reel"]["scenes"][0]["clip"] = "01:00-01:20"        # valid, inside a 10 minute video
    raw["reel"]["scenes"][1]["clip"] = "99:00-99:30"        # beyond the video
    raw["short"]["scenes"][0]["clip"] = "not a range"
    monkeypatch.setattr(gb, "_chat", lambda *a, **k: json.dumps(raw))
    va = {"source": "transcript", "duration_seconds": 600, "clip_candidates": [], "video_summary": "s"}
    out = gb.plan_video_scripts("k", "m", {"title": "T"}, {"article_analysis": {}}, va, {"tone": []}, {"facebook": FB, "instagram": IG})
    assert out["reel"]["scenes"][0]["clip"] == "01:00-01:20" and out["reel"]["scenes"][1]["clip"] == ""
    assert out["short"]["scenes"][0]["clip"] == ""
    out = gb.plan_video_scripts("k", "m", {"title": "T"}, {"article_analysis": {}}, None, {"tone": []}, {"facebook": FB, "instagram": IG})
    assert all(s["clip"] == "" for s in out["reel"]["scenes"])
