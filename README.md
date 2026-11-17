# Summer Section Content Agent

One article and/or one YouTube video in, a full set of channel content out. One run processes **one** article and **one**
video (no batches). Each can be left out:

| You provide | What happens |
|---|---|
| article + video | the most varied output: the video adds moments, demos and wording the article lacks |
| article only | article-based posts, pins and scripts |
| video only | everything is built from the video; links point to the video (or to `destination_url` if you give one) and the wording says "watch the full video" |
| neither (and `WP_SITE_URL` set) | picks the newest WordPress article with no draft yet |

## What you get
- **Pinterest**: 10 pins (1000 x 1500), each with title, description, **alt text**, keywords and a **board**. Boards come from your real board list (see below).
- **Video Pin** (`video_pin.mp4`, 2:3): slideshow of your best pins.
- **Instagram Reel** (`instagram_reel.mp4`) and **YouTube Short** (`youtube_short.mp4`), 9:16 with captions and a voiceover. Different hooks and looks. If you give the source MP4, scenes that point to a real stretch of your video use that footage with its own audio.
- **Facebook post + card** (published only after you add the `approved` label) and **Instagram post + card** (upload manually).
- **Reel and Short scripts** (text), `CAMPAIGN_SUMMARY.md`, `quality_report.json`, `boards_report.json`, and one GitHub review issue showing everything.
- **`editor.html`**: a visual editor (below).

All of it is in the artifact `summer-section-campaign` (kept 14 days). The Facebook text and both cards are also committed to `drafts/<id>/`.
Links carry UTM tags: `utm_source` = `pinterest` / `facebook` / `instagram` / `youtube`, one `utm_content` per pin.

## Inputs (Actions > Summer Section Content Agent > Run workflow)
`article_url`, `video_url`, `video_notes` (paste the script or key points), `video_notes_file` (a script file in this repo),
`destination_url` (video-only runs), `video_file` (your source MP4: repo path or https link), `make_videos`, `pins_per_article`, `use_ai_backgrounds`.

## Board matching
Put your real Pinterest boards in `brand/boards.json` (names exactly as on Pinterest, optional descriptions). The planner may only choose from
that list. A pin that fits none gets a proposed new board with an SEO description, marked **NEW: create it first** in the issue, the summary and the editor.
With an empty list you get board *suggestions* only. Close spellings match (for example "winter home tip" finds "Winter Home Tips").

## Visual editor and re-render
Open `editor.html` from the downloaded artifact in any browser. It works offline and shows every pin and both cards:
- edit text, template (3 layouts), photo background (any photo used in the campaign, or none), overlay, colours and text size, with a live preview that matches the real renderer;
- edit Pinterest title, description (with character counters), board (with an existing/new indicator) and alt text; edit the Facebook and Instagram text;
- **Download this PNG** or **Download all PNGs** for quick fixes, or **Download edits.json**.

To update the whole campaign (pins, cards, Video Pin, summary, and the Facebook draft that publishing reads), run **Actions > Re-render edited campaign**
with the original run's ID (the number in that run's URL) and the contents of `edits.json` (or a committed `edits_file`). No Groq calls are made.
Locally: `python -m agent.rerender --campaign output/<slug> --edits edits.json`.

## How the video is read
Transcript through `youtube-transcript-api` (YouTube sometimes blocks GitHub's servers) > title, description and chapters (add `YOUTUBE_API_KEY` for reliability) >
your pasted notes. Notes are always used when given: if the video came from a script you have, paste it. The issue says which source was used. Long videos are sampled in
sections and merged; invalid timestamps are dropped, never invented.

## Setup
1. Create a **private** repo and upload this project.
2. **Secrets**: `GROQ_API_KEY` (required), `FB_PAGE_ID` + `FB_PAGE_TOKEN` (Facebook publishing), `YOUTUBE_API_KEY` and `OPENAI_API_KEY` (optional).
3. **Variables** (optional): `WP_SITE_URL`, `WP_CATEGORY_ID`, `SEASON`, `DISCLOSURE` (affiliate disclosure line), `INCLUDE_VIDEO_LINK`, `TTS_VOICE` (default `en-US-AndrewNeural`; for a female voice try `en-US-AriaNeural`), `USE_TTS`, `GROQ_MODEL`.
4. Edit `brand/summer_section.json` (set `website`, `display_domain`) and `brand/boards.json`.
5. Run the workflow, review the issue, add `approved` to publish the Facebook post.

## Limits and honest notes
- Pinterest, Instagram, the Reel, the Short and the Video Pin are uploaded by you. Pinterest publishing is deliberately off (Pinterest's API only allows creating pins in production with approved access).
- Voiceover uses edge-tts, an unofficial Microsoft voice service. If it fails or is blocked, the videos are built silent with captions and the issue says so.
- Videos are made from pins, scripts, images and (optionally) your own footage: they are slideshows with captions, not newly generated AI footage. Expect a few extra minutes for the three videos.
- Use videos and images you own or have rights to.
- Check the Graph API version (`GRAPH_VERSION`, default `v23.0`) and the Groq model name against current docs.

## Local run and tests
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pytest
cp .env.example .env     # set GROQ_API_KEY and ARTICLE_URL and/or VIDEO_URL
python -m agent.main
pytest -q                # the editor test needs `pip install playwright && playwright install chromium`; it skips itself without them
```
`SOCIAL_OUTPUTS=false` runs Pinterest only. `MAKE_VIDEOS=false` skips the MP4 files.
Never commit `.env`, API keys or tokens.
