"""Board matching: use the user's REAL Pinterest boards, and flag anything that would need a new board."""
from __future__ import annotations
import json
import re
from difflib import SequenceMatcher
from pathlib import Path


def _norm(s) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", str(s or "").lower()).split())


def load_boards(path) -> list[dict]:
    """brand/boards.json: {"boards": [{"name": "...", "description": "...", "keywords": []}]}. Missing file = no boards."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    out = []
    for b in data.get("boards", []):
        if isinstance(b, str):
            b = {"name": b}
        if isinstance(b, dict) and str(b.get("name", "")).strip():
            out.append({"name": b["name"].strip(), "description": str(b.get("description", "")).strip(),
                        "keywords": list(b.get("keywords", []))})
    return out


def match_board(name: str, boards: list[dict], threshold: float = 0.86):
    """The user's board that `name` refers to (exact, case/punctuation-insensitive, or a close spelling), else None."""
    n = _norm(name)
    if not n:
        return None
    best, best_score = None, 0.0
    for b in boards:
        bn = _norm(b["name"])
        score = 1.0 if bn == n else SequenceMatcher(None, n, bn).ratio()
        if score > best_score:
            best, best_score = b["name"], score
    return best if best_score >= threshold else None


def assign_boards(pins: list[dict], boards: list[dict]) -> dict:
    """Sets pin['board'] to the exact name of an existing board and pin['board_status'] to
    'existing' | 'new' (configured boards, none fits) | 'suggested' (no boards configured)."""
    existing: dict[str, list[int]] = {}
    new: dict[str, dict] = {}
    for pin in pins:
        raw = str(pin.get("board", "")).strip()
        matched = match_board(raw, boards) if boards else None
        number = pin.get("number")
        if matched:
            pin["board"], pin["board_status"] = matched, "existing"
            existing.setdefault(matched, []).append(number)
            continue
        pin["board"] = raw or "General"
        pin["board_status"] = "new" if boards else "suggested"
        entry = new.setdefault(_norm(pin["board"]), {"name": pin["board"], "description": "", "pins": []})
        entry["pins"].append(number)
        if not entry["description"]:
            entry["description"] = str(pin.get("new_board_description", "")).strip()
    return {"mode": "matched" if boards else "suggestions_only", "configured_boards": len(boards),
            "existing": [{"board": b, "pins": v} for b, v in existing.items()],
            "new": list(new.values())}
