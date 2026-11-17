"""Builds the Pinterest Video Pin, the Instagram Reel and the YouTube Short as MP4 files (Pillow + ffmpeg).

- Video Pin: a 2:3 slideshow of your finished pins (silent; the pin text is already on the images).
- Reel / Short: 9:16 videos made from the script. Each scene is a branded frame (image + caption) with a slow zoom,
  spoken with edge-tts when available. If you provide the source MP4 (VIDEO_FILE), scenes that point to a real
  stretch of your video (`clip`) use that footage, with its own audio, instead.
Everything degrades gracefully: no ffmpeg, no voice service, no images: the run continues and says what was skipped.
"""
from __future__ import annotations
import asyncio
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
import requests
from PIL import Image, ImageDraw, ImageFilter
from .image_designer import _clean, _download_image, _fit_cover, _fit_text, _font
from .video_reader import parse_ts

FPS = 30
VW, VH = 1080, 1920
MAX_SOURCE_BYTES = 800 * 1024 * 1024


def have_ffmpeg() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _run(cmd: list[str]) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg failed: " + (r.stderr or "").strip()[-500:])
    return r.stdout


def probe_duration(path) -> float:
    out = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)])
    return float(out.strip() or 0)


def has_audio(path) -> bool:
    out = _run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=codec_type",
                "-of", "csv=p=0", str(path)])
    return "audio" in out


def tts_to_file(text: str, voice: str, path) -> bool:
    """Speech with edge-tts. Returns False (never raises) when the service or package is unavailable."""
    try:
        import edge_tts
    except ImportError:
        print("  edge-tts is not installed; making silent captioned video.")
        return False

    async def go():
        await edge_tts.Communicate(text, voice).save(str(path))
    try:
        asyncio.run(go())
        return Path(path).is_file() and Path(path).stat().st_size > 500
    except Exception as exc:
        print(f"  Voiceover unavailable ({type(exc).__name__}); continuing with captions only.")
        return False


# ------------------------------------------------------------------ frames
def _rounded(img: Image.Image, radius: int) -> Image.Image:
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, img.width - 1, img.height - 1), radius=radius, fill=255)
    out = img.convert("RGBA")
    out.putalpha(mask)
    return out


def _caption_card(d: ImageDraw.ImageDraw, text: str, box, colors, sizes, max_lines=6):
    x0, y0, x1, y1 = box
    d.rounded_rectangle(box, radius=40, fill=colors["cream"], outline=colors["champagne"], width=4)
    font, size, lines, clipped = _fit_text(d, text, sizes, (x1 - x0) - 90, max_lines, True)
    lh = int(size * 1.28)
    y = y0 + ((y1 - y0) - len(lines) * lh) / 2
    for line in lines:
        d.text((x0 + 45, y), line, font=font, fill=colors["ink"])
        y += lh
    return clipped


def _progress(d, colors, index, total, y=1665):
    gap, left, right = 10, 70, VW - 70
    seg = (right - left - gap * (total - 1)) / total
    for i in range(total):
        x = left + i * (seg + gap)
        d.rounded_rectangle((x, y, x + seg, y + 12), radius=6,
                            fill=colors["ink"] if i <= index else colors["champagne"])


def render_script_frame(kind: str, text: str, image, brand: dict, path: Path, accent: str = "sage",
                        index: int = 0, total: int = 1, cta_label: str = "READ THE FULL GUIDE") -> dict:
    """One 1080x1920 frame. kind: 'hook' | 'scene' | 'cta'."""
    colors = brand["colors"]
    text = _clean(text)
    canvas = Image.new("RGB", (VW, VH), colors["ivory"])
    if image is not None:
        blurred = _fit_cover(image, (VW, VH)).filter(ImageFilter.GaussianBlur(26)).convert("RGBA")
        canvas = Image.alpha_composite(blurred, Image.new("RGBA", (VW, VH), (245, 239, 230, 205))).convert("RGB")
    d = ImageDraw.Draw(canvas)
    d.rectangle((0, 0, VW, 150), fill=colors[accent])
    d.text((70, 52), str(brand.get("brand", "Summer Section")).upper(), font=_font(34, True), fill=colors["ink"])
    clipped = False
    domain = str(brand.get("display_domain") or "summersection.com")

    if kind == "hook":
        clipped = _caption_card(d, text, (50, 560, VW - 50, 1300), colors, [92, 82, 72, 62, 54, 46], 7)
    elif kind == "cta":
        clipped = _caption_card(d, text, (50, 520, VW - 50, 1180), colors, [76, 66, 58, 50, 44], 6)
        d.rounded_rectangle((140, 1260, VW - 140, 1400), radius=70, fill=colors[accent])
        f = _font(40, True)
        label = cta_label
        w = d.textbbox((0, 0), label, font=f)[2]
        d.text(((VW - w) / 2, 1297), label, font=f, fill=colors["ink"])
        f2 = _font(34)
        w2 = d.textbbox((0, 0), domain, font=f2)[2]
        d.text(((VW - w2) / 2, 1440), domain, font=f2, fill=colors["muted"])
    else:
        if image is not None:
            card = _rounded(_fit_cover(image, (940, 600)), 36)
            canvas.paste(card, (70, 190), card)
            d = ImageDraw.Draw(canvas)
            box = (50, 840, VW - 50, 1580)
        else:
            box = (50, 420, VW - 50, 1400)
        sizes = [62, 56, 50, 44, 40, 36] if image is not None else [88, 78, 70, 62, 54, 48, 42, 38]
        clipped = _caption_card(d, text, box, colors, sizes, 8)

    d = ImageDraw.Draw(canvas)
    _progress(d, colors, index, total)
    d.text((70, 1730), domain, font=_font(30), fill=colors["muted"])
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path)
    return {"clipped": clipped}


