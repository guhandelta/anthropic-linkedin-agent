import json
from unittest.mock import MagicMock

import pytest

import agent
from poster_layout import MARKER

PLAN = {
    "title": "Native APIs for leaner apps", "subtitle": "A practical path", "tagline": "Less code",
    "hero": {"caption": "Replace one library", "nodes": [
        {"label": "Find usage", "detail": "Inspect calls", "icon": "search"},
        {"label": "Pick API", "detail": "Check support", "icon": "code"},
        {"label": "Measure", "detail": "Compare size", "icon": "check"}]},
    "modules": [
        {"kind": "code", "heading": "Clipboard", "icon": "code", "lines": ["await navigator.clipboard.writeText(t)"]},
        {"kind": "checklist", "heading": "Compat", "icon": "check", "lines": ["Check support", "Keep fallback"]},
        {"kind": "stats", "heading": "Numbers", "icon": "chart", "lines": ["50% | Less JS", "2x | Faster"]}],
    "gotcha": {"heading": "Watch out", "text": "Support varies."},
    "takeaway": "Try one native API.",
}
BRIEF = "idea\n\n" + MARKER + "\n" + json.dumps(PLAN)


def test_plan_infographic_appends_blueprint(monkeypatch):
    monkeypatch.setattr(agent, "call_json", MagicMock(return_value=PLAN))
    out = agent.plan_infographic("post", "Head", "idea")
    assert out.startswith("idea") and "CONTENT BLUEPRINT" in out and "Native APIs" in out


@pytest.mark.parametrize("result", [{}, {"modules": []}, ["not", "a", "dict"]])
def test_plan_infographic_falls_back_on_unusable_plan(monkeypatch, result):
    monkeypatch.setattr(agent, "call_json", MagicMock(return_value=result))
    assert agent.plan_infographic("post", "Head", "idea") == "idea"


def test_plan_infographic_falls_back_on_error(monkeypatch):
    monkeypatch.setattr(agent, "call_json", MagicMock(side_effect=RuntimeError("down")))
    assert agent.plan_infographic("post", "Head", "idea") == "idea"


def test_designer_prompt_is_complete_and_stable():
    first = agent._designer_prompt("Same headline", "My footer")
    assert first == agent._designer_prompt("Same headline", "My footer")
    assert "My footer" in first and "THEME_BLOCK" not in first and "ICON_LIST" not in first


def test_render_poster_files_prefers_gif(monkeypatch, tmp_path):
    monkeypatch.setattr(agent, "render_svg", lambda svg, p: p.write_bytes(b"png"))
    monkeypatch.setattr(agent, "render_svg_to_gif", lambda svg, p: p.write_bytes(b"gif"))
    out = agent.render_poster_files("<svg/>", tmp_path / "a.png")
    assert out == tmp_path / "a.gif" and (tmp_path / "a.svg").exists()


def test_render_poster_files_falls_back_to_png(monkeypatch, tmp_path):
    monkeypatch.setattr(agent, "render_svg", lambda svg, p: p.write_bytes(b"png"))
    monkeypatch.setattr(agent, "render_svg_to_gif", MagicMock(side_effect=RuntimeError("no gif")))
    assert agent.render_poster_files("<svg/>", tmp_path / "a.png") == tmp_path / "a.png"


def test_draw_poster_uses_structured_layout_and_returns_gif(tmp_path):
    media, feedback = agent.draw_poster("post", BRIEF, "Head", "Footer", tmp_path / "p.png")
    assert media == tmp_path / "p.gif" and media.exists() and feedback is None
    assert (tmp_path / "p.png").exists()


def test_draw_poster_structured_render_error_goes_to_designer(monkeypatch, tmp_path):
    calls = []

    def render(svg, path):
        calls.append(path)
        if len(calls) == 1:
            raise ValueError("bad svg")
        return path

    monkeypatch.setattr(agent, "render_poster_files", render)
    monkeypatch.setattr(agent, "design_svg", MagicMock(return_value="<svg/>"))
    monkeypatch.setattr(agent, "svg_checks", lambda s: [])
    monkeypatch.setattr(agent, "design_quality_checks", lambda s: [])
    media, _ = agent.draw_poster("post", BRIEF, "Head", "Footer", tmp_path / "p.png")
    assert media == tmp_path / "p.png"


def test_draw_poster_structured_failing_checks_fall_to_designer(monkeypatch, tmp_path):
    monkeypatch.setattr(agent, "design_quality_checks", lambda s: ["sparse"])
    monkeypatch.setattr(agent, "design_svg", MagicMock(side_effect=ValueError("cut off")))
    media, feedback = agent.draw_poster("post", BRIEF, "Head", "Footer", tmp_path / "p.png")
    assert media is None and "cut off" in feedback


def test_draw_poster_designer_retries_then_succeeds(monkeypatch, tmp_path):
    svgs = iter(["<svg>hard</svg>", "<svg>soft</svg>", "<svg>good</svg>"])
    monkeypatch.setattr(agent, "design_svg", lambda *a, **k: next(svgs))
    monkeypatch.setattr(agent, "svg_checks", lambda s: ["too big"] if "hard" in s else [])
    monkeypatch.setattr(agent, "design_quality_checks", lambda s: ["sparse"] if "soft" in s else [])
    monkeypatch.setattr(agent, "render_poster_files", lambda svg, p: p)
    media, _ = agent.draw_poster("post", "plain idea", "Head", "Footer", tmp_path / "p.png")
    assert media == tmp_path / "p.png"


def test_draw_poster_designer_render_error_then_gives_up(monkeypatch, tmp_path):
    monkeypatch.setattr(agent, "design_svg", lambda *a, **k: "<svg/>")
    monkeypatch.setattr(agent, "svg_checks", lambda s: [])
    monkeypatch.setattr(agent, "design_quality_checks", lambda s: [])
    monkeypatch.setattr(agent, "render_poster_files", MagicMock(side_effect=ValueError("render boom")))
    media, feedback = agent.draw_poster("post", "plain idea", "Head", "Footer", tmp_path / "p.png")
    assert media is None and feedback == "render boom"
