"""The twelve layouts modelled on popular hand-made infographics: profiles, columns, zigzag,
playbook, scorecard, swimlanes, twin, flowchart, pipeline, snake, pros/cons and masonry."""
import pytest

import poster_layout as P
from infographic import design_quality_checks, svg_checks
from layout_check import layout_issues
from poster_layout import STYLES, choose_style
from tests.test_poster_styles import (CARDS, CHECKS, CODE, CONS, DECISION, LAYERS, PROFILES, PROS,
                                      SCORECARD, STAGES, STATS, STEPS, TABLE, _plan, _style, _svg)

NEW = ("profiles", "columns", "zigzag", "playbook", "scorecard", "swimlanes", "twin", "flowchart",
       "pipeline", "snake", "proscons", "masonry")
SHORT = [{**c, "text": c["fix"]} for c in CARDS]


def test_the_new_layouts_are_registered():
    assert set(NEW) <= set(STYLES) and len(STYLES) == 26
    assert set(NEW) <= set(P._LAYOUTS) and set(NEW) <= set(P.LAYOUT_HINTS)


@pytest.mark.parametrize("style, plan", [
    ("profiles", _plan(profiles=PROFILES[:4])),
    ("columns", _plan(profiles=PROFILES[:3])),
    ("columns", _plan(profiles=[{**p, "about": "Short note."} for p in PROFILES[:5]])),
    ("zigzag", _plan(cards=SHORT[:7])),
    ("zigzag", _plan(cards=CARDS[:6])),
    ("playbook", _plan(cards=CARDS[:4])),
    ("playbook", _plan(cards=SHORT[:6])),
    ("scorecard", _plan("flow", 3, (CHECKS, STEPS, STATS),
                        scorecard={**SCORECARD, "ratio": "", "ratio_caption": ""})),
    ("swimlanes", _plan(layers=LAYERS[:3])),
    ("twin", _plan("flow", 3, table={**TABLE, "left_when": "not a list"})),
    ("flowchart", _plan("flow", 3, decision=DECISION)),
    ("pipeline", _plan(stages=STAGES[:3], modules=[CHECKS, CODE, STEPS], tagline="")),
    ("snake", _plan(cards=SHORT[:6])),
    ("snake", _plan(cards=SHORT[:9])),
    ("proscons", _plan("flow", 3, pros=PROS[:2], cons=CONS[:2])),
    ("masonry", _plan(cards=CARDS[:4])),
    ("masonry", _plan(cards=SHORT[:6])),
])
def test_new_layout_variants_stay_clean(style, plan):
    svg = _svg(plan, style=style, theme="midnight")
    assert _style(svg) == style
    assert svg_checks(svg) + design_quality_checks(svg) + layout_issues(svg) == []


# --- What each layout needs ---

def test_card_list_counts_titled_cards_only():
    assert len(P._card_list(_plan(cards=CARDS[:5] + [{"title": ""}, "x"]), 4, 7)) == 5
    assert P._card_list(_plan(cards=CARDS[:3]), 4, 7) == []
    assert P._card_list(_plan(cards="nope"), 4, 7) == []


def test_profiles_scorecard_decision_and_pros_cons_need_complete_data():
    assert P._profiles(_plan(profiles=PROFILES[:2])) == []
    assert P._profiles(_plan(profiles=[{"name": ""}] * 4)) == []
    assert len(P._profiles(_plan(profiles=PROFILES))) == 6
    assert P._scorecard(_plan(scorecard={**SCORECARD, "right_value": ""})) is None
    assert P._scorecard(_plan(scorecard="x")) is None
    assert P._decision(_plan(decision={**DECISION, "no": ""})) is None
    assert P._pros_cons(_plan(pros=PROS, cons=CONS[:1])) == ([], [])
    assert P._pros_cons(_plan(pros="x", cons=CONS)) == ([], [])
    assert P._strings(["a", "", " b "], 2, 5) == ["a", "b"]


