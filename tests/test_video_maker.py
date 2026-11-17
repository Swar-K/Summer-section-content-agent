import subprocess
from pathlib import Path
from PIL import Image
from agent import video_maker as vm

BRAND = {"brand": "Summer Section", "display_domain": "summersection.com",
         "colors": {"ivory": "#F5EFE6", "cream": "#EFE5D7", "champagne": "#D8C7AE", "sage": "#A8B5A0", "blush": "#E8CFCB",
                    "ink": "#34332F", "muted": "#77736C"}}


def probe(path, entries):
    return subprocess.run(["ffprobe", "-v", "error", *entries, "-of", "default=nw=1", str(path)],
                          capture_output=True, text=True).stdout


def fake_voice(text, voice, path):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=330:duration=0.7", "-q:a", "6", str(path)], check=True)
    return True


def test_video_pin_is_a_two_by_three_slideshow(tmp_path):
    if not vm.have_ffmpeg():
        return
    pins = []
    for i, c in enumerate(("#A8B5A0", "#E8CFCB")):
        p = tmp_path / f"p{i}.png"
        Image.new("RGB", (1000, 1500), c).save(p)
        pins.append(p)
    rep = vm.make_video_pin(pins, tmp_path / "vp.mp4", seconds_each=1.0)
    info = probe(tmp_path / "vp.mp4", ["-show_entries", "stream=width,height,codec_type", "-show_entries", "format=duration"])
    assert "width=1080" in info and "height=1620" in info and rep["aspect"] == "2:3"
    assert 1.8 < float([l for l in info.splitlines() if l.startswith("duration")][0].split("=")[1]) < 2.6


def test_script_video_has_voice_real_clip_and_correct_size(tmp_path, monkeypatch):
    if not vm.have_ffmpeg():
        return
    monkeypatch.setattr(vm, "tts_to_file", fake_voice)
    src = tmp_path / "src.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30:duration=3",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-shortest", str(src)], check=True)
    scene = lambda t, clip="": {"visual": "v", "voiceover": t, "clip": clip}
    script = {"hook": "Feel that draft?", "cta": "Full guide in the description",
              "scenes": [scene("Measure the gap first."), scene("Here is the test.", "00:00-00:02"), scene("Bad range.", "00:05-00:01")]}
    rep = vm.make_script_video(script, [], BRAND, tmp_path / "reel.mp4", voice="v", use_tts=True, accent="blush",
                               cta_label="READ THE FULL GUIDE", source_video=src)
    info = probe(tmp_path / "reel.mp4", ["-show_entries", "stream=width,height,codec_type"])
    assert "width=1080" in info and "height=1920" in info and "codec_type=audio" in info
    assert rep["real_clips"] == 1 and rep["voiceover"] is True and rep["scenes"] == 5 and rep["aspect"] == "9:16"
    assert 8 < rep["seconds"] < 14


def test_missing_ffmpeg_skips_videos_with_a_note(tmp_path, monkeypatch):
    monkeypatch.setattr(vm, "have_ffmpeg", lambda: False)
    res = vm.make_all_videos(tmp_path, [], None, BRAND, image_urls=[], cta_label="x", voice="v", use_tts=False)
    assert res["videos"] == {} and "ffmpeg was not found" in res["notes"][0]


def test_one_failing_video_does_not_stop_the_others(tmp_path, monkeypatch):
    monkeypatch.setattr(vm, "have_ffmpeg", lambda: True)
    monkeypatch.setattr(vm, "load_image_pool", lambda *a, **k: [])
    monkeypatch.setattr(vm, "make_video_pin", lambda *a, **k: {"file": "video_pin.mp4", "seconds": 16})

    def script_video(script, *a, **k):
        if k["accent"] == "blush":
            raise RuntimeError("encoder exploded")
        return {"file": "x", "seconds": 20, "voiceover": False}
    monkeypatch.setattr(vm, "make_script_video", script_video)
    res = vm.make_all_videos(tmp_path, [tmp_path / "p.png"], {"reel": {}, "short": {}}, BRAND, image_urls=[], cta_label="x", voice="v", use_tts=True)
    assert "error" in res["videos"]["instagram_reel.mp4"] and res["videos"]["youtube_short.mp4"]["seconds"] == 20
    assert res["videos"]["video_pin.mp4"]["seconds"] == 16
    assert any("instagram_reel.mp4 could not be built" in n for n in res["notes"])
    assert any("No usable images" in n for n in res["notes"]) and any("silent" in n for n in res["notes"])


def test_voice_service_missing_returns_false_not_an_error(tmp_path):
    assert vm.tts_to_file("hello", "en-US-AndrewNeural", tmp_path / "a.mp3") is False


def test_source_video_must_be_inside_the_repo(tmp_path):
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "v.mp4").write_bytes(b"x")
    assert vm.resolve_source_video("", root, tmp_path) is None
    assert vm.resolve_source_video("scripts/v.mp4", root, tmp_path) == (root / "scripts" / "v.mp4").resolve()
    for bad in ("../outside.mp4", "scripts/missing.mp4"):
        try:
            vm.resolve_source_video(bad, root, tmp_path)
            assert False, bad
        except ValueError:
            pass
