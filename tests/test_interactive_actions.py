"""Interactive GitHub Actions runs: topic pick, text approval before drawing, Telegram inbox."""
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import agent
import telegram_inbox
import telegram_review

ROOT = Path(agent.__file__).parent


def _draft():
    recent = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    return {
        "post": ("🚀 Check modern frontend rendering tradeoffs before choosing a large library. "
                 "#Tech #Dev #Coding"),
        "headline": "Modern frontend rendering tradeoffs",
        "topic_kind": "evergreen",
        "technical_takeaway": "Check modern frontend rendering tradeoffs before choosing a large library",
        "sources": [{"url": "https://react.dev/blog/item", "published": recent, "claim": "Fast builds"}],
        "infographic_idea": "Diagram showing the compilation steps clearly.",
    }


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    monkeypatch.setattr(agent, "ROOT", tmp_path)
    monkeypatch.setattr(agent, "load_log", MagicMock(return_value=[]))
    monkeypatch.setattr(agent, "pick_source", MagicMock(return_value="react.dev/blog"))
    monkeypatch.setattr(agent, "select_model_for_run", MagicMock())
    monkeypatch.setattr(agent, "find_fresh_item", lambda source, *a, **k: (source, None))
    monkeypatch.setattr(agent, "repair_length", lambda post: post)
    monkeypatch.setattr(agent, "hard_checks", lambda post: [])
    monkeypatch.setattr(agent, "source_checks", lambda *a, **k: [])
    monkeypatch.setattr(agent, "duplicate_topic", lambda *a, **k: False)
    monkeypatch.setattr(agent, "remember_topic", lambda *a, **k: None)
    monkeypatch.setattr(agent, "drop_dead_sources", lambda sources: sources)
    write = MagicMock(return_value=_draft())
    monkeypatch.setattr(agent, "write_draft", write)
    monkeypatch.setattr(agent, "review_text", MagicMock(return_value=(True, [], {"reviews": []})))
    monkeypatch.setattr(agent, "call_json", MagicMock(side_effect=RuntimeError("offline")))
    image = tmp_path / "poster.png"
    image.write_bytes(b"png")
    produce = MagicMock(return_value=(image, [], {}))
    monkeypatch.setattr(agent, "produce_infographic", produce)
    publish = MagicMock(return_value={"status": "posted"})
    monkeypatch.setattr(agent, "publish_after_approval", publish)
    return {"write": write, "produce": produce, "publish": publish}


def test_text_is_approved_before_the_infographic_is_drawn(pipeline, monkeypatch):
    order = []
    approve = MagicMock(side_effect=lambda *a, **k: order.append("text") or {"status": "approved"})
    monkeypatch.setattr(agent, "approve_text", approve)
    pipeline["produce"].side_effect = lambda *a, **k: order.append("image") or (Path("x.png"), [], {})
    pipeline["publish"].side_effect = lambda *a, **k: order.append("final") or {"status": "posted"}
    assert agent.run(source_arg="react.dev/blog", tg=MagicMock(), tracker_id=1, text_first=True) == "posted"
    assert order == ["text", "image", "final"]


def test_rejected_text_draws_nothing(pipeline, monkeypatch):
    monkeypatch.setattr(agent, "approve_text", MagicMock(return_value={"status": "rejected"}))
    assert agent.run(source_arg="react.dev/blog", tg=MagicMock(), tracker_id=1, text_first=True) == "declined"
    pipeline["produce"].assert_not_called()
    pipeline["publish"].assert_not_called()


def test_text_notes_rewrite_the_post_then_ask_again(pipeline, monkeypatch):
    approve = MagicMock(side_effect=[{"status": "revise", "feedback": "Shorter hook"},
                                     {"status": "approved"}])
    monkeypatch.setattr(agent, "approve_text", approve)
    assert agent.run(source_arg="react.dev/blog", tg=MagicMock(), tracker_id=1, text_first=True) == "posted"
    assert approve.call_count == 2
    assert pipeline["write"].call_args_list[1].args[1] == "Shorter hook"
    pipeline["produce"].assert_called_once()


def test_without_text_first_the_old_single_approval_stays(pipeline, monkeypatch):
    approve = MagicMock()
    monkeypatch.setattr(agent, "approve_text", approve)
    assert agent.run(source_arg="react.dev/blog", tg=MagicMock(), tracker_id=1) == "posted"
    approve.assert_not_called()


