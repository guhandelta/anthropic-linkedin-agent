"""The diagram layout: parts in columns joined by elbow arrows, drawn from the planner's graph."""
import re

import pytest

from infographic import design_quality_checks, svg_checks
from layout_check import layout_issues
from poster_layout import _eligible, _graph, _style_candidates, choose_style
from tests.test_poster_styles import _plan, _style, _svg


def part(i, label=None):
    return {"id": i, "label": label or i.title(), "detail": "A short detail", "icon": "gear"}


def graph(nodes, edges):
    return {"nodes": nodes, "edges": [{"from": a, "to": b} for a, b in edges]}


# a -> b, a -> c, b -> d: three columns, the middle one holds two parts
FLOW = graph([part("a", "Webhook"), part("b", "Agent"), part("c", "Memory"), part("d", "Approval")],
             [("a", "b"), ("a", "c"), ("b", "d")])
# four columns, the widest holds three parts, and every arrow joins neighbouring columns
DEEP = graph([part("in"), part("agent"), part("memory"), part("model"), part("tools"),
              part("gate")],
             [("in", "agent"), ("agent", "memory"), ("agent", "model"), ("agent", "tools"),
              ("model", "gate"), ("tools", "gate")])
TWO = graph([part("a"), part("b"), part("c")], [("a", "b"), ("a", "c")])


def _with(g):
    return _plan("flow", 3, graph=g, title="How the parts connect")


def _segments(svg):
    """Every drawn arrow as a list of (x1, y1, x2, y2) segments."""
    out = []
    for points in re.findall(r'<polyline points="([^"]+)"', svg):
        xy = [tuple(map(float, p.split(","))) for p in points.split()]
        out.append([(*a, *b) for a, b in zip(xy, xy[1:])])
    return out


def _boxes(svg):
    return [tuple(map(float, m)) for m in re.findall(
        r'<rect data-motion-step="\d+" x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)"',
        svg)]


def test_no_graph_or_a_graph_of_the_wrong_shape_gives_no_diagram():
    assert _graph({}) is None
    assert _graph({"graph": "not a dict"}) is None
    assert _graph({"graph": []}) is None
    assert _graph(_with({"nodes": [part("a")], "edges": []})["graph"]) is None  # fewer than 3 parts


def test_a_valid_graph_keeps_its_parts_in_reading_order():
    g = _graph(_with(FLOW))
    assert g["levels"] == 3
    assert [n["id"] for n in g["nodes"]] == ["a", "b", "c", "d"]
    assert [n["depth"] for n in g["nodes"]] == [0, 1, 1, 2]
    assert sorted(g["edges"]) == [("a", "b"), ("a", "c"), ("b", "d")]


def test_parts_without_an_id_or_label_are_ignored_and_ids_must_be_unique():
    g = graph([part("a"), part("b"), part("c"), {"label": "no id"}, {"id": "e"}],
              [("a", "b"), ("a", "c")])
    assert [n["id"] for n in _graph(_with(g))["nodes"]] == ["a", "b", "c"]
    assert _graph(_with(graph([part("a"), part("a"), part("c")], [("a", "c"), ("c", "a")]))) is None


def test_arrows_to_unknown_parts_or_to_themselves_are_dropped():
    g = graph([part("a"), part("b"), part("c")],
              [("a", "b"), ("a", "zzz"), ("b", "b"), ("a", "c")])
    assert sorted(_graph(_with(g))["edges"]) == [("a", "b"), ("a", "c")]


def test_a_loop_gives_no_diagram():
    loop = graph([part("a"), part("b"), part("c")], [("a", "b"), ("b", "c"), ("c", "a")])
    assert _graph(_with(loop)) is None


def test_an_arrow_that_skips_a_column_is_dropped_and_the_rest_are_kept():
    g = graph([part("a"), part("b"), part("c"), part("d")],
              [("a", "b"), ("a", "d"), ("b", "c"), ("a", "c")])
    parsed = _graph(_with(g))
    assert parsed["levels"] == 3 and ("a", "c") not in parsed["edges"]
    assert sorted(parsed["edges"]) == [("a", "b"), ("a", "d"), ("b", "c")]


def test_too_few_arrows_or_too_many_columns_or_crowded_columns_give_no_diagram():
    assert _graph(_with(graph([part("a"), part("b"), part("c")], [("a", "b")]))) is None
    chain = graph([part(x) for x in "abcde"], [("a", "b"), ("b", "c"), ("c", "d"), ("d", "e")])
    assert _graph(_with(chain)) is None  # five columns
    crowd = graph([part("a"), part("b"), part("c"), part("d"), part("e")],
                  [("a", "b"), ("a", "c"), ("a", "d"), ("a", "e")])
    assert _graph(_with(crowd)) is None  # four parts in one column


def test_long_part_ids_are_shortened_consistently():
    long_id = "x" * 30
    g = graph([part(long_id), part("b"), part("c")], [(long_id, "b"), (long_id, "c")])
    parsed = _graph(_with(g))
    assert parsed["nodes"][0]["id"] == "x" * 24
    assert ("x" * 24, "b") in parsed["edges"]


def test_the_diagram_draws_every_part_and_every_arrow():
    svg = _svg(_with(DEEP), style="diagram", theme="ocean")
    assert _style(svg) == "diagram"
    assert len(_segments(svg)) == len(DEEP["edges"])
    assert len(_boxes(svg)) == len(DEEP["nodes"])
    for label in ("In", "Agent", "Memory", "Model", "Tools", "Gate"):
        assert label in svg


def test_arrows_never_cross_a_part():
    svg = _svg(_with(DEEP), style="diagram", theme="midnight")
    boxes = _boxes(svg)
    for line in _segments(svg):
        for x1, y1, x2, y2 in line:
            lo_x, hi_x, lo_y, hi_y = min(x1, x2), max(x1, x2), min(y1, y2), max(y1, y2)
            for bx, by, bw, bh in boxes:
                crosses = bx < hi_x and bx + bw > lo_x and by < hi_y and by + bh > lo_y
                assert not crosses, (x1, y1, x2, y2, bx, by)


def test_a_diagram_is_chosen_only_when_the_planner_gave_one():
    assert choose_style(_with(FLOW)) == "diagram"
    assert _style_candidates(_with(FLOW))[0] == "diagram"
    assert "diagram" not in _eligible(_plan())
    assert choose_style(_plan()) != "diagram"


@pytest.mark.parametrize("g", [FLOW, DEEP, TWO])
def test_the_diagram_passes_every_check(g):
    svg = _svg(_with(g), style="diagram", theme="grape")
    assert _style(svg) == "diagram"
    assert svg_checks(svg) + design_quality_checks(svg) + layout_issues(svg) == []


def test_a_straight_chain_is_not_a_diagram():
    chain = graph([part("a"), part("b"), part("c")], [("a", "b"), ("b", "c")])
    assert _graph(_with(chain)) is None
