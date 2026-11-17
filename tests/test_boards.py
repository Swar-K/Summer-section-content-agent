import copy
import json
from agent import boards as bd
from agent import groq_brain as gb

BOARDS = [{"name": "Home Cooling & Fans", "description": "fans", "keywords": []}, {"name": "Winter Home Tips", "description": "", "keywords": []}]


def test_load_boards_tolerates_missing_file_and_plain_names(tmp_path):
    assert bd.load_boards(tmp_path / "nope.json") == []
    (tmp_path / "b.json").write_text(json.dumps({"boards": ["Fans", {"name": " Kitchen "}, {"name": ""}, 5]}))
    assert [b["name"] for b in bd.load_boards(tmp_path / "b.json")] == ["Fans", "Kitchen"]
    (tmp_path / "bad.json").write_text("{not json")
    assert bd.load_boards(tmp_path / "bad.json") == []


def test_match_board_exact_loose_and_close_spellings():
    assert bd.match_board("home cooling and fans", BOARDS) == "Home Cooling & Fans"
    assert bd.match_board("Home Cooling & Fans", BOARDS) == "Home Cooling & Fans"
    assert bd.match_board("home cooling fans", BOARDS) == "Home Cooling & Fans"
    assert bd.match_board("Winter Home Tip", BOARDS) == "Winter Home Tips"
    assert bd.match_board("Gardening", BOARDS) is None and bd.match_board("", BOARDS) is None


def test_assign_boards_marks_existing_and_new():
    pins = [{"number": 1, "board": "winter home tips"}, {"number": 2, "board": "Pet Care", "new_board_description": "Pets"},
            {"number": 3, "board": "Pet Care"}]
    rep = bd.assign_boards(pins, BOARDS)
    assert pins[0]["board"] == "Winter Home Tips" and pins[0]["board_status"] == "existing"
    assert pins[1]["board_status"] == pins[2]["board_status"] == "new"
    assert rep["mode"] == "matched" and rep["new"] == [{"name": "Pet Care", "description": "Pets", "pins": [2, 3]}]
    assert rep["existing"] == [{"board": "Winter Home Tips", "pins": [1]}]


def test_without_configured_boards_everything_is_a_suggestion():
    pins = [{"number": 1, "board": "Home Tips"}]
    rep = bd.assign_boards(pins, [])
    assert pins[0]["board_status"] == "suggested" and rep["mode"] == "suggestions_only"


# ---- the planner is told about the real boards ----
class Resp:
    def __init__(self, content):
        self.status_code, self.headers, self.text, self._c = 200, {}, content, content

    def json(self):
        return {"choices": [{"message": {"content": self._c}}]}


ANALYSIS = json.dumps({"article_analysis": {"topic": "t"}, "keyword_suggestions": {"phrases": []}, "board_suggestions": ["Idea"]})


def pins_json(k):
    return json.dumps({"pins": [{"number": i + 1, "angle": "a", "headline": f"H{i}", "subheadline": "", "title": "T",
                                 "description": "D", "keywords": [], "hashtags": [], "board": "Winter Home Tips",
                                 "visual_direction": "v", "image_prompt": "p", "claims_used": []} for i in range(k)]})


def run_plan(monkeypatch, **extra):
    sent = []
    replies = [Resp(ANALYSIS), Resp(pins_json(3))]
    monkeypatch.setattr(gb.requests, "post", lambda url, headers=None, json=None, timeout=0: (sent.append(copy.deepcopy(json)), replies.pop(0))[1])
    monkeypatch.setattr(gb.time, "sleep", lambda s: None)
    return sent, {"title": "T", "url": "u", "description": "d", "headings": [], "text": "word " * 100, **extra}


def test_planner_prompt_lists_existing_boards_only_when_configured(monkeypatch):
    sent, article = run_plan(monkeypatch)
    plan = gb.analyze_and_plan("k", "m", article, {"tone": []}, 3, boards=BOARDS)
    prompt = sent[1]["messages"][1]["content"]
    assert "EXISTING BOARDS" in prompt and "Home Cooling & Fans" in prompt and "BOARD IDEAS" not in prompt
    assert "alt_text" in prompt and plan["pins"][0]["alt_text"] == ""            # defaulted when the model omits it
    sent, article = run_plan(monkeypatch)
    gb.analyze_and_plan("k", "m", article, {"tone": []}, 3)
    assert "BOARD IDEAS" in sent[1]["messages"][1]["content"] and "EXISTING BOARDS" not in sent[1]["messages"][1]["content"]


def test_video_only_source_is_explained_to_the_planner(monkeypatch):
    sent, article = run_plan(monkeypatch, source_kind="video")
    gb.analyze_and_plan("k", "m", article, {"tone": []}, 3)
    assert "comes from a product VIDEO" in sent[0]["messages"][1]["content"]