def render_caption_overlay(text: str, brand: dict, path: Path, index: int, total: int) -> None:
    """Transparent 1080x1920 layer with just the caption card, laid over real footage."""
    colors = brand["colors"]
    layer = Image.new("RGBA", (VW, VH), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    _caption_card(d, _clean(text), (50, 1290, VW - 50, 1640), colors, [54, 48, 44, 40, 36], 5)
    _progress(d, colors, index, total)
    path.parent.mkdir(parents=True, exist_ok=True)
    layer.save(path)


# ------------------------------------------------------------------ ffmpeg segments
def _enc_args() -> list[str]:
    return ["-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "128k"]


def still_segment(frame_png, duration: float, out, audio=None, size=(VW, VH), zoom: float = 0.0007) -> None:
    """A still image with a slow zoom, plus voiceover (padded with silence to `duration`) or silence."""
    n = max(2, int(round(duration * FPS)))
    w, h = size
    vf = (f"scale={int(w * 1.5)}:{int(h * 1.5)},zoompan=z='min(zoom+{zoom},1.12)':x='iw/2-(iw/zoom/2)':"
          f"y='ih/2-(ih/zoom/2)':d={n}:s={w}x{h}:fps={FPS},format=yuv420p")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(frame_png)]
    cmd += ["-i", str(audio)] if audio else ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
    cmd += ["-vf", vf, "-af", "aresample=44100,apad", "-t", f"{duration:.2f}", "-map", "0:v", "-map", "1:a"]
    _run(cmd + _enc_args() + [str(out)])


def clip_segment(src, start: float, end: float, overlay_png, out, max_len: float = 20.0) -> float:
    """A real stretch of the source video on a blurred 9:16 background, caption overlay on top, original audio."""
    dur = min(end - start, max_len)
    fc = ("[0:v]split[a][b];[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=24:2[bg];"
          "[b]scale=1080:1920:force_original_aspect_ratio=decrease:force_divisible_by=2[fg];"
          "[bg][fg]overlay=(W-w)/2:(H-h)/2[base];[base][1:v]overlay=0:0,format=yuv420p[v]")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.2f}", "-t", f"{dur:.2f}", "-i", str(src),
           "-i", str(overlay_png)]
    if has_audio(src):
        amap = "0:a"
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
        amap = "2:a"
    cmd += ["-filter_complex", fc, "-map", "[v]", "-map", amap, "-af", "aresample=44100", "-t", f"{dur:.2f}"]
    _run(cmd + _enc_args() + [str(out)])
    return dur


def concat(segments: list[Path], out: Path) -> None:
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{Path(s).resolve()}'\n" for s in segments), encoding="utf-8")
    _run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
          "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
          "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out)])
    lst.unlink(missing_ok=True)


def _estimate(text: str) -> float:
    return min(9.0, max(2.5, len(text.split()) / 2.6 + 0.8))


# ------------------------------------------------------------------ the three videos
def make_video_pin(pin_files: list[Path], out: Path, seconds_each: float = 3.2, count: int = 5) -> dict:
    """2:3 slideshow of finished pins, spread across the set for variety."""
    n = len(pin_files)
    if n == 0:
        raise ValueError("no pin images to build a Video Pin from")
    idx = list(range(n)) if n <= count else sorted({round(i * (n - 1) / (count - 1)) for i in range(count)})
    with tempfile.TemporaryDirectory() as tmp:
        segs = []
        for k, i in enumerate(idx):
            seg = Path(tmp) / f"s{k}.mp4"
            still_segment(pin_files[i], seconds_each, seg, None, size=(1080, 1620), zoom=0.0005)
            segs.append(seg)
        concat(segs, out)
    return {"file": out.name, "seconds": round(seconds_each * len(idx), 1), "slides": len(idx),
            "voiceover": False, "real_clips": 0, "aspect": "2:3"}


