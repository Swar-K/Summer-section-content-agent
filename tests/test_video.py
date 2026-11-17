import json
import pytest
from agent import groq_brain as gb
from agent import video_reader as vr


def test_parse_video_id_accepts_common_youtube_links():
    vid = "dQw4w9WgXcQ"
    for url in (f"https://www.youtube.com/watch?v={vid}", f"https://youtu.be/{vid}?t=5", f"https://m.youtube.com/watch?v={vid}&list=x",
                f"https://www.youtube.com/shorts/{vid}", f"https://www.youtube.com/embed/{vid}", f"https://www.youtube.com/live/{vid}"):
        assert vr.parse_video_id(url) == vid
    for bad in ("https://example.com/watch?v=dQw4w9WgXcQ", "https://www.youtube.com/watch?v=short", "not a url", ""):
        with pytest.raises(ValueError):
            vr.parse_video_id(bad)


def test_timestamps_and_chapters():
    assert vr.parse_ts("1:02:03") == 3723 and vr.parse_ts("02:03") == 123 and vr.parse_ts("2:3") is None
    assert vr.fmt_ts(3723) == "1:02:03" and vr.fmt_ts(123) == "02:03"
    desc = "Intro text\n0:00 Intro\n1:30 - Unboxing\n(05:10) Test results\nthanks"
    assert [c["title"] for c in vr.parse_chapters(desc)] == ["Intro", "Unboxing", "Test results"]
    assert vr.parse_chapters("1:00 only one\n2:00 two") == []        # first chapter must be 0:00


def test_blocks_merge_caption_fragments():
    segs = [{"start": float(i * 5), "text": f"w{i}"} for i in range(20)]
    blocks = vr.to_blocks(segs, span=30)
    assert blocks[0]["start"] == 0 and len(blocks) < len(segs)
    assert vr.blocks_text(blocks).startswith("[00:00] w0")


def _stub(monkeypatch, transcript, meta=None):
    monkeypatch.setattr(vr, "fetch_transcript", lambda vid: transcript)
    monkeypatch.setattr(vr, "fetch_metadata", lambda vid, key="": meta or {"title": "", "channel": "", "description": "",
                                                                         "tags": [], "duration_seconds": 0})


def test_load_video_fallback_ladder(monkeypatch):
    url = "https://youtu.be/dQw4w9WgXcQ"
    _stub(monkeypatch, [{"start": 0.0, "text": "hello"}, {"start": 40.0, "text": "world"}], {"title": "T", "channel": "", "description": "", "tags": [], "duration_seconds": 0})
    v = vr.load_video(url)
    assert v["source"] == "transcript" and v["duration_seconds"] == 45 and v["is_short"] is True
    _stub(monkeypatch, None, {"title": "T", "channel": "", "description": "d", "tags": [], "duration_seconds": 900})
    assert vr.load_video(url)["source"] == "metadata"
    assert vr.load_video(url, notes="my script")["source"] == "notes"
    _stub(monkeypatch, None)
    assert vr.load_video(url)["source"] == "none"
    assert vr.load_video("", notes="only notes")["source"] == "notes"
    assert vr.load_video("") is None
    assert vr.load_video("https://www.youtube.com/shorts/dQw4w9WgXcQ")["is_short"] is True


def make_video(n_blocks, duration=1800):
    return {"video_id": "x", "url": "u", "title": "T", "channel": "", "description": "", "tags": [], "chapters": [],
            "duration_seconds": duration, "is_short": False, "notes": "", "source": "transcript",
            "blocks": [{"start": i * 30, "text": "word " * 60} for i in range(n_blocks)]}


ANALYSIS = {"video_summary": "A test of three draft stoppers.", "key_points": ["k1"], "products_shown": ["P"],
            "statements_in_video": ["s"],
            "moments": [{"time": "02:00", "point": "good"}, {"time": "99:99", "point": "bad time"}, {"time": "2:00:00", "point": "past the end"}],
            "clip_candidates": [{"start": "02:00", "end": "02:30", "why": "demo"}, {"start": "03:00", "end": "09:00", "why": "too long"},
                                {"start": "88:00", "end": "88:20", "why": "past the end"}]}


def test_short_video_is_read_in_one_call_and_times_are_validated(monkeypatch):
    calls = []
    monkeypatch.setattr(gb, "_chat", lambda *a, **k: calls.append(1) or json.dumps(ANALYSIS))
    out = gb.analyze_video("k", "m", make_video(4), {"tone": []}, char_limit=6000)
    assert len(calls) == 1 and out["coverage"] == "full" and out["source"] == "transcript"
    assert [m["time"] for m in out["moments"]] == ["02:00", "", ""]           # invalid/out-of-range times removed
    assert out["clip_candidates"] == [{"start": "02:00", "end": "02:30", "why": "demo"}]


def test_long_video_is_sampled_in_sections_then_merged(monkeypatch):
    calls = []
    monkeypatch.setattr(gb, "_chat", lambda *a, **k: calls.append(1) or json.dumps(ANALYSIS))
    out = gb.analyze_video("k", "m", make_video(40), {"tone": []}, char_limit=2000, max_chunks=3)
    assert len(calls) == 4                                                       # 3 sections + 1 merge
    assert out["coverage"].startswith("sampled 3 of")


def test_unreadable_video_makes_no_ai_call(monkeypatch):
    monkeypatch.setattr(gb, "_chat", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no call expected")))
    v = {**make_video(0), "source": "none", "title": "Only a title"}
    out = gb.analyze_video("k", "m", v, {"tone": []})
    assert out["coverage"] == "none" and out["video_summary"] == "Only a title"
