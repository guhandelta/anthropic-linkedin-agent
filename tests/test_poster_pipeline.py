import json
import re
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
    # Soft issues on every try still publish the best valid drawing rather than nothing.
    monkeypatch.setattr(agent, "design_quality_checks", lambda s: ["sparse"])
    monkeypatch.setattr(agent, "design_svg", MagicMock(side_effect=ValueError("cut off")))
    media, feedback = agent.draw_poster("post", BRIEF, "Head", "Footer", tmp_path / "p.png")
    assert media is not None


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


# --- Varied layouts and themes: the next poster never repeats the last one's layout or colours ---

def test_draw_poster_remembers_the_layout_and_the_next_poster_differs(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(agent, "layout_issues", lambda svg: [])
    monkeypatch.setattr(agent, "render_poster_files", lambda svg, p: seen.append(svg) or p)
    for _ in range(3):
        media, feedback = agent.draw_poster("post", BRIEF, "Head", "Footer", tmp_path / "p.png")
        assert media == tmp_path / "p.png" and feedback is None
    styles = [re.search(r'data-style="(\w+)"', s).group(1) for s in seen]
    themes = [re.search(r'data-theme="(\w+)"', s).group(1) for s in seen]
    assert len(set(styles)) == 3 and len(set(themes)) == 3
    saved = json.loads(agent.poster_style_path().read_text())
    assert saved == {"styles": styles, "themes": themes}


def test_style_history_keeps_the_last_four():
    for style in ["guide", "timeline", "stack", "sidebar", "incident"]:
        agent._remember_poster_style(f'<svg data-style="{style}" data-theme="ocean"/>')
    assert agent._recent_poster_styles() == {"styles": ["timeline", "stack", "sidebar", "incident"],
                                             "themes": ["ocean"] * 4}


def test_style_history_reads_the_older_single_value_file():
    path = agent.poster_style_path()
    path.parent.mkdir(parents=True)
    path.write_text('{"style": "guide", "theme": "ocean"}')
    assert agent._recent_poster_styles() == {"styles": ["guide"], "themes": ["ocean"]}
    path.write_text('{"styles": "guide", "themes": ["ocean"]}')
    assert agent._recent_poster_styles() == {"styles": [], "themes": ["ocean"]}


def test_draw_poster_runs_the_rendered_layout_check_on_the_structured_poster(monkeypatch, tmp_path):
    monkeypatch.setattr(agent, "layout_issues", lambda svg: ["'Title' overlaps icon"])
    monkeypatch.setattr(agent, "design_svg", MagicMock(side_effect=ValueError("cut off")))
    monkeypatch.setattr(agent, "render_poster_files", lambda svg, p: p)
    media, feedback = agent.draw_poster("post", BRIEF, "Head", "Footer", tmp_path / "p.png")
    assert media == tmp_path / "p.png"  # still published as the best valid drawing
    assert not agent.poster_style_path().exists()  # only a clean structured poster is remembered


@pytest.mark.parametrize("content", ["not json", "[1, 2]"])
def test_last_poster_style_ignores_a_damaged_file(content):
    path = agent.poster_style_path()
    path.parent.mkdir(parents=True)
    path.write_text(content)
    assert agent._recent_poster_styles() == {"styles": [], "themes": []}


def test_last_poster_style_is_empty_before_the_first_poster():
    assert agent._recent_poster_styles() == {"styles": [], "themes": []}


def test_remember_poster_style_skips_drawings_without_a_style():
    agent._remember_poster_style("<svg/>")
    assert not agent.poster_style_path().exists()


def test_remember_poster_style_never_raises(monkeypatch, tmp_path, capsys):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setattr(agent, "poster_style_path", lambda: blocker / "sub" / "style.json")
    agent._remember_poster_style('<svg data-style="guide" data-theme="ocean"/>')
    assert "Could not save the poster style" in capsys.readouterr().out


def test_planner_is_asked_for_a_theme(monkeypatch):
    call = MagicMock(return_value=PLAN)
    monkeypatch.setattr(agent, "call_json", call)
    agent.plan_infographic("post", "Head", "idea")
    system = call.call_args.args[0]
    assert '"theme": "ocean | forest | sunset | grape | midnight | ember"' in system
    assert "midnight for infrastructure" in system and "THEME_" not in system
    assert '"post_type": "release | bug_fix' in system and "incident for bug fixes" in system
    assert "LAYOUT_" not in system and "POST_TYPES" not in system
    assert '"cards": [{"title"' in system and "matrix for lists of 6 or 9" in system


def test_poster_style_lives_in_the_git_ignored_state_folder(monkeypatch):
    monkeypatch.undo()  # drop the conftest redirect to see the real location
    assert agent.poster_style_path() == agent.ROOT / "state" / "poster_style.json"
