"""Content-driven hero layouts: the planner's hero.form picks the drawing, and every form stays clean."""
import json

import pytest

from infographic import design_quality_checks, finalize_svg, svg_checks
from layout_check import layout_issues
from poster_layout import MARKER, _hero_before_after, _hero_flow, _hero_layers, poster_from_brief

NODES = [
    {"label": "Find usage", "detail": "Inspect one library's calls", "icon": "search"},
    {"label": "Select API", "detail": "Check support and permissions", "icon": "code"},
    {"label": "Measure", "detail": "Compare bundle size", "icon": "check"},
    {"label": "Ship safely", "detail": "Keep a fallback in place", "icon": "layers"},
]
MODULES = [
    {"kind": "code", "heading": "Clipboard API", "icon": "code",
     "lines": ["await navigator.clipboard.writeText(text)"]},
    {"kind": "checklist", "heading": "Compatibility", "icon": "check",
     "lines": ["Check browser support", "Check secure context", "Keep a fallback"]},
    {"kind": "steps", "heading": "Rollout", "icon": "layers",
     "lines": ["Replace one call", "Test in browsers", "Measure bundle size"]},
]


def _plan(form=None, nodes=None, **hero_extra):
    hero = {"caption": "Replace one library with a native capability", "nodes": nodes or NODES[:3],
            "left_label": "Old way", "right_label": "New way", **hero_extra}
    if form is not None:
        hero["form"] = form
    return {"title": "Built-in Web APIs for leaner apps",
            "subtitle": "A practical path through browser capabilities",
            "tagline": "Less dependency code, with a compatibility check",
            "hero": hero, "modules": MODULES,
            "gotcha": {"heading": "Watch out", "text": "Browser support and permissions vary."},
            "takeaway": "Try one native API and measure its impact."}


def _render(plan):
    return finalize_svg(poster_from_brief(MARKER + "\n" + json.dumps(plan), "Heading", "Author",
                                          style="guide", theme="ocean"))


@pytest.mark.parametrize("form, count", [("flow", 3), (None, 3), ("cycle", 3), ("flow", 4),
                                         ("layers", 3), ("layers", 4), ("before_after", 4)])
def test_every_hero_form_renders_clean(form, count):
    nodes = NODES[:count]
    svg = _render(_plan(form=form, nodes=nodes))
    assert svg is not None
    assert svg_checks(svg) == []
    assert design_quality_checks(svg) == []
    assert layout_issues(svg) == []
    assert svg.count("data-motion-step=") == count


def test_before_after_uses_the_two_labels_and_arrow():
    svg = _render(_plan(form="before_after", nodes=NODES, left_label="Old way", right_label="New way"))
    assert "Old way" in svg and "New way" in svg
    assert 'x1="505"' in svg  # the arrow between the two columns


def test_layers_stacks_one_band_per_step_top_to_bottom():
    svg = _render(_plan(form="layers", nodes=NODES))
    ys = [int(part.split('y="')[1].split('"')[0]) for part in svg.split("<rect ")
          if "data-motion-step" in part]
    assert ys == sorted(ys) and len(ys) == 4


def test_before_after_with_three_steps_falls_back_to_flow():
    flow = _render(_plan(form="flow", nodes=NODES[:3]))
    assert _render(_plan(form="before_after", nodes=NODES[:3])) == flow


def test_layers_with_three_steps_is_a_different_drawing_from_flow():
    assert _render(_plan(form="layers", nodes=NODES[:3])) != _render(_plan(form="flow", nodes=NODES[:3]))


def test_fewer_than_three_steps_is_rejected_by_the_builder():
    assert poster_from_brief(MARKER + "\n" + json.dumps(_plan(form="layers", nodes=NODES[:2])),
                             "Heading", "Author") is None


def test_unknown_form_falls_back_to_flow():
    flow = _render(_plan(form="flow", nodes=NODES[:3]))
    assert _render(_plan(form="hologram", nodes=NODES[:3])) == flow


def test_form_is_case_and_space_insensitive():
    a = _render(_plan(form="  Layers ", nodes=NODES))
    b = _render(_plan(form="layers", nodes=NODES))
    assert a == b


def test_long_labels_are_fitted_inside_their_band_and_column():
    long_nodes = [{"label": "An extremely long step label that cannot fit the band at all",
                   "detail": "An equally long supporting detail sentence about the step here",
                   "icon": "search"} for _ in range(4)]
    for form in ("layers", "before_after"):
        svg = _render(_plan(form=form, nodes=long_nodes))
        assert svg is not None
        assert layout_issues(svg) == []