def make_script_video(script: dict, images: list, brand: dict, out: Path, *, voice: str, use_tts: bool,
                      accent: str, cta_label: str, source_video: Path | None = None,
                      image_offset: int = 0) -> dict:
    """Hook + scenes + closing call to action, as a 9:16 video."""
    steps = [{"kind": "hook", "text": script["hook"], "clip": None}]
    for sc in script["scenes"]:
        clip = None
        m = re.fullmatch(r"\s*([\d:]+)\s*-\s*([\d:]+)\s*", str(sc.get("clip") or ""))
        if source_video and m and parse_ts(m.group(1)) is not None and parse_ts(m.group(2)) is not None:
            s, e = parse_ts(m.group(1)), parse_ts(m.group(2))
            if e > s:
                clip = (s, e)
        steps.append({"kind": "scene", "text": sc["voiceover"], "clip": clip})
    steps.append({"kind": "cta", "text": script["cta"], "clip": None})
    total, seconds, spoken, clips = len(steps), 0.0, 0, 0
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        segs = []
        for i, st in enumerate(steps):
            seg = tmp / f"seg{i}.mp4"
            if st["clip"]:
                ov = tmp / f"ov{i}.png"
                render_caption_overlay(st["text"], brand, ov, i, total)
                seconds += clip_segment(source_video, st["clip"][0], st["clip"][1], ov, seg)
                clips += 1
            else:
                img = images[(image_offset + i) % len(images)] if images else None
                frame = tmp / f"f{i}.png"
                render_script_frame(st["kind"], st["text"], img, brand, frame, accent, i, total, cta_label)
                audio, dur = None, None
                if use_tts:
                    mp3 = tmp / f"a{i}.mp3"
                    if tts_to_file(st["text"], voice, mp3):
                        audio, dur = mp3, probe_duration(mp3) + 0.45
                        spoken += 1
                dur = min(14.0, max(2.2, dur or _estimate(st["text"])))
                still_segment(frame, dur, seg, audio)
                seconds += dur
            segs.append(seg)
        concat(segs, out)
    return {"file": out.name, "seconds": round(seconds, 1), "scenes": total, "voiceover": spoken > 0,
            "real_clips": clips, "aspect": "9:16"}


def load_image_pool(urls: list[str], asset_files: list[Path], limit: int = 8) -> list:
    pool = []
    for p in asset_files:
        try:
            pool.append(Image.open(p).convert("RGB"))
        except Exception:
            pass
    for u in urls:
        if len(pool) >= limit:
            break
        im = _download_image(u, min_side=320)
        if im is not None:
            pool.append(im)
    return pool[:limit]


def resolve_source_video(setting: str, root: Path, tmp_dir: Path) -> Path | None:
    """VIDEO_FILE: a path inside the repo, or an https link to the MP4. Returns None when not usable."""
    setting = (setting or "").strip()
    if not setting:
        return None
    if setting.lower().startswith(("http://", "https://")):
        dest = tmp_dir / "source_video.mp4"
        size = 0
        with requests.get(setting, stream=True, timeout=60, headers={"User-Agent": "Mozilla/5.0"}) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    size += len(chunk)
                    if size > MAX_SOURCE_BYTES:
                        raise ValueError("source video is larger than 800 MB")
                    f.write(chunk)
        return dest
    path = (Path(root) / setting).resolve()
    if Path(root).resolve() not in path.parents or not path.is_file():
        raise ValueError(f"VIDEO_FILE must be an https link or a file inside this repository: {setting}")
    return path


def make_all_videos(out_dir: Path, pin_files: list[Path], scripts: dict | None, brand: dict, *, image_urls: list[str],
                    cta_label: str, voice: str, use_tts: bool, source_video: Path | None = None) -> dict:
    """Builds every video it can. Returns {'videos': {...}, 'notes': [...]} and never raises."""
    report, notes = {}, []
    if not have_ffmpeg():
        return {"videos": {}, "notes": ["ffmpeg was not found, so no videos were made."]}
    jobs = []
    if pin_files:
        jobs.append(("video_pin.mp4", lambda: make_video_pin(pin_files, out_dir / "video_pin.mp4")))
    if scripts:
        assets = sorted((out_dir / "assets").glob("bg_*.jpg"))
        pool = load_image_pool(image_urls, assets)
        if not pool:
            notes.append("No usable images were found for the Reel and Short, so they use text frames only.")
        for name, key, accent, offset in (("instagram_reel.mp4", "reel", "blush", 0),
                                          ("youtube_short.mp4", "short", "sage", 2)):
            jobs.append((name, lambda key=key, accent=accent, offset=offset, name=name: make_script_video(
                scripts[key], pool, brand, out_dir / name, voice=voice, use_tts=use_tts, accent=accent,
                cta_label=cta_label, source_video=source_video, image_offset=offset)))
    for name, job in jobs:
        try:
            print(f"  Building {name} ...")
            report[name] = job()
        except Exception as exc:
            report[name] = {"error": str(exc)[:300]}
            notes.append(f"{name} could not be built: {str(exc)[:200]}")
    if scripts and use_tts and not any(v.get("voiceover") for v in report.values() if isinstance(v, dict)):
        notes.append("No voiceover was added (edge-tts unavailable), so the Reel and Short are silent with captions.")
    return {"videos": report, "notes": notes}
