"""Publishes ONE approved draft to the Facebook Page. Run by the 'Publish approved draft' workflow
after a human adds the `approved` label to the review issue. Pinterest is never published here."""
from __future__ import annotations
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
import requests
from .drafts import DRAFT_ID_RE


def main() -> int:
    draft_id = os.environ["DRAFT_ID"]
    if not DRAFT_ID_RE.fullmatch(draft_id):
        sys.exit("Invalid draft id")
    page_id, token = os.environ["FB_PAGE_ID"], os.environ["FB_PAGE_TOKEN"]
    version = os.environ.get("GRAPH_VERSION") or "v23.0"   # check Meta's current Graph API version
    folder = Path(os.environ.get("DRAFTS_DIR") or "drafts") / draft_id
    path = folder / "draft.json"
    draft = json.loads(path.read_text(encoding="utf-8"))
    if draft.get("status") == "published":
        print("Already published, skipping.")
        return 0
    with open(folder / "facebook_card.png", "rb") as img:
        r = requests.post(f"https://graph.facebook.com/{version}/{page_id}/photos",
                          data={"message": draft["facebook_message"], "access_token": token},
                          files={"source": img}, timeout=120)
    if not r.ok:
        sys.exit(f"Facebook error {r.status_code}: {r.text}")
    res = r.json()
    post_id = res.get("post_id") or res.get("id")
    draft.update({"status": "published", "fb_post_id": post_id,
                  "published_at": datetime.now(timezone.utc).isoformat()})
    path.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"post_id={post_id}\n")
    print("Published:", post_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