def test_helpers_draw_directly_into_parts():
    parts = []
    _hero_layers(parts, NODES, ["#000000"] * 5)
    _hero_before_after(parts, {"left_label": "", "right_label": ""}, NODES, ["#000000"] * 5)
    _hero_flow(parts, {"tagline": "hook"}, NODES[:3], ["#000000"] * 5)
    assert any("data-motion-step" in part for part in parts)


# --- Edge cases that keep the builder safe on any planner output (coverage for poster_layout) ---

from poster_layout import _icon, _module, _wrap, _wrap_code  # noqa: E402


def test_wrap_truncates_a_single_long_word_with_an_ellipsis():
    assert _wrap("supercalifragilisticexpialidocious", 80, 26, 2)[0].endswith("…")


def test_five_step_flow_draws_the_long_return_arrow():
    five = NODES + [{"label": "Monitor", "detail": "Watch the metrics", "icon": "chart"}]
    svg = _render(_plan(form="flow", nodes=five))
    assert svg is not None and svg.count("data-motion-step=") == 5
    assert layout_issues(svg) == []


def test_wrap_of_nothing_returns_no_lines():
    assert _wrap(None, 200, 22, 2) == []


def test_wrap_code_marks_a_code_line_that_ends_in_an_ellipsis():
    lines = _wrap_code("const value = computeSomething(argumentOne, argumentTwo...", 300, 22, 3)
    assert lines and "..." not in "".join(lines)  # the trailing dots are replaced by a marker


def test_icon_falls_back_to_sparkle_for_unknown_names():
    assert "icon-sparkle" in _icon("not-a-real-icon", 0, 0, "#000000")


def test_module_with_non_list_lines_renders_only_the_heading():
    parts = []
    _module(parts, {"kind": "checklist", "heading": "Notes", "icon": "check", "lines": "not a list"},
            40, 698, 490, 187, 1, "#3768B7")
    assert any("1. Notes" in part for part in parts)


def test_stats_module_renders_value_and_caption_pairs():
    parts = []
    _module(parts, {"kind": "stats", "heading": "Numbers", "icon": "chart",
                    "lines": ["40% | smaller bundle", "2x | faster paint"]},
            40, 698, 490, 187, 1, "#3768B7")
    joined = "".join(parts)
    assert "40%" in joined and "smaller bundle" in joined


def test_module_drops_items_that_are_too_long_and_stops_at_the_line_budget():
    long_item = "word " * 60
    parts = []
    _module(parts, {"kind": "checklist", "heading": "Limits", "icon": "warning",
                    "lines": [long_item, "Short item one", "Short item two", "Short item three",
                              "Short item four", "Short item five"]},
            40, 698, 490, 187, 1, "#3768B7")
    joined = "".join(parts)
    assert "Short item one" in joined
    assert "Short item five" not in joined  # past the four-line budget


@pytest.mark.parametrize("brief", [
    "not a marker at all",
    "MARKER-missing",
])
def test_builder_ignores_briefs_without_the_marker(brief):
    assert poster_from_brief(brief, "Heading", "Author") is None


@pytest.mark.parametrize("payload", [
    "{not json",
    "[1, 2, 3]",
    json.dumps({"hero": {"nodes": NODES[:3]}, "modules": MODULES, "gotcha": {"text": "x"},
                "takeaway": ""}),  # missing takeaway
    json.dumps({**_plan(form="flow", nodes=NODES[:3]), "hero": "not a dict"}),
    json.dumps({**_plan(form="flow", nodes=NODES[:3]), "modules": MODULES[:2]}),  # too few modules
    json.dumps({**_plan(form="flow", nodes=NODES[:3]), "gotcha": "not a dict"}),
])
def test_builder_returns_none_for_malformed_plans(payload):
    assert poster_from_brief(MARKER + "\n" + payload, "Heading", "Author") is None


def test_poster_without_tagline_or_gotcha_heading_still_renders():
    plan = _plan(form="flow", nodes=NODES[:3])
    plan.pop("tagline")
    plan["gotcha"] = {"text": "Browser support varies."}
    svg = finalize_svg(poster_from_brief(MARKER + "\n" + json.dumps(plan), "Heading", "Author",
                                          style="guide", theme="ocean"))
    assert svg is not None and "Watch out" in svg