def test_approve_text_uses_the_text_stage_and_its_own_wait(monkeypatch):
    tg = MagicMock()
    tg.send_text_draft.return_value = 7
    tg.wait_for_decision.return_value = {"action": "approved"}
    monkeypatch.setitem(agent.CFG["telegram"], "text_wait_minutes", 90)
    res = agent.approve_text("Head", "Post body", [{"url": "https://react.dev/a"}], tg)
    assert res == {"status": "approved"}
    assert tg.send_text_draft.call_args.kwargs["approve_label"] == "✅ Approve text"
    kwargs = tg.wait_for_decision.call_args.kwargs
    assert kwargs["stage"] == "text" and kwargs["timeout_s"] == 90 * 60


def test_interactive_session_offers_topics_then_runs_text_first(monkeypatch):
    tg = MagicMock()
    tg.choose_topic.return_value = {"action": "new_topic", "topic": "React use()", "source": "react.dev"}
    monkeypatch.setattr(agent, "select_model_for_run", MagicMock())
    monkeypatch.setattr(agent, "suggest_topics", MagicMock(return_value=[{"topic": "React use()"}]))
    run = MagicMock(return_value="posted")
    monkeypatch.setattr(agent, "run", run)
    assert agent.interactive_session(tg=tg) == "posted"
    assert run.call_args.kwargs["topic_arg"] == "React use()"
    assert run.call_args.kwargs["source_arg"] == "react.dev"
    assert run.call_args.kwargs["text_first"] is True


def test_interactive_session_without_a_pick_posts_nothing(monkeypatch):
    tg = MagicMock()
    tg.choose_topic.return_value = {"action": "expired"}
    monkeypatch.setattr(agent, "select_model_for_run", MagicMock())
    monkeypatch.setattr(agent, "suggest_topics", MagicMock(return_value=[{"topic": "A"}]))
    run = MagicMock()
    monkeypatch.setattr(agent, "run", run)
    assert agent.interactive_session(tg=tg) == "declined"
    run.assert_not_called()


def test_interactive_session_with_a_topic_skips_suggestions(monkeypatch):
    monkeypatch.setattr(agent, "select_model_for_run", MagicMock())
    suggest = MagicMock()
    monkeypatch.setattr(agent, "suggest_topics", suggest)
    monkeypatch.setattr(agent, "run", MagicMock(return_value="posted"))
    assert agent.interactive_session("My topic", tg=MagicMock()) == "posted"
    suggest.assert_not_called()


def test_text_stage_wait_uses_its_own_timeout_and_wording(monkeypatch):
    reviewer = telegram_review.TelegramReviewer("t", "1", timeout_s=3 * 3600, remind_every_s=10_000)
    sent = []
    monkeypatch.setattr(reviewer, "_call", lambda method, **p: sent.append(p.get("text")) or {})
    monkeypatch.setattr(reviewer, "_poll_updates", lambda params: [])
    monkeypatch.setattr(telegram_review, "set_status", lambda *a, **k: None)
    assert reviewer.wait_for_decision("d", 5, timeout_s=0, stage="text") == {"action": "expired"}
    assert any("No answer within 0 minutes" in (t or "") for t in sent)
    assert telegram_review._duration(7200) == "2 hours" and telegram_review._duration(5400) == "90 minutes"


# ------------------------------------------------------------------ inbox
OWNER = "42"


def _msg(uid, text, sender=OWNER, age=0, now=1_000_000, **extra):
    return {"update_id": uid, "message": {"message_id": uid, "date": now - age, "text": text,
                                          "from": {"id": int(sender)}, "chat": {"id": int(sender)},
                                          **extra}}


def _plan(*updates, now=1_000_000):
    inbox = telegram_inbox.TelegramInbox("t", OWNER)
    return telegram_inbox.plan_linkedin(list(updates), inbox, now=now)


def test_inbox_routes_commands_to_one_run():
    assert _plan(_msg(1, "/topic React compiler"))["run"] == {"mode": "topic", "topic": "React compiler"}
    assert _plan(_msg(1, "💡 Suggest Topics"))["run"] == {"mode": "suggest"}
    assert _plan(_msg(1, "🚀 Run Daily Post"))["run"] == {"mode": "suggest"}
    assert _plan(_msg(1, "Edge caching basics"))["run"] == {"mode": "topic", "topic": "Edge caching basics"}
    long_post = "A pasted post " * 10
    assert _plan(_msg(1, long_post))["run"] == {"mode": "direct", "text": long_post.strip()}
    assert _plan(_msg(1, "/direct Short post"))["run"] == {"mode": "direct", "text": "Short post"}


