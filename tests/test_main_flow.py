import json
from pathlib import Path
from agent import main as m
from agent.config import Settings

ROOT = Path(__file__).resolve().parents[1]


def make_settings(tmp_path, **kw):
    opts = {"make_videos": False, "boards_path": tmp_path / "boards.json", **kw}
    return Settings("key", "model", "https://example.com/post/", "", "gpt-image-1", False, 10, 9000,
                    tmp_path / "out", ROOT / "brand/summer_section.json", drafts_dir=tmp_path / "drafts", **opts)


ARTICLE = {"url": "https://example.com/post/", "submitted_url": "https://example.com/post/", "title": "Best Draft Stoppers",
           "headings": [], "text": "x" * 500, "image_urls": [], "description": ""}

VIDEO = {"video_id": "abcdefghijk", "url": "https://www.youtube.com/watch?v=abcdefghijk", "title": "Draft stopper test",
         "source": "transcript", "thumbnail_urls": [], "frame_urls": [], "blocks": [], "notes": "", "duration_seconds": 600,
         "chapters": [{"start": 0, "title": "Intro"}], "description": "d", "tags": []}
ANALYSIS = {"video_summary": "A test of three draft stoppers.", "key_points": ["k"], "moments": [{"time": "", "point": "gap test"}],
            "products_shown": [], "statements_in_video": [], "clip_candidates": [], "source": "transcript",
            "coverage": "full", "duration_seconds": 600}
SEEN = {}


def fake_plan(*a, **k):
    SEEN["plan_kwargs"], SEEN["article"] = k, a[2]
    n = a[4] if len(a) > 4 else 10
    return {"article_analysis": {"topic": "t"}, "keyword_suggestions": {"phrases": []}, "board_suggestions": ["Home"],
            "pins": [{"number": i, "angle": "a", "headline": f"Pin headline {i}", "subheadline": "", "title": f"T{i}",
                      "description": "D", "board": "Home" if i % 2 else "Winter Tips", "keywords": [], "hashtags": [],
                      "alt_text": f"alt {i}", "new_board_description": "Cold weather ideas"} for i in range(1, n + 1)]}


def fake_posts(*a, **k):
    return {"facebook": {"headline": "Stop drafts the easy way",
                         "tips": ["Measure the gap under the door first", "Pick a stopper that fits snugly", "Check it every season"],
                         "post": "Cold air sneaking under the door? Which room is draftiest?", "hashtags": ["#HomeTips"]},
            "instagram": {"headline": "The test that surprised us",
                          "tips": ["The video shows the gap test", "Snug fit beats price", "Check seals twice a year"],
                          "caption": "Draft test in 20 seconds.\nFull guide: link in bio", "hashtags": ["#Home", "#Draft", "#Review", "#Tips", "#Winter"],
                          "alt_text": "Card with three draft stopper tips"}}


def fake_scripts(*a, **k):
    scene = {"visual": "door gap close-up", "voiceover": "Measure first", "clip": ""}
    return {"reel": {"hook": "Feel that draft?", "scenes": [scene] * 3, "on_screen_text": ["Measure first"], "cta": "Link in bio"},
            "short": {"title": "Is this draft stopper worth it?", "hook": "Wait before you buy", "scenes": [scene] * 3,
                      "cta": "Full guide in the description", "description": "Quick look.", "pinned_comment": "Which door?",
                      "on_screen_text": []}}


def patch_all(monkeypatch, tmp_path, video=True, video_source="transcript", article=True, **kw):
    s = make_settings(tmp_path, **kw)
    if not article:
        s.article_url = ""
    if video:
        s.video_url = VIDEO["url"]

    def no_article(url):
        if not article:
            raise AssertionError("extract_article must not be called in video-only mode")
        return ARTICLE
    monkeypatch.setattr(m, "load_settings", lambda: s)
    monkeypatch.setattr(m, "extract_article", no_article)
    monkeypatch.setattr(m, "load_video", lambda *a, **k: {**VIDEO, "source": video_source})
    monkeypatch.setattr(m, "analyze_video", lambda *a, **k: {**ANALYSIS, "source": video_source})
    monkeypatch.setattr(m, "analyze_and_plan", fake_plan)
    monkeypatch.setattr(m, "plan_posts", fake_posts)
    monkeypatch.setattr(m, "plan_video_scripts", fake_scripts)
    monkeypatch.setattr(m, "pick_unused_article", lambda *a: (_ for _ in ()).throw(AssertionError("no auto-pick expected")))
    return s