@pytest.mark.parametrize("extra, style, eligible", [
    ({"profiles": PROFILES[:5]}, "profiles", False),   # the grid needs 4 or 6
    ({"profiles": PROFILES}, "columns", False),        # at most 5 columns
    ({"cards": CARDS[:8]}, "zigzag", False),
    ({"cards": CARDS[:4]}, "zigzag", False),
    ({"cards": [{**c, "fix": ""} for c in CARDS[:5]]}, "zigzag", False),
    ({"cards": [{**c, "fix": ""} for c in CARDS[:5]]}, "masonry", False),  # needs every fix
    ({"scorecard": SCORECARD}, "scorecard", False),    # needs a stats module too
    ({"decision": DECISION}, "flowchart", True),
    ({"stages": STAGES}, "pipeline", True),
    ({"cards": CARDS[:3]}, "playbook", False),
    ({"layers": LAYERS[:2]}, "swimlanes", False),
])
def test_layouts_are_offered_only_for_content_they_can_draw(extra, style, eligible):
    assert (style in P._eligible(_plan("flow", 3, (CODE, CHECKS, STEPS), **extra))) is eligible


def test_pipeline_needs_a_plain_list_for_its_notes():
    plan = _plan(stages=STAGES, modules=[CODE, STATS, {**CODE, "heading": "More"}])
    assert "pipeline" not in P._eligible(plan)


@pytest.mark.parametrize("extra, expected", [
    ({"scorecard": SCORECARD}, "scorecard"), ({"decision": DECISION}, "flowchart"),
    ({"pros": PROS, "cons": CONS}, "proscons"), ({"profiles": PROFILES}, "profiles"),
    ({"profiles": PROFILES[:5]}, "columns"), ({"cards": CARDS[:5]}, "zigzag"),
])
def test_new_content_picks_its_layout(extra, expected):
    assert choose_style(_plan("flow", 4, (CODE, CHECKS, STATS), **extra)) == expected


def test_cards_rotate_through_every_card_layout():
    plan = _plan(cards=CARDS[:6])
    seen, recent = [], []
    for _ in range(4):
        style = choose_style(plan, recent)
        seen.append(style)
        recent.append(style)
    assert seen == ["matrix", "zigzag", "playbook", "snake"]
    assert "masonry" in P._eligible(plan)


# --- Drawing details ---

def test_labelled_lists_bold_the_label_and_cut_when_too_long():
    parts: list[str] = []
    P._CUTS.clear()
    assert P._labelled(parts, 0, 0, "Used in", ["Speech", "Time series"], 452, "#123456", 1) == 1
    assert '<tspan font-weight="bold" fill="#123456">Used in:</tspan>' in parts[0]
    assert not P._CUTS
    P._labelled(parts, 0, 0, "Used in", ["A long item"] * 12, 200, "#123456", 2)
    assert P._CUTS


def test_bullets_stop_at_the_budget_and_record_the_loss():
    parts: list[str] = []
    P._CUTS.clear()
    assert P._bullets(parts, 0, 0, ["one", "two", "three"], 300, 2) == 2
    assert P._CUTS == ["three"]
    assert P._bullets(parts, 0, 0, "not a list", 300, 2) == 0


def test_snake_runs_back_and_forth():
    svg = _svg(_plan(cards=SHORT[:6]), style="snake", theme="ocean")
    # The fourth card sits under the third, on the right; the sixth ends on the left.
    xs = [int(x) for x in P.re.findall(r'data-motion-step="\d+" x="(\d+)"', svg)]
    assert xs[2] == xs[3] and xs[5] == xs[0]


def test_flowchart_draws_the_decision_and_its_loop():
    svg = _svg(_plan("flow", 5, decision=DECISION), style="flowchart", theme="ocean")
    assert "<polygon" in svg and "<polyline" in svg and "YES" in svg and "NO" in svg
    assert "Enough evidence?" in svg and "Cited final" in svg


def test_masonry_overflow_counts_as_a_cut():
    long = [{**c, "text": c["text"] * 3, "fix": c["fix"] * 3} for c in CARDS[:6]]
    P._CUTS.clear()
    P.poster_from_brief(P.MARKER + "\n" + __import__("json").dumps(_plan(cards=long)), "H", "F",
                        style="masonry", theme="ocean")
    assert "masonry overflow" in P._CUTS


def test_swimlanes_and_proscons_record_text_that_does_not_fit():
    long = [{"name": "Lane", "items": [{"label": "A very long component label", "detail": "Detail"}] * 3}] * 4
    plan = _plan(layers=long)
    P._CUTS.clear()
    P._layout_swimlanes([], plan, "H", list(P.ACCENTS))
    assert "Detail" in P._CUTS
    P._CUTS.clear()
    P._layout_proscons([], _plan(pros=["A long benefit that wraps over several lines in the narrow pros column"] * 5,
                                 cons=CONS), "H", list(P.ACCENTS))
    assert P._CUTS


def test_malformed_numbers_are_not_numbers():
    assert P._number("1.2.3 ms") is None