def test_inbox_prompt_taps_wait_for_the_next_text():
    plan = _plan(_msg(1, "📝 Direct Post"), _msg(2, "Short post text"))
    assert plan["run"] == {"mode": "direct", "text": "Short post text"}
    plan = _plan(_msg(1, "✍️ Post from Topic"))
    assert plan["run"] is None and "Send the topic" in plan["replies"][0]


def test_inbox_answers_help_and_status_without_a_run():
    plan = _plan(_msg(1, "/help"), _msg(2, "/status"))
    assert plan["run"] is None and len(plan["replies"]) == 2
    assert "every 15 minutes" in plan["replies"][0]


def test_inbox_ignores_strangers_and_old_messages():
    assert _plan(_msg(1, "/topic X", sender="99"))["run"] is None
    assert _plan(_msg(1, "/topic X", age=telegram_inbox.MAX_AGE_S + 5))["run"] is None


def test_inbox_tells_the_owner_about_messages_it_waited_too_long_for():
    old = telegram_inbox.MAX_AGE_S + 3 * 3600
    plan = _plan(_msg(1, "📝 Direct Post", age=old), _msg(2, "/status"))
    assert plan["run"] is None
    assert "GitHub only ran my inbox check now" in plan["replies"][0]
    assert "'📝 Direct Post'" in plan["replies"][0] and "6 hours ago" in plan["replies"][0]
    assert "Posts" in plan["replies"][1] or "No posts" in plan["replies"][1]
    assert _plan(_msg(1, "/topic X", sender="99", age=old))["replies"] == []
    assert _plan(_msg(1, "/help"))["replies"][0].startswith("🤖")


def test_inbox_starts_only_the_latest_request():
    plan = _plan(_msg(1, "/topic First"), _msg(2, "/topic Second"))
    assert plan["run"] == {"mode": "topic", "topic": "Second"}
    assert "only the latest" in plan["replies"][-1]


def test_inbox_handles_old_buttons():
    cq = {"update_id": 3, "callback_query": {"id": "c1", "data": "approve:old",
                                             "from": {"id": 42}, "message": {"chat": {"id": 42}, "date": 1}}}
    plan = _plan(cq)
    assert plan["run"] is None and "ended" in plan["callbacks"][0][1]
    cq["callback_query"]["data"] = "retry_last"
    assert _plan(cq)["run"] == {"mode": "suggest"}