def test_article_plus_video_writes_everything(tmp_path, monkeypatch):
    patch_all(monkeypatch, tmp_path)
    assert m.run() == 0
    out = tmp_path / "out" / "best-draft-stoppers"
    names = {p.name for p in out.iterdir()}
    assert {f"pin_{i:02d}.png" for i in range(1, 11)} <= names
    for f in ("article_analysis.json", "video_analysis.json", "pinterest_keyword_suggestions.json", "pin_strategy.json",
              "pinterest_campaign.json", "publishing_queue.json", "quality_report.json", "CAMPAIGN_SUMMARY.md",
              "facebook_card.png", "facebook_post.json", "instagram_card.png", "instagram_post.json",
              "instagram_reel_script.md", "youtube_short_script.md", "video_scripts.json", "boards_report.json",
              "editor.html"):
        assert f in names, f
    q = json.loads((out / "quality_report.json").read_text())
    assert q["passed"] is True and len(q["checks"]) == 10
    camp = json.loads((out / "pinterest_campaign.json").read_text())
    assert camp["source_kind"] == "both" and camp["cta_label"] == "READ THE FULL GUIDE" and camp["draft_id"]
    assert all(p["style"]["template"] in (1, 2, 3) and p["alt_text"] for p in camp["pins"])
    assert "Watch the video: https://www.youtube.com/watch?v=abcdefghijk" in json.loads((out / "facebook_post.json").read_text())["message"]


def test_review_draft_has_both_cards_and_tracked_links(tmp_path, monkeypatch):
    patch_all(monkeypatch, tmp_path)
    m.run()
    drafts = list((tmp_path / "drafts").iterdir())
    assert len(drafts) == 1
    d = json.loads((drafts[0] / "draft.json").read_text())
    assert d["status"] == "pending" and "utm_source=facebook" in d["facebook_message"]
    issue = (drafts[0] / "issue.md").read_text()
    assert issue.startswith(f"<!-- draft-id: {drafts[0].name} -->")
    for needle in ("utm_source=pinterest", "utm_content=pin_01", "utm_source=youtube", "Instagram post", "YouTube Short script",
                   "article + video", "Alt text: alt 1", "Board suggestions"):
        assert needle in issue, needle
    assert (drafts[0] / "facebook_card.png").exists() and (drafts[0] / "instagram_card.png").exists()


def test_article_only_mode(tmp_path, monkeypatch):
    patch_all(monkeypatch, tmp_path, video=False)
    assert m.run() == 0
    out = tmp_path / "out" / "best-draft-stoppers"
    q = json.loads((out / "quality_report.json").read_text())
    assert any("No video was provided" in n for n in q["notes"])
    assert json.loads((out / "pinterest_campaign.json").read_text())["source_kind"] == "article"
    assert "Watch the video" not in json.loads((out / "facebook_post.json").read_text())["message"]
    assert SEEN["plan_kwargs"]["video_analysis"] is None


def test_video_only_mode_links_to_the_video(tmp_path, monkeypatch):
    patch_all(monkeypatch, tmp_path, article=False)
    assert m.run() == 0
    out = tmp_path / "out" / "draft-stopper-test"
    camp = json.loads((out / "pinterest_campaign.json").read_text())
    assert camp["source_kind"] == "video" and camp["cta_label"] == "WATCH THE FULL VIDEO"
    assert camp["article_url"] == VIDEO["url"] and camp["pins"][0]["destination_url"].startswith(VIDEO["url"])
    assert "utm_source=pinterest" in camp["pins"][0]["destination_url"]
    fb = json.loads((out / "facebook_post.json").read_text())["message"]
    assert "Watch the full video: " + VIDEO["url"] in fb and fb.count("youtube.com") == 1
    assert SEEN["article"]["source_kind"] == "video" and "gap test" in SEEN["article"]["text"]
    assert any("Video-only run" in n for n in camp["notes"])


def test_video_only_uses_destination_url_when_given(tmp_path, monkeypatch):
    patch_all(monkeypatch, tmp_path, article=False, destination_url="https://summersection.com/draft-stoppers/")
    assert m.run() == 0
    out = tmp_path / "out" / "draft-stopper-test"
    camp = json.loads((out / "pinterest_campaign.json").read_text())
    assert camp["article_url"] == "https://summersection.com/draft-stoppers/"
    assert camp["cta_label"] == "READ THE FULL GUIDE"                     # a site page, so the wording says guide
    assert "Read the full guide: https://summersection.com" in json.loads((out / "facebook_post.json").read_text())["message"]


