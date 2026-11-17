from __future__ import annotations
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from .config import ROOT, load_settings, load_brand
from .article_reader import extract_article
from .video_reader import load_video
from .groq_brain import analyze_and_plan, analyze_video, plan_posts, plan_video_scripts
from .boards import assign_boards, load_boards
from .image_designer import render_pin
from .facebook_card import render_facebook_card, render_instagram_card
from .quality_checker import check_pin, check_facebook, check_instagram, check_scripts
from .links import add_utm
from .wp_picker import pick_unused_article
from .video_maker import make_all_videos, resolve_source_video
from .editor_builder import build_editor
from .report import write_summary
from . import drafts as dr


def slugify(value: str) -> str:
    value = re.sub(r"[^\w\s-]", "", value.lower())
    return re.sub(r"[-\s]+", "-", value).strip("-")[:70] or "article-campaign"


def write_json(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def with_video_thumbnails(article_images: list[str], thumbs: list[str]) -> list[str]:
    """Every third pin gets a frame-style background from the video, for visual variety."""
    images = list(article_images)
    for pos, thumb in zip((0, 3, 6, 9), (thumbs or []) * 4):
        images.insert(min(pos, len(images)), thumb)
    return images


def article_from_video(video: dict, analysis: dict, destination: str = "") -> dict:
    """Video-only mode: the planner expects an 'article', so build one from the video analysis."""
    dest = (destination or "").strip() or video.get("url", "")
    if not dest:
        raise ValueError("Video-only mode needs a video URL, or a destination URL for the links.")
    parts = [analysis.get("video_summary", "")]
    for label, key in (("Key points", "key_points"), ("Statements made in the video", "statements_in_video"),
                       ("Products shown", "products_shown")):
        if analysis.get(key):
            parts.append(f"{label}: " + "; ".join(analysis[key]))
    if analysis.get("moments"):
        parts.append("Moments: " + "; ".join(m["point"] for m in analysis["moments"]))
    return {"url": dest, "submitted_url": dest,
            "title": video.get("title") or analysis.get("video_summary", "Product video")[:80],
            "headings": [c["title"] for c in video.get("chapters", [])],
            "text": "\n".join(p for p in parts if p),
            "image_urls": list(video.get("thumbnail_urls", [])),
            "description": (video.get("description") or "")[:300], "source_kind": "video",
            # links go to the video itself unless the owner gave a page of their own to send people to
            "link_target": "guide" if (destination or "").strip() else "video"}


def video_notes(video, analysis) -> list[str]:
    if not video:
        return ["No video was provided, so the copy is based on the article only and may be more repetitive. "
                "Add a video URL for more variety."]
    notes = []
    src = video.get("source")
    if src == "none":
        notes.append("The video could not be read at all, so the copy is based on the article only.")
    elif src == "metadata":
        notes.append("No transcript was available (YouTube may block GitHub's servers). Only the title, description "
                     "and chapters were used. Paste the video script into video_notes for richer copy.")
    elif src == "notes":
        notes.append("No transcript was available; the pasted notes were used. Clip timestamps are not available.")
    cov = (analysis or {}).get("coverage", "")
    if cov.startswith("sampled"):
        notes.append(f"Long video: {cov}. Raise VIDEO_MAX_CHUNKS to read more of it.")
    return notes


def run():
    settings = load_settings()
    brand = load_brand(settings.brand_path)
    if not settings.groq_api_key:
        raise ValueError("GROQ_API_KEY is missing. Add it as a GitHub Actions secret named GROQ_API_KEY.")

    # ---- sources: article only, video only, or both ----
    has_video_input = bool(settings.video_url or settings.video_notes)
    url = settings.article_url
    if not url and not has_video_input:
        url = pick_unused_article(settings.wp_site_url, settings.wp_category_id,
                                  dr.used_urls(settings.drafts_dir))
        if not url:
            print("No unused articles found. Publish a new article or pass an article or video URL.")
            return 0
        print(f"Auto-picked the next unused article: {url}")
    article = None
    if url:
        print(f"Extracting article: {url}")
        article = extract_article(url)

    video, video_analysis = None, None
    if has_video_input:
        print("Reading the video ...")
        video = load_video(settings.video_url, settings.youtube_api_key, settings.video_notes)
        print(f"  Video source: {video['source']}")
        video_analysis = analyze_video(settings.groq_api_key, settings.model, video, brand,
                                       settings.video_char_limit, settings.video_max_chunks)
    if article is None:
        if video["source"] == "none":
            raise ValueError("The video could not be read (no transcript, description or notes) and no article "
                             "was given, so there is nothing to build from. Paste notes, or add an article URL.")
        article = article_from_video(video, video_analysis, settings.destination_url)
    kind = "video" if article.get("source_kind") == "video" else ("both" if video else "article")
    notes = video_notes(video, video_analysis)
    if kind == "video":
        notes.append(f"Video-only run: pins and posts link to {article['url']}.")
    to_video = article.get("link_target") == "video"
    cta_label = "WATCH THE FULL VIDEO" if to_video else "READ THE FULL GUIDE"
    footers = {"fb": cta_label, "ig": "FULL VIDEO: LINK IN BIO" if to_video else "FULL GUIDE: LINK IN BIO"}
    label = "Watch the full video" if to_video else "Read the full guide"

    # ---- plan the pins (with the user's real boards) ----
    boards = load_boards(settings.boards_path)
    print(f"Analyzing the content and planning {settings.pin_count} Pinterest pins with Groq ({settings.model})...")
    plan = analyze_and_plan(settings.groq_api_key, settings.model, article, brand, settings.pin_count,
                            settings.article_char_limit, video_analysis=video_analysis, boards=boards)
    board_report = assign_boards(plan["pins"], boards)

    campaign_slug = slugify(article.get("title") or plan["article_analysis"].get("topic", "article"))
    out = settings.output_dir / campaign_slug
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "article_analysis.json", plan["article_analysis"])
    if video_analysis:
        write_json(out / "video_analysis.json", video_analysis)
    write_json(out / "pinterest_keyword_suggestions.json", plan["keyword_suggestions"])
    write_json(out / "pin_strategy.json", {"pins": plan["pins"], "boards": plan.get("board_suggestions", [])})
    write_json(out / "boards_report.json", board_report)

    # ---- Pinterest pins (article images plus video frames) ----
    images = with_video_thumbnails(article.get("image_urls", []), video["thumbnail_urls"] if video and kind != "video" else [])
    quality, campaign_pins = [], []
    seen_hashes: dict[str, int] = {}
    for pin in plan["pins"]:
        number = int(pin["number"])
        image_path = out / f"pin_{number:02d}.png"
        image_meta = render_pin(pin, brand, image_path, images, settings.openai_api_key, settings.image_model,
                                settings.use_ai_backgrounds, cta_label=cta_label, assets_dir=out / "assets")
        result = check_pin(image_path, pin, article["url"], image_meta)
        digest = hashlib.sha1(image_path.read_bytes()).hexdigest()
        if digest in seen_hashes:
            result["issues"].append(f"Image is identical to pin {seen_hashes[digest]}.")
            result["passed"] = False
        seen_hashes.setdefault(digest, number)
        result["pin_number"] = number
        quality.append(result)
        campaign_pins.append({
            **pin,
            "canonical_url": article["url"],
            "destination_url": add_utm(article["url"], "pinterest", campaign_slug, f"pin_{number:02d}"),
            "image_file": image_path.name,
            "image": image_meta,
            "style": image_meta["style"],
            "approval_status": "pending"
        })

    # ---- Facebook + Instagram posts, Reel + Short scripts ----
    fb_check = ig_check = script_check = None
    draft_id = fb_message = ig_caption = reel_md = short_md = ""
    posts = scripts = None
    video_url = video["url"] if (video and video.get("url")) else ""
    if settings.social_outputs:
        print("Planning the Facebook and Instagram posts ...")
        posts = plan_posts(settings.groq_api_key, settings.model, article, plan, video_analysis, brand,
                           settings.season, [p["headline"] for p in plan["pins"]])
        posts["facebook"]["band"], posts["instagram"]["band"] = "sage", "blush"
        print("Writing the Reel and YouTube Short scripts ...")
        scripts = plan_video_scripts(settings.groq_api_key, settings.model, article, plan, video_analysis,
                                     brand, posts)
        title = article.get("title", "Article")
        fb_link = add_utm(article["url"], "facebook", campaign_slug)
        ig_link = add_utm(article["url"], "instagram", campaign_slug)
        yt_link = add_utm(article["url"], "youtube", campaign_slug)
        video_line = video_url if (settings.include_video_link and kind == "both") else ""

        fb_card, ig_card = out / "facebook_card.png", out / "instagram_card.png"
        fb_meta = render_facebook_card(posts["facebook"], brand, fb_card, footers["fb"])
        ig_meta = render_instagram_card(posts["instagram"], brand, ig_card, footers["ig"])
        fb_message = dr.build_facebook_message(posts["facebook"], settings.disclosure, fb_link, video_line, label)
        ig_caption = dr.build_instagram_caption(posts["instagram"], settings.disclosure)
        reel_md = dr.build_reel_md(title, scripts["reel"], ig_link)
        short_md = dr.build_short_md(title, scripts["short"], yt_link, video_url)
        fb_check = check_facebook(fb_card, posts["facebook"], fb_message, fb_link, fb_meta)
        ig_check = check_instagram(ig_card, posts["instagram"], ig_caption, ig_meta)
        script_check = check_scripts(scripts)

        write_json(out / "facebook_post.json", {"message": fb_message, "image_file": fb_card.name, "link": fb_link,
                                                "content": posts["facebook"], "disclosure": settings.disclosure,
                                                "video_url": video_line, "label": label, "approval_status": "pending"})
        write_json(out / "instagram_post.json", {"caption": ig_caption, "image_file": ig_card.name,
                                                 "alt_text": posts["instagram"]["alt_text"], "link_for_bio": ig_link,
                                                 "content": posts["instagram"], "disclosure": settings.disclosure,
                                                 "approval_status": "manual_upload"})
        write_json(out / "video_scripts.json", scripts)
        (out / "instagram_reel_script.md").write_text(reel_md, encoding="utf-8")
        (out / "youtube_short_script.md").write_text(short_md, encoding="utf-8")

    # ---- videos: Video Pin, Reel, Short (MP4) ----
    video_report = {}
    if settings.make_videos:
        print("Building the Video Pin, Reel and Short ...")
        frame_urls = (video.get("frame_urls", []) if video else []) + article.get("image_urls", [])
        with tempfile.TemporaryDirectory() as tmp:
            source_video = None
            if settings.video_file:
                try:
                    source_video = resolve_source_video(settings.video_file, ROOT, Path(tmp))
                except Exception as exc:
                    notes.append(f"VIDEO_FILE could not be used ({str(exc)[:160]}); built the videos without real footage.")
            res = make_all_videos(out, [out / p["image_file"] for p in campaign_pins], scripts, brand,
                                  image_urls=frame_urls, cta_label=cta_label, voice=settings.tts_voice,
                                  use_tts=settings.use_tts, source_video=source_video)
        video_report = res["videos"]
        notes += res["notes"]
        write_json(out / "video_report.json", video_report)

    extra = [c for c in (fb_check, ig_check, script_check) if c]
    all_checks = quality + extra
    passed_count = sum(x["passed"] for x in all_checks)
    all_issues = [f"Pin {x['pin_number']}: {i}" for x in quality for i in x["issues"]]
    for lbl, c in (("Facebook", fb_check), ("Instagram", ig_check), ("Scripts", script_check)):
        if c:
            all_issues += [f"{lbl}: {i}" for i in c["issues"]]
    all_passed = all(x["passed"] for x in all_checks)

    # ---- review draft (committed by the workflow; the Facebook post waits for the `approved` label) ----
    if settings.social_outputs:
        draft_id = dr.new_draft_id(article["url"])
        video_files = [n for n, v in video_report.items() if "error" not in v]
        issue_md = dr.build_issue_md(
            draft_id, article, fb_message, ig_caption, posts["instagram"]["alt_text"], reel_md, short_md,
            campaign_pins,
            {"passed_count": passed_count, "total": len(all_checks), "issues": all_issues, "notes": notes},
            settings.run_url, os.environ.get("GITHUB_REPOSITORY", "owner/repo"),
            os.environ.get("GITHUB_REF_NAME", "main"), board_report, video_files, kind)
        dr.write_draft(settings.drafts_dir, draft_id, {
            "status": "pending",
            "created": datetime.now(timezone.utc).isoformat(),
            "article_url": article["url"],
            "submitted_url": article.get("submitted_url", article["url"]),
            "article_title": article.get("title", ""),
            "video_url": video_url,
            "facebook_message": fb_message,
            "campaign_folder": campaign_slug,
        }, {"facebook_card.png": out / "facebook_card.png", "instagram_card.png": out / "instagram_card.png"},
            issue_md)

    campaign = {
        "brand": brand["brand"],
        "article_url": article["url"],
        "article_title": article["title"],
        "source_kind": kind,
        "video_url": video_url,
        "video_source": video["source"] if video else "",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "publishing_mode": "manual_review_only",
        "cta_label": cta_label,
        "footers": footers,
        "draft_id": draft_id,
        "notes": notes,
        "quality": {"passed": all_passed, "passed_count": passed_count, "total": len(all_checks)},
        "pins": campaign_pins
    }
    write_json(out / "pinterest_campaign.json", campaign)
    write_json(out / "publishing_queue.json", {
        "note": "No Pins have been published. Review and approve each item manually. "
                "The Facebook post publishes only after the review issue gets the `approved` label. "
                "Instagram, the Reel, the YouTube Short and the Video Pin are uploaded manually.",
        "publishing_enabled": False,
        "items": [{"pin_number": p["number"], "status": "pending_review", "board": p["board"],
                   "board_status": p.get("board_status", ""), "image_file": p["image_file"],
                   "destination_url": p["destination_url"]} for p in campaign_pins],
        "facebook": ({"status": "pending_review", "image_file": "facebook_card.png",
                      "draft_id": draft_id, "publishes_when": "review issue labelled approved"}
                     if settings.social_outputs else None),
        "instagram_post": {"status": "manual_upload"} if settings.social_outputs else None,
        "videos": {n: {"status": "manual_upload"} for n, v in video_report.items() if "error" not in v},
    })
    write_json(out / "quality_report.json", {
        "passed": all_passed,
        "checks": quality,
        "facebook_check": fb_check,
        "instagram_check": ig_check,
        "script_check": script_check,
        "notes": notes
    })
    write_summary(out)
    build_editor(out, brand, campaign, boards, facebook=posts["facebook"] if posts else None,
                 instagram=posts["instagram"] if posts else None, cta_label=cta_label,
                 fb_footer=footers["fb"], ig_footer=footers["ig"])
    print(f"Campaign saved to: {out}")

    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out and draft_id:
        title = re.sub(r"\s+", " ", article.get("title", "Article"))[:70]
        with open(gh_out, "a", encoding="utf-8") as f:
            f.write(f"draft_id={draft_id}\ntitle={title}\n")

    if not all_passed:
        print("WARNING: Some quality checks failed. Review quality_report.json.")
        return 2
    return 0


def main():
    try:
        code = run()
    except Exception as exc:  # report a clear error instead of a long traceback
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
    sys.exit(code)


if __name__ == "__main__":
    main()