def test_inbox_main_leaves_telegram_alone_while_a_run_is_active(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", OWNER)
    monkeypatch.setattr(telegram_inbox, "posting_run_active", lambda repo, wf: True)
    fetch = MagicMock()
    monkeypatch.setattr(telegram_inbox.TelegramInbox, "fetch", fetch)
    assert telegram_inbox.main() == 0
    fetch.assert_not_called()


def test_inbox_main_starts_the_run_then_confirms(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", OWNER)
    monkeypatch.setattr(telegram_inbox, "posting_run_active", lambda repo, wf: False)
    import time as _time
    updates = [_msg(5, "/topic Vite 7", now=int(_time.time()))]
    calls = []
    monkeypatch.setattr(telegram_inbox.TelegramInbox, "fetch", lambda self: updates)
    monkeypatch.setattr(telegram_inbox.TelegramInbox, "reply", lambda self, t: calls.append(("reply", t)))
    monkeypatch.setattr(telegram_inbox.TelegramInbox, "confirm", lambda self, u: calls.append(("confirm", len(u))))
    monkeypatch.setattr(telegram_inbox, "start_posting_run",
                        lambda repo, wf, ref, run: calls.append(("start", run["topic"])))
    assert telegram_inbox.main() == 0
    assert [c[0] for c in calls] == ["start", "reply", "confirm"]
    assert calls[0] == ("start", "Vite 7")


def test_start_posting_run_sends_the_right_inputs(monkeypatch):
    sent = []
    monkeypatch.setattr(telegram_inbox, "_github", lambda m, path, **k: sent.append((m, path, k["json"])))
    telegram_inbox.start_posting_run("o/r", "daily-post.yml", "main", {"mode": "direct", "text": "Hi"})
    method, path, body = sent[0]
    assert method == "POST" and path.endswith("/workflows/daily-post.yml/dispatches")
    assert body == {"ref": "main", "inputs": {"run_mode": "direct", "topic": "", "post_text": "Hi"}}


def test_workflows_wire_the_interactive_run_and_inbox():
    daily = (ROOT / ".github/workflows/daily-post.yml").read_text()
    assert "args=(--interactive)" in daily and "--interactive --direct" in daily
    assert "timeout-minutes: 350" in daily
    inbox = (ROOT / ".github/workflows/inbox-check.yml").read_text()
    assert 'cron: "*/15 * * * *"' in inbox and "actions: write" in inbox
    assert "python telegram_inbox.py" in inbox


def test_a_picked_topic_is_written_from_its_checked_page(monkeypatch):
    seen = {}
    monkeypatch.setattr(agent, "call_json", lambda system, msg, **k: seen.update(msg=msg, tools=k.get("tools")) or {})
    monkeypatch.setattr(agent, "source_page_text", lambda url: "The API opens an always-on-top window.")
    item = {"topic": "Document PiP", "source_url": "https://developer.mozilla.org/en-US/docs/Web/API/Document_Picture-in-Picture_API",
            "angle": "Custom PiP windows", "technical_takeaway": "Use requestWindow for custom controls",
            "source_claim": "opens an always-on-top window"}
    agent.write_draft("developer.mozilla.org/en-US/docs/Web/API", "[fact-check] claim not supported", set(),
                      topic="Document PiP", item=item)
    assert item["source_url"] in seen["msg"]
    assert "The API opens an always-on-top window." in seen["msg"]
    assert "delete it or replace it" in seen["msg"]


def test_a_failed_topic_offers_the_remaining_ones(monkeypatch):
    tg = MagicMock()
    a, b = {"topic": "A", "source": "s"}, {"topic": "B", "source": "s"}
    tg.choose_topic.side_effect = [{"action": "new_topic", "topic": "A", "source": "s", "item": a},
                                   {"action": "new_topic", "topic": "B", "source": "s", "item": b}]
    monkeypatch.setattr(agent, "select_model_for_run", MagicMock())
    monkeypatch.setattr(agent, "suggest_topics", MagicMock(return_value=[a, b]))
    run = MagicMock(side_effect=[None, "posted"])
    monkeypatch.setattr(agent, "run", run)
    assert agent.interactive_session(tg=tg) == "posted"
    assert run.call_args_list[0].kwargs["item_arg"] is a and run.call_args_list[1].kwargs["item_arg"] is b
    assert tg.choose_topic.call_args_list[1].args[1] == [b]


def test_dead_cited_pages_are_dropped_but_one_source_always_stays(monkeypatch):
    def fetch(url, allowed):
        if "dead" in url:
            raise ValueError("Source page not found (404)")
        return {"text": "ok", "published_dates": []}
    monkeypatch.setattr(agent, "fetch_source_page", fetch)
    good, dead = {"url": "https://web.dev/good"}, {"url": "https://web.dev/dead"}
    assert agent.drop_dead_sources([dead, good]) == [good]
    assert agent.drop_dead_sources([dead, {"url": "https://web.dev/dead2"}]) == [dead, {"url": "https://web.dev/dead2"}]
    assert agent.drop_dead_sources([dead]) == [dead]


def test_reviewers_defer_to_the_fact_check_on_sourcing(monkeypatch):
    monkeypatch.setattr(agent, "_fact_check_safely", lambda post, sources: {"approved": True})
    seen = []
    monkeypatch.setattr(agent, "call_json", lambda system, content, **k: seen.append(system) or {
        "scores": {k2: 5 for k2 in ("meaningful", "sourced", "on_topic", "professional",
                                    "technical_depth", "takeaway", "code")}, "approved": True})
    ok, issues, _ = agent.review_text("H", "post", [{"url": "https://x", "claim": "c"}], is_custom_topic=True)
    assert ok and "already compared every claim with the full text" in seen[0]


def test_index_pages_are_not_accepted_as_a_topic_page(monkeypatch):
    monkeypatch.setattr(agent, "SOURCES", ["developer.mozilla.org/en-US/docs/Web/API", "web.dev/blog"])
    assert agent.is_index_page("https://developer.mozilla.org/en-US/docs/Web/API")
    assert agent.is_index_page("https://developer.mozilla.org/en-US/docs/Web/API/")
    assert agent.is_index_page("https://web.dev")
    assert not agent.is_index_page("https://developer.mozilla.org/en-US/docs/Web/API/ResizeObserver")
    assert not agent.is_index_page("https://web.dev/learn/css/anchor-positioning")


def test_buttons_on_an_older_topic_list_are_ignored(monkeypatch):
    reviewer = telegram_review.TelegramReviewer("t", "1")
    calls, answers = [], []
    monkeypatch.setattr(reviewer, "_call", lambda method, **p: calls.append(method) or {"message_id": 9})
    monkeypatch.setattr(reviewer, "_answer_cq", lambda cid, text: answers.append(text))

    def cq(uid, data):
        return {"update_id": uid, "callback_query": {"id": str(uid), "data": data, "from": {"id": 1},
                                                      "message": {"chat": {"id": 1}}}}
    batches = [[cq(1, "opt_skip:old-list"), cq(2, "pick_topic:2:old-list"), cq(3, "pick_topic:0:new-list")]]
    monkeypatch.setattr(reviewer, "_poll_updates", lambda params: batches.pop(0) if batches else [])
    res = reviewer.choose_topic("new-list", [{"topic": "A", "source": "s"}], timeout_s=5)
    assert res["action"] == "new_topic" and res["topic"] == "A"
    assert answers[:2] == ["That list has closed. Use the newest one below."] * 2


def test_dated_suggestions_need_their_date_on_the_page(tmp_path, monkeypatch):
    monkeypatch.setattr(agent, "ROOT", tmp_path)
    monkeypatch.setattr(agent, "load_log", MagicMock(return_value=[]))
    monkeypatch.setattr(agent.random, "sample", lambda values, count: ["react.dev/blog"])
    monkeypatch.setattr(agent, "source_checks", lambda *a, **k: [])
    monkeypatch.setattr(agent, "verify_sources", MagicMock(return_value=[
        {"url": "u", "text": "React 20 ships a new compiler mode for apps.", "published_dates": []}]))
    monkeypatch.setattr(agent, "verify_topic_suggestion", lambda item, page: True)
    candidate = {"topic": "React compiler release notes today", "angle": "What changed",
                 "technical_takeaway": "Turn on the new compiler mode and measure renders",
                 "topic_kind": "update", "source_url": "https://react.dev/blog/2026/11/01/react-20",
                 "published": None, "source_claim": "React 20 ships a new compiler mode"}
    monkeypatch.setattr(agent, "call_json", MagicMock(return_value=candidate))
    assert agent.suggest_topics(count=1) == []


def test_a_menu_tap_keeps_the_topic_list_open_on_actions(monkeypatch):
    reviewer = telegram_review.TelegramReviewer("t", "1")
    reviewer.menu_closes_lists = False
    sent = []
    monkeypatch.setattr(reviewer, "_call", lambda method, **p: sent.append(p.get("text")) or {"message_id": 9})
    monkeypatch.setattr(reviewer, "_answer_cq", lambda cid, text: None)
    status = {"update_id": 1, "message": {"text": "📊 Status & History", "from": {"id": 1}, "chat": {"id": 1}}}
    pick = {"update_id": 2, "callback_query": {"id": "c", "data": "pick_topic:0:L", "from": {"id": 1},
                                               "message": {"chat": {"id": 1}}}}
    batches = [[status], [pick]]
    monkeypatch.setattr(reviewer, "_poll_updates", lambda params: batches.pop(0) if batches else [])
    assert reviewer.choose_topic("L", [{"topic": "A", "source": "s"}], timeout_s=5)["topic"] == "A"
    assert any("still open" in (t or "") for t in sent) and reviewer.deferred == []


def test_history_merge_keeps_main_entries_and_adds_the_runs(tmp_path):
    import json, importlib.util
    spec = importlib.util.spec_from_file_location("merge_history", ROOT / "scripts/merge_history.py")
    mh = importlib.util.module_from_spec(spec); spec.loader.exec_module(mh)
    run, main = tmp_path / "run", tmp_path / "main"
    run.mkdir(); main.mkdir()
    (main / "topic_history.json").write_text(json.dumps([{"topic": "A"}, {"topic": "M"}]))
    (run / "topic_history.json").write_text(json.dumps([{"topic": "A"}, {"topic": "R"}]))
    (run / "posted.json").write_text(json.dumps([{"draft_id": "d1"}]))
    mh.main(str(run), str(main))
    assert json.loads((main / "topic_history.json").read_text()) == [{"topic": "A"}, {"topic": "M"}, {"topic": "R"}]
    assert json.loads((main / "posted.json").read_text()) == [{"draft_id": "d1"}]