def test_video_only_with_unreadable_video_stops_with_a_clear_error(tmp_path, monkeypatch, capsys):
    patch_all(monkeypatch, tmp_path, article=False, video_source="none")
    try:
        m.main()
    except SystemExit as e:
        assert e.code == 1
    assert "nothing to build from" in capsys.readouterr().err


def test_boards_are_matched_and_new_ones_flagged(tmp_path, monkeypatch):
    (tmp_path / "boards.json").write_text(json.dumps({"boards": [{"name": "Home"}, {"name": "Kitchen"}]}))
    patch_all(monkeypatch, tmp_path)
    assert m.run() == 0
    out = tmp_path / "out" / "best-draft-stoppers"
    camp = json.loads((out / "pinterest_campaign.json").read_text())
    status = {p["number"]: (p["board"], p["board_status"]) for p in camp["pins"]}
    assert status[1] == ("Home", "existing") and status[2] == ("Winter Tips", "new")
    rep = json.loads((out / "boards_report.json").read_text())
    assert rep["mode"] == "matched" and rep["new"][0]["name"] == "Winter Tips" and rep["new"][0]["description"] == "Cold weather ideas"
    assert [b["name"] for b in SEEN["plan_kwargs"]["boards"]] == ["Home", "Kitchen"]
    assert "NEW board: create it first" in next((tmp_path / "drafts").iterdir()).joinpath("issue.md").read_text()


def test_videos_are_built_from_pins_and_scripts(tmp_path, monkeypatch):
    patch_all(monkeypatch, tmp_path, make_videos=True)
    calls = {}

    def fake_make(out, pin_files, scripts, brand, **k):
        calls.update(pins=len(pin_files), scripts=sorted(scripts), cta=k["cta_label"], voice=k["voice"])
        (out / "video_pin.mp4").write_bytes(b"x")
        return {"videos": {"video_pin.mp4": {"seconds": 16, "aspect": "2:3", "voiceover": False},
                           "instagram_reel.mp4": {"error": "boom"}}, "notes": ["Reel failed"]}
    monkeypatch.setattr(m, "make_all_videos", fake_make)
    assert m.run() == 0
    assert calls == {"pins": 10, "scripts": ["reel", "short"], "cta": "READ THE FULL GUIDE", "voice": "en-US-AndrewNeural"}
    out = tmp_path / "out" / "best-draft-stoppers"
    summary = (out / "CAMPAIGN_SUMMARY.md").read_text()
    assert "`video_pin.mp4`: 16 s" in summary and "failed (boom)" in summary
    issue = next((tmp_path / "drafts").iterdir()).joinpath("issue.md").read_text()
    assert "- `video_pin.mp4`" in issue and "instagram_reel.mp4" not in issue.split("Videos and editor")[1]
    assert "Reel failed" in issue


def test_pinterest_only_mode_creates_no_draft_or_social_files(tmp_path, monkeypatch):
    patch_all(monkeypatch, tmp_path, social_outputs=False)
    assert m.run() == 0
    out = tmp_path / "out" / "best-draft-stoppers"
    assert not (out / "facebook_card.png").exists() and not (out / "instagram_card.png").exists()
    assert not (tmp_path / "drafts").exists() and (out / "editor.html").exists()


def test_blank_everything_auto_picks_the_next_unused_article(tmp_path, monkeypatch):
    s = patch_all(monkeypatch, tmp_path, video=False, wp_site_url="https://example.com")
    s.article_url = ""
    seen = {}
    monkeypatch.setattr(m, "pick_unused_article", lambda site, cat, used: seen.setdefault("url", "https://example.com/post/"))
    assert m.run() == 0 and seen["url"] == "https://example.com/post/"


def test_thumbnails_are_mixed_into_pin_backgrounds():
    imgs = m.with_video_thumbnails(["a1", "a2", "a3", "a4", "a5"], ["T"])
    assert imgs[0] == "T" and imgs[3] == "T" and imgs[6] == "T"
    assert m.with_video_thumbnails(["a1"], []) == ["a1"]


def test_missing_groq_key_gives_clear_error(tmp_path, monkeypatch, capsys):
    s = make_settings(tmp_path)
    s.groq_api_key = ""
    monkeypatch.setattr(m, "load_settings", lambda: s)
    try:
        m.main()
    except SystemExit as e:
        assert e.code == 1
    assert "GROQ_API_KEY" in capsys.readouterr().err
