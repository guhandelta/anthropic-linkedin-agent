"""The text is made pristine before any drawing, and the poster never shows a cut-off phrase."""
import json
import random
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

import agent
import poster_layout as P
from poster_layout import MARKER, poster_from_brief

LO, HI = agent.CFG["post"]["min_chars"], agent.CFG["post"]["max_chars"]


# ---------------------------------------------------------------- network retries

def test_transient_errors_are_retried_and_permanent_ones_are_not():
    assert agent._is_transient(RuntimeError("peer closed connection without sending complete message"))
    assert agent._is_transient(TimeoutError("Read timed out"))
    assert not agent._is_transient(RuntimeError("Your credit balance is too low"))
    assert not agent._is_transient(ValueError("bad JSON"))


def test_with_network_retries_recovers_from_a_dropped_connection(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    call = MagicMock(side_effect=[RuntimeError("incomplete chunked read"), "ok"])
    assert agent._with_network_retries(call) == "ok"
    assert call.call_count == 2


def test_with_network_retries_gives_up_after_the_last_attempt(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    call = MagicMock(side_effect=RuntimeError("503 service unavailable"))
    with pytest.raises(RuntimeError):
        agent._with_network_retries(call, attempts=3)
    assert call.call_count == 3


def test_with_network_retries_raises_a_permanent_error_at_once(monkeypatch):
    call = MagicMock(side_effect=RuntimeError("quota exceeded"))
    with pytest.raises(RuntimeError):
        agent._with_network_retries(call)
    assert call.call_count == 1


# ---------------------------------------------------------------- length repair

def _post(n: int) -> str:
    body = ("Real detail about bundles and builds. " * 200)[: n - 30]
    return "🚀 " + body.strip() + "\n\n#Tech #Dev #Web #Code"


def test_repair_length_keeps_a_post_that_already_fits(monkeypatch):
    call = MagicMock()
    monkeypatch.setattr(agent, "call_json", call)
    post = _post((LO + HI) // 2)
    monkeypatch.setattr(agent, "fit_to_character_range", lambda p: p)
    assert agent.repair_length(post) == post
    call.assert_not_called()


def test_repair_length_trims_an_overlong_post_in_place(monkeypatch):
    monkeypatch.setattr(agent, "fit_to_character_range", lambda p: p)
    monkeypatch.setattr(agent, "clamp_emojis", lambda p, lo, hi: p)
    fixed = _post((LO + HI) // 2)
    call = MagicMock(return_value={"post": fixed})
    monkeypatch.setattr(agent, "call_json", call)
    assert agent.repair_length(_post(HI + 120)) == fixed
    assert call.call_count == 1
    assert "cut" in call.call_args[0][0]


def test_repair_length_ignores_an_edit_that_makes_it_worse(monkeypatch):
    monkeypatch.setattr(agent, "fit_to_character_range", lambda p: p)
    monkeypatch.setattr(agent, "clamp_emojis", lambda p, lo, hi: p)
    original = _post(LO - 100)
    monkeypatch.setattr(agent, "call_json", MagicMock(side_effect=[
        {"post": _post(LO - 600)}, {"nope": 1}, RuntimeError("offline")]))
    assert agent.repair_length(original) == original


# ---------------------------------------------------------------- JSON check

def test_code_with_json_keys_is_not_mistaken_for_a_raw_json_draft():
    code_post = 'Use fetch:\nconst body = { "name": "x", "id": 1 };\n' + "x " * 10
    assert not any("JSON" in i for i in agent.hard_checks(code_post))
    assert any("JSON" in i for i in agent.hard_checks('{"post": "hello"}'))
    assert any("JSON" in i for i in agent.hard_checks('Intro "headline": "x" more'))


# ---------------------------------------------------------------- reviews

def _ok_review(**_):
    return {"approved": True, "issues": [],
            "scores": {k: 5 for k in ("meaningful", "sourced", "on_topic", "professional",
                                      "technical_depth", "takeaway", "code")}}


def test_review_text_runs_the_fact_check_first(monkeypatch):
    monkeypatch.setattr(agent, "fact_check", MagicMock(return_value={"approved": False,
                                                                     "issues": ["Claim X unsupported"]}))
    call = MagicMock()
    monkeypatch.setattr(agent, "call_json", call)
    ok, issues, detail = agent.review_text("H", "post", [{"url": "u"}])
    assert not ok and issues == ["[fact-check] Claim X unsupported"]
    call.assert_not_called()


def test_review_text_enforces_the_score_threshold_itself(monkeypatch):
    monkeypatch.setattr(agent, "fact_check", MagicMock(return_value={"approved": True}))
    low = _ok_review()
    low["scores"]["takeaway"] = 2  # the model said approved, but one score is too low
    monkeypatch.setattr(agent, "call_json", MagicMock(side_effect=[_ok_review(), low, _ok_review()]))
    ok, issues, detail = agent.review_text("H", "post", [{"url": "u"}])
    assert not ok and len(detail["reviews"]) == 3
    assert any("[review 2]" in i for i in issues)


def test_review_text_custom_topic_needs_one_pass(monkeypatch):
    monkeypatch.setattr(agent, "fact_check", MagicMock(return_value={"approved": True}))
    call = MagicMock(return_value=_ok_review())
    monkeypatch.setattr(agent, "call_json", call)
    ok, issues, _ = agent.review_text("H", "post", [{"url": "u"}], is_custom_topic=True)
    assert ok and not issues and call.call_count == 1


def test_scored_rejects_missing_or_bad_scores():
    assert not agent._scored({"approved": True, "scores": {"a": 5}}, {"a", "b"})["approved"]
    assert not agent._scored({"approved": True, "scores": {"a": "high"}}, {"a"})["approved"]
    assert not agent._scored({"approved": True, "scores": "x"}, {"a"})["approved"]
    assert agent._scored({"approved": True, "scores": {"a": 4}}, {"a"})["approved"]


@pytest.mark.parametrize("error, unavailable", [
    (ValueError("too little readable text on https://solidjs.com"), True),
    (ValueError("something else"), False),
    (requests.ConnectionError("down"), False),
])
def test_fact_check_safely_marks_unreadable_pages(monkeypatch, error, unavailable):
    monkeypatch.setattr(agent, "fact_check", MagicMock(side_effect=error))
    fc = agent._fact_check_safely("post", [])
    assert fc["approved"] is False and fc["source_unavailable"] is unavailable


def test_fact_check_safely_reports_other_http_errors(monkeypatch):
    error = requests.HTTPError("500 Server Error", response=MagicMock(status_code=500))
    monkeypatch.setattr(agent, "fact_check", MagicMock(side_effect=error))
    fc = agent._fact_check_safely("post", [])
    assert fc["approved"] is False and "Source verification failed" in fc["issues"][0]


def test_review_image_sends_the_picture_and_reports_issues(monkeypatch, tmp_path):
    png = tmp_path / "p.png"
    png.write_bytes(b"\x89PNG fake")
    call = MagicMock(return_value={"approved": True, "scores": {"image_text": 5, "image_match": 3},
                                   "issues": ["Label cut off"]})
    monkeypatch.setattr(agent, "call_json", call)
    ok, issues, _ = agent.review_image("H", "post", png)
    assert not ok and issues == ["[image] Label cut off"]
    assert call.call_args[0][1][1]["type"] == "image"


def test_produce_infographic_redraws_only_the_image_with_the_reviewers_notes(monkeypatch, tmp_path):
    monkeypatch.setattr(agent, "plan_infographic", MagicMock(return_value="brief"))
    feedbacks = []

    def draw(post, brief, headline, footer, path, feedback, drafts=None):
        feedbacks.append(feedback)
        path.write_bytes(b"png")
        return path, None

    monkeypatch.setattr(agent, "draw_poster", draw)
    monkeypatch.setattr(agent, "review_image", MagicMock(side_effect=[
        (False, ["[image] Code differs from the post"], {}), (True, [], {"scores": {}})]))
    media, issues, _ = agent.produce_infographic("post", "H", "idea", tmp_path / "p.png")
    assert media.name == "p_2.png" and issues == []
    assert feedbacks == [None, "[image] Code differs from the post"]


def test_produce_infographic_keeps_the_drawing_when_the_reviewer_is_down(monkeypatch, tmp_path):
    monkeypatch.setattr(agent, "plan_infographic", MagicMock(return_value="brief"))
    monkeypatch.setattr(agent, "draw_poster", lambda *a, **k: (tmp_path / "p_1.png", None))
    monkeypatch.setattr(agent, "review_image", MagicMock(side_effect=RuntimeError("offline")))
    media, issues, review = agent.produce_infographic("post", "H", "idea", tmp_path / "p.png")
    assert media == tmp_path / "p_1.png" and issues == [] and review == {}


def test_produce_infographic_reports_when_nothing_could_be_drawn(monkeypatch, tmp_path):
    monkeypatch.setattr(agent, "plan_infographic", MagicMock(return_value="brief"))
    monkeypatch.setattr(agent, "draw_poster", lambda *a, **k: (None, "bad svg"))
    media, issues, _ = agent.produce_infographic("post", "H", "idea", tmp_path / "p.png", tries=2)
    assert media is None and issues == ["[image] bad svg"]


def test_produce_infographic_returns_the_last_drawing_after_every_try_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(agent, "plan_infographic", MagicMock(return_value="brief"))
    monkeypatch.setattr(agent, "draw_poster", lambda post, b, h, f, path, fb, drafts=None: (path, None))
    monkeypatch.setattr(agent, "review_image", MagicMock(return_value=(False, ["[image] x"], {})))
    media, issues, _ = agent.produce_infographic("post", "H", "idea", tmp_path / "p.png", tries=2)
    assert media.name == "p_2.png" and issues == ["[image] x"]


# ---------------------------------------------------------------- verbatim code

def test_code_lines_not_in_the_post_are_dropped():
    post = "Use it:\nconst user = await db.get(id);\nreturn  user;"
    plan = {"modules": [
        {"kind": "code", "lines": ["const user = await db.get(id);", "db.get()  // missing id",
                                   "return user;"]},
        {"kind": "code", "lines": ["invented()"]},
        {"kind": "checklist", "lines": ["Keep this"]},
    ]}
    agent._keep_verbatim_code(plan, post)
    assert plan["modules"] == [
        {"kind": "code", "lines": ["const user = await db.get(id);", "return user;"]},
        {"kind": "checklist", "lines": ["Keep this"]},
    ]
    agent._keep_verbatim_code({"modules": "x"}, post)  # malformed plans are left alone


def test_plan_infographic_filters_code_from_the_blueprint(monkeypatch):
    monkeypatch.setattr(agent, "call_json", MagicMock(return_value={
        "modules": [{"kind": "code", "lines": ["made_up()"]}, {"kind": "stats", "lines": ["1 | a"]}]}))
    brief = agent.plan_infographic("post with real_code()", "H", "idea")
    assert "made_up" not in brief and '"stats"' in brief


# ---------------------------------------------------------------- posters

NODES = [{"label": f"Step {i}", "detail": "Short detail", "icon": "check"} for i in range(4)]
CHECKS = {"kind": "checklist", "heading": "Checks", "icon": "check", "lines": ["One", "Two"]}
STEPS = {"kind": "steps", "heading": "Steps", "icon": "layers", "lines": ["One", "Two"]}


def _plan(**extra):
    plan = {"title": "Faster builds", "subtitle": "What changed", "tagline": "Less waiting",
            "hero": {"form": "flow", "caption": "c", "nodes": NODES},
            "modules": [CHECKS, STEPS, {"kind": "steps", "heading": "More", "lines": ["x"]}],
            "gotcha": {"heading": "Watch out", "text": "Plugins may need updates."},
            "takeaway": "Measure before you switch."}
    plan.update(extra)
    return plan


def _brief(plan):
    return MARKER + "\n" + json.dumps(plan)


def _style(svg):
    return re.search(r'data-style="([a-z_]+)"', svg).group(1)


def test_number_parsing_and_comparability():
    assert P._number("45%") == (45.0, "%")
    assert P._number("120 ms") == (120.0, "ms")
    assert P._number("1,200 req/s") == (1200.0, "req/s")
    assert P._number("$0") == (0.0, "$")
    assert P._number("3,5x") == (3.5, "x")
    assert P._number("v2.1") is None
    assert P._number("12 a very long unit name") is None
    assert P._comparable(["120 ms | Vite", "340 ms | Webpack"])
    assert not P._comparable(["40% | smaller", "3x | faster"])  # different units
    assert not P._comparable(["19 | major", "2 | hooks"])  # unitless unless asked for a chart
    assert P._comparable(["19 | major", "2 | hooks"], chart=True)
    assert not P._comparable(["0 ms | a", "0 ms | b"])
    assert not P._comparable("not a list")


def test_dashboard_draws_a_bar_chart_for_comparable_numbers():
    chart = {"kind": "chart", "heading": "Cold start", "icon": "chart",
             "lines": ["120 ms | Vite 6", "340 ms | Webpack 5", "90 ms | Rspack"]}
    svg = poster_from_brief(_brief(_plan(modules=[chart, CHECKS, STEPS])), "H", "F",
                            style="dashboard", theme="ocean")
    widths = [int(w) for w in re.findall(r'<rect data-motion-grow="1" x="\d+" y="\d+" width="(\d+)" '
                                               r'height="18"', svg)]
    assert len(widths) == 3 and widths[1] == max(widths)  # 340 ms is the longest bar
    assert "340 ms" in svg and "Rspack" in svg


def test_dashboard_tiles_get_a_ring_for_a_percentage():
    stats = {"kind": "stats", "heading": "Numbers", "icon": "chart",
             "lines": ["40% | smaller bundle", "3x | faster start", "100% | typed"]}
    svg = poster_from_brief(_brief(_plan(modules=[stats, CHECKS, STEPS])), "H", "F",
                            style="dashboard", theme="ocean")
    assert svg.count("<circle") == 3  # two tracks and a full ring for 100%
    assert 'stroke-dasharray="none"' in re.search(r"<path d=\"M [^>]*A [^>]*>", svg).group(0)


def test_ring_edge_cases():
    parts: list[str] = []
    P._ring(parts, 0, 0, 10, 0, "#000")
    assert len(parts) == 1  # only the track
    P._ring(parts, 0, 0, 10, 75, "#000")
    assert ' 1 1 ' in parts[-1]  # a large arc past half way


def test_wide_modules_draw_comparable_stats_as_bars():
    chart = {"kind": "stats", "heading": "Latency", "icon": "chart",
             "lines": ["120 ms | p50", "340 ms | p99"]}
    parts: list[str] = []
    P._module(parts, chart, 40, 600, 1000, 186, 1, "#123456")
    assert sum('height="18"' in p for p in parts) == 2


def test_a_layout_that_would_cut_text_is_swapped_for_one_that_fits(monkeypatch):
    plan = _plan()
    first = P._style_order(plan, None, "H")[0]
    real = P._LAYOUTS[first]

    def cutting(parts, *a):
        P._CUTS.append("a phrase cut short")
        real(parts, *a)

    monkeypatch.setitem(P._LAYOUTS, first, cutting)
    assert _style(poster_from_brief(_brief(plan), "H", "F")) != first


def test_when_every_layout_cuts_the_one_with_fewest_cuts_wins(monkeypatch):
    plan = _plan()
    order = P._style_order(plan, None, "H")
    for i, name in enumerate(order):
        real = P._LAYOUTS[name]

        def cutting(parts, *a, real=real, n=abs(i - 1) + 1):
            P._CUTS.extend(["cut"] * n)
            real(parts, *a)

        monkeypatch.setitem(P._LAYOUTS, name, cutting)
    assert _style(poster_from_brief(_brief(plan), "H", "F")) == order[1]


def test_excluding_every_layout_returns_none():
    plan = _plan()
    assert poster_from_brief(_brief(plan), "H", "F",
                             exclude=P._style_order(plan, None, "H")) is None


def test_random_choice_uses_the_roster_and_skips_recent_ones():
    plan = _plan()
    rng = random.Random(7)
    styles = {P.choose_style(plan, ["guide"], "H", rng) for _ in range(40)}
    assert len(styles) == 3 and "guide" not in styles
    themes = {P.choose_theme(plan, ["ocean", "forest"], rng) for _ in range(60)}
    assert len(themes) >= 3 and not themes & {"ocean", "forest"}


def test_random_theme_sometimes_follows_the_planners_hint():
    plan = _plan(theme="ember")
    picks = [P.choose_theme(plan, None, random.Random(i)) for i in range(40)]
    assert 10 < picks.count("ember") < 40


def test_long_watch_out_text_wraps_to_two_lines_instead_of_being_cut():
    plan = _plan(gotcha={"heading": "Watch out",
                         "text": "Older plugins that hook into the legacy loader API need an update "
                                 "before you switch, or the build fails."})
    P._CUTS.clear()
    svg = poster_from_brief(_brief(plan), "H", "F", style="guide", theme="ocean")
    assert not P._CUTS
    assert "or the build fails." in svg


def test_draw_poster_tries_another_structured_layout_before_the_designer(monkeypatch, tmp_path):
    from tests.test_poster_pipeline import BRIEF

    calls = {"n": 0}

    def layout(svg):
        calls["n"] += 1
        return ["overlap"] if calls["n"] == 1 else []

    monkeypatch.setattr(agent, "layout_issues", layout)
    designer = MagicMock()
    monkeypatch.setattr(agent, "design_svg", designer)
    media, feedback = agent.draw_poster("post", BRIEF, "Head", "Footer", tmp_path / "p.png")
    assert media is not None and feedback is None
    assert calls["n"] == 2
    designer.assert_not_called()


CHART = {"kind": "chart", "heading": "Cold start time", "icon": "chart",
         "lines": ["120 ms | Vite 6", "340 ms | Webpack 5", "90 ms | Rspack"]}
RINGS = {"kind": "stats", "heading": "By the numbers", "icon": "chart",
         "lines": ["40% | smaller bundle", "3x | faster cold start", "100% | typed"]}


@pytest.mark.parametrize("theme", sorted(P.THEMES))
@pytest.mark.parametrize("modules", [[CHART, CHECKS, STEPS], [RINGS, CHECKS, STEPS],
                                     [CHECKS, STEPS, CHART, RINGS]])
def test_charts_and_rings_pass_every_poster_check(theme, modules):
    """The new bar charts and rings get the same checks as every layout before publishing."""
    from infographic import design_quality_checks, finalize_svg, svg_checks
    from layout_check import layout_issues

    for style in [s for s in P._eligible(_plan(modules=modules), "H")
                  if s in ("dashboard", "guide", "timeline")]:
        svg = finalize_svg(poster_from_brief(_brief(_plan(modules=modules)), "H", "Guhaprasaanth N",
                                             style=style, theme=theme))
        assert svg_checks(svg) + design_quality_checks(svg) + layout_issues(svg) == [], style


# ---------------------------------------------------------------- pasted posts and motion

def test_a_pasted_post_gets_a_fresh_reviewed_infographic(monkeypatch, tmp_path):
    monkeypatch.setattr(agent, "ROOT", tmp_path)
    monkeypatch.setattr(agent, "call_json", MagicMock(return_value={
        "headline": "Faster builds", "infographic_idea": "Steps"}))
    png = tmp_path / "p.png"
    png.write_bytes(b"png")
    produce = MagicMock(return_value=(png, ["[image] minor"], {}))
    monkeypatch.setattr(agent, "produce_infographic", produce)
    tg = MagicMock()
    tg.wait_for_decision.return_value = {"action": "rejected"}
    agent.handle_direct_post("My own post", custom_image_path=None, generate_infographic=True,
                             tg=tg, tracker_id=1)
    assert produce.call_args.args[:3] == ("My own post", "Faster builds", "Steps")
    tg.send_draft.assert_called_once()


def test_choose_motion_never_repeats_the_last_one():
    from infographic import MOTIONS

    plan = {"title": "Faster builds"}
    for last in MOTIONS:
        assert P.choose_motion(plan, [last]) != last
        assert P.choose_motion(plan, [last], random.Random(3)) != last
    picks = {P.choose_motion(plan, None, random.Random(i)) for i in range(200)}
    assert picks == set(MOTIONS)


def _motion_svg(motion):
    svg = poster_from_brief(_brief(_plan()), "H", "F", style="timeline", theme="ocean")
    return re.sub(r'data-motion="\w+"', f'data-motion="{motion}"', svg)


def _lit(frame, colour):
    return len(re.findall(rf'data-motion-step="\d+"[^>]*stroke="{colour}"', frame))


def test_each_motion_moves_differently():
    from infographic import gif_frame_svgs

    colour = P.THEMES["ocean"]["primary"]
    flow = gif_frame_svgs(_motion_svg("flow"), 12)
    build = gif_frame_svgs(_motion_svg("build"), 12)
    wave = gif_frame_svgs(_motion_svg("wave"), 12)
    pulse = gif_frame_svgs(_motion_svg("pulse"), 12)
    assert [_lit(f, colour) for f in flow].count(1) == 12           # one step at a time
    assert _lit(build[0], colour) < _lit(build[-1], colour)        # steps stay lit
    assert 'height="8"' in build[0] and 'width="1080" height="8"' in build[-1]  # progress bar
    assert all(_lit(f, colour) == 2 for f in wave)                 # neighbours lit together
    assert len({re.search(r'stroke-width="(\d+)"[^>]*data-motion-step|data-motion-step[^>]*'
                          r'stroke-width="(\d+)"', f).groups() for f in pulse}) > 1  # breathing
    assert re.findall(r'stroke-dashoffset="(\d+)"', wave[1])[0] != \
        re.findall(r'stroke-dashoffset="(\d+)"', flow[1])[0]       # connectors flow the other way


def test_unknown_motion_falls_back_to_flow():
    from infographic import gif_frame_svgs

    colour = P.THEMES["ocean"]["primary"]
    frames = gif_frame_svgs(_motion_svg("spin"), 4)
    assert all(_lit(f, colour) == 1 for f in frames)


@pytest.mark.parametrize("motion", ["flow", "wave", "build", "pulse"])
def test_every_motion_keeps_the_gif_frames_clean(motion):
    from infographic import finalize_svg, gif_frame_svgs
    from layout_check import gif_issues

    svg = finalize_svg(_motion_svg(motion))
    assert gif_issues(svg, gif_frame_svgs(svg)) == []


# ---------------------------------------------------------------- repeat check before writing

def _scouted(topic, url="https://react.dev/reference/x"):
    return {"topic": topic, "angle": "an angle", "topic_kind": "evergreen", "source_url": url,
            "technical_takeaway": "Measure the render cost before adding another memo wrapper"}


HISTORY = [{"topic": "React Reference Overview for hooks", "source_urls": ["https://react.dev/reference"],
            "technical_takeaway": "Read the hooks reference before writing custom hooks"}]


def test_a_repeated_topic_is_caught_before_any_post_is_written(monkeypatch):
    scout = MagicMock(side_effect=[_scouted("React Reference Overview for hooks"),
                                   _scouted("Server Components streaming with Suspense boundaries")])
    monkeypatch.setattr(agent, "scout_topic", scout)
    source, item = agent.find_fresh_item("react.dev/reference", HISTORY, set())
    assert source == "react.dev/reference"
    assert item["topic"] == "Server Components streaming with Suspense boundaries"
    # The second scout is told which idea was a repeat.
    assert "React Reference Overview for hooks" in scout.call_args_list[1].args[2]


def test_a_source_that_keeps_repeating_hands_over_to_the_next_source(monkeypatch):
    repeat = _scouted("React Reference Overview for hooks")
    monkeypatch.setattr(agent, "scout_topic", MagicMock(side_effect=[
        repeat, repeat, _scouted("CSS anchor positioning for tooltips", "https://web.dev/anchor")]))
    monkeypatch.setattr(agent, "pick_source", MagicMock(return_value="web.dev/blog"))
    monkeypatch.setattr(agent, "load_log", lambda: [])
    tried = set()
    source, item = agent.find_fresh_item("react.dev/reference", HISTORY, tried)
    assert (source, item["topic"]) == ("web.dev/blog", "CSS anchor positioning for tooltips")
    assert tried == {"react.dev/reference", "web.dev/blog"}


def test_a_fixed_source_is_never_swapped(monkeypatch):
    repeat = _scouted("React Reference Overview for hooks")
    monkeypatch.setattr(agent, "scout_topic", MagicMock(return_value=repeat))
    pick = MagicMock()
    monkeypatch.setattr(agent, "pick_source", pick)
    assert agent.find_fresh_item("react.dev/reference", HISTORY, set(), fixed=True) == (
        "react.dev/reference", None)
    pick.assert_not_called()


def test_a_failed_scout_falls_back_to_the_writer(monkeypatch):
    monkeypatch.setattr(agent, "call_json", MagicMock(side_effect=RuntimeError("credit balance too low")))
    assert agent.scout_topic("react.dev/reference", HISTORY) is None
    assert agent.find_fresh_item("react.dev/reference", HISTORY, set()) == ("react.dev/reference", None)


def test_run_writes_about_the_checked_topic(tmp_path, monkeypatch):
    fresh = _scouted("Server Components streaming with Suspense boundaries")
    monkeypatch.setattr(agent, "ROOT", tmp_path)
    monkeypatch.setattr(agent, "load_log", lambda: [])
    monkeypatch.setattr(agent, "select_model_for_run", lambda *a, **k: "x")
    monkeypatch.setattr(agent, "pick_source", lambda *a, **k: "react.dev/reference")
    monkeypatch.setattr(agent, "find_fresh_item", MagicMock(return_value=("react.dev/reference", fresh)))
    writer = MagicMock(return_value={"no_item": True, "reason": "stop here"})
    monkeypatch.setattr(agent, "write_draft", writer)
    agent.run(dry_run=True)
    assert writer.call_args_list[0].kwargs["item"] == fresh


def test_the_writer_is_told_to_stay_on_the_checked_topic(monkeypatch):
    call = MagicMock(return_value={"post": "x"})
    monkeypatch.setattr(agent, "call_json", call)
    agent.write_draft("react.dev/reference", None, set(), item=_scouted("Suspense streaming"))
    msg = call.call_args.args[1]
    assert "Suspense streaming" in msg and "do not switch" in msg


# ---------------------------------------------------------------- pasted post spacing

PASTED = """Astro Islands vs. Module Federation
Most teams reach for Module Federation.
🧩 Vite / Webpack Module Federation
• Paradigm: Client-side runtime script loading.
• The Catch: heavy runtimes.
The Efficiency Verdict:
If you are building a stateful dashboard, Module Federation holds the crown.


What's your take?
#WebDevelopment #Astro"""


def test_pasted_posts_get_a_blank_line_between_sections():
    assert agent.space_sections(PASTED) == """Astro Islands vs. Module Federation

Most teams reach for Module Federation.

🧩 Vite / Webpack Module Federation
• Paradigm: Client-side runtime script loading.
• The Catch: heavy runtimes.

The Efficiency Verdict:
If you are building a stateful dashboard, Module Federation holds the crown.

What's your take?

#WebDevelopment #Astro"""


def test_spacing_never_pushes_a_post_past_the_linkedin_limit():
    long_post = "\n".join(["A line of the post."] * 150)  # 2999 characters
    assert len(long_post) <= agent.LINKEDIN_LIMIT
    assert agent.space_sections(long_post) == long_post


def test_spacing_is_applied_to_pasted_posts(monkeypatch, tmp_path):
    monkeypatch.setattr(agent, "ROOT", tmp_path)
    monkeypatch.setattr(agent, "select_model_for_run", lambda *a, **k: "x")
    tg = MagicMock()
    tg.wait_for_decision.return_value = "cancelled"
    agent.handle_direct_post(PASTED, generate_infographic=False, tg=tg)
    sent = tg.send_text_draft.call_args.args[2]
    assert "Federation\n\nMost teams" in sent
    assert "\n\n🧩 Vite" in sent


def test_only_the_delivered_poster_is_remembered(monkeypatch, tmp_path):
    from tests.test_poster_pipeline import BRIEF

    monkeypatch.setattr(agent, "ROOT", tmp_path)
    monkeypatch.setattr(agent, "plan_infographic", lambda post, headline, idea: BRIEF)
    monkeypatch.setattr(agent, "layout_issues", lambda svg: [])
    monkeypatch.setattr(agent, "render_svg_to_gif", lambda svg, p: None)
    monkeypatch.setattr(agent, "render_svg", lambda svg, p: Path(p).write_bytes(b"png"))
    reviews = MagicMock(side_effect=[(False, ["wrong order"], {}), (False, ["too busy"], {}),
                                     (True, [], {})])
    monkeypatch.setattr(agent, "review_image", reviews)
    media, issues, _ = agent.produce_infographic("post", "Head", "idea", tmp_path / "info.png")
    assert issues == [] and reviews.call_count == 3
    saved = json.loads(agent.poster_style_path().read_text())
    assert len(saved["styles"]) == 1  # three drafts, one delivered poster
    final = (tmp_path / "info_3.svg").read_text()
    assert f'data-style="{saved["styles"][0]}"' in final
    drafts = [re.search(r'data-style="(\w+)"', (tmp_path / f"info_{n}.svg").read_text()).group(1)
              for n in (1, 2, 3)]
    assert len(set(drafts)) == 3  # each redraw tried a different layout


# ---------------------------------------------------------------- pasted posts over the limit

def test_a_long_pasted_post_is_trimmed_to_fit_before_drawing(monkeypatch, tmp_path):
    monkeypatch.setattr(agent, "ROOT", tmp_path)
    monkeypatch.setattr(agent, "select_model_for_run", lambda *a, **k: "x")
    long_post = "Fact one stays. " * 200 + "\n#WebDev #APIs"   # about 3,200 characters
    short = "Fact one stays. " * 150 + "\n#WebDev #APIs"
    editor = MagicMock(return_value={"post": short})
    monkeypatch.setattr(agent, "call_json", editor)
    tg = MagicMock()
    tg.wait_for_decision.return_value = "cancelled"
    agent.handle_direct_post(long_post, generate_infographic=False, tg=tg)
    sent = tg.send_text_draft.call_args.args[2]
    assert len(sent) <= agent.LINKEDIN_LIMIT and "cut" in editor.call_args.args[0]


def test_a_post_within_the_limit_is_never_edited(monkeypatch, tmp_path):
    monkeypatch.setattr(agent, "ROOT", tmp_path)
    monkeypatch.setattr(agent, "select_model_for_run", lambda *a, **k: "x")
    editor = MagicMock()
    monkeypatch.setattr(agent, "call_json", editor)
    tg = MagicMock()
    tg.wait_for_decision.return_value = "cancelled"
    agent.handle_direct_post("Short post.\n#WebDev", generate_infographic=False, tg=tg)
    editor.assert_not_called()


def test_surplus_hashtags_go_before_any_words(monkeypatch):
    monkeypatch.setattr(agent, "call_json", MagicMock(side_effect=AssertionError("no edit needed")))
    tags = " ".join(f"#Tag{i}" for i in range(12))
    post = "x" * (agent.LINKEDIN_LIMIT - 70) + "\n" + tags
    trimmed = agent.trim_to_limit(post)
    assert trimmed.startswith("x" * 100) and len(trimmed) <= agent.LINKEDIN_LIMIT - 40


def test_when_trimming_fails_the_post_is_kept_and_the_user_is_told(monkeypatch, tmp_path):
    monkeypatch.setattr(agent, "ROOT", tmp_path)
    monkeypatch.setattr(agent, "select_model_for_run", lambda *a, **k: "x")
    monkeypatch.setattr(agent, "call_json", MagicMock(side_effect=RuntimeError("credit balance")))
    tg = MagicMock()
    tg.wait_for_decision.return_value = "cancelled"
    agent.handle_direct_post("word " * 700, generate_infographic=False, tg=tg)
    assert "groups will reject it" in tg._call.call_args.kwargs["text"]
