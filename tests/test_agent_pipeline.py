from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch

import agent


def test_publish_to_linkedin_and_groups_with_image(tmp_path: Path, monkeypatch):
    dummy_img = tmp_path / "post_img.png"
    dummy_img.write_bytes(b"image data")

    mock_li = MagicMock()
    mock_li.post_with_image.return_value = "urn:li:share:123"
    monkeypatch.setattr(agent, "LinkedInClient", MagicMock(return_value=mock_li))

    mock_post_groups = MagicMock(return_value={"success": ["https://linkedin.com/groups/1"]})
    monkeypatch.setattr(agent, "post_to_groups", mock_post_groups)

    mock_tg = MagicMock()
    mock_tg.send_progress_tracker.return_value = 999

    monkeypatch.setenv("LINKEDIN_ACCESS_TOKEN", "fake_token")
    monkeypatch.setitem(agent.CFG, "linkedin", {"api_version": "202610", "target_groups": ["https://linkedin.com/groups/1"], "group_delay_seconds": 0})

    urn = agent.publish_to_linkedin_and_groups(
        post="Test post content",
        image_path=dummy_img,
        headline="Test Headline",
        sources=[{"url": "https://react.dev", "claim": "React 19"}],
        draft_id="d123",
        message_id=456,
        tg=mock_tg,
    )

    assert urn == "urn:li:share:123"
    mock_li.post_with_image.assert_called_once()
    mock_li.comment.assert_called_once()
    mock_tg.mark_posted.assert_called_once_with("d123", 456, "urn:li:share:123")
    mock_post_groups.assert_called_once()


def test_publish_to_linkedin_and_groups_failure(monkeypatch):
    mock_li = MagicMock()
    mock_li.post_text.side_effect = RuntimeError("LinkedIn 401 Unauthorized")
    monkeypatch.setattr(agent, "LinkedInClient", MagicMock(return_value=mock_li))

    mock_tg = MagicMock()
    monkeypatch.setenv("LINKEDIN_ACCESS_TOKEN", "fake_token")

    with pytest.raises(RuntimeError, match="LinkedIn 401 Unauthorized"):
        agent.publish_to_linkedin_and_groups(
            post="Text only post",
            image_path=None,
            headline="Test",
            sources=[],
            draft_id="d-fail",
            message_id=789,
            tg=mock_tg,
        )

    mock_tg.mark_failed.assert_called_once()


def test_publish_after_approval_flows(monkeypatch):
    mock_tg = MagicMock()
    monkeypatch.setattr(agent, "get_status", MagicMock(return_value="approved"))
    monkeypatch.setattr(agent, "publish_to_linkedin_and_groups", MagicMock(return_value="urn:li:share:approved1"))
    monkeypatch.setattr(agent, "append_log", MagicMock())

    # Flow 1: Approved
    mock_tg.wait_for_decision.return_value = {"action": "approved"}
    res1 = agent.publish_after_approval("Title", "react.dev", "Post text", [], Path("img.png"), tg=mock_tg)
    assert res1["status"] == "posted"

    # Flow 2: Revise
    mock_tg.wait_for_decision.return_value = {"action": "revise", "feedback": "Make it punchier"}
    res2 = agent.publish_after_approval("Title", "react.dev", "Post text", [], Path("img.png"), tg=mock_tg)
    assert res2["status"] == "revise"
    assert res2["feedback"] == "Make it punchier"

    # Flow 3: Suggest Topics -> Choose
    mock_tg.wait_for_decision.return_value = {"action": "suggest_topics"}
    monkeypatch.setattr(agent, "suggest_topics", MagicMock(return_value=[{"topic": "Next.js 15", "source": "nextjs.org"}]))
    mock_tg.choose_topic.return_value = {"action": "new_topic", "topic": "Next.js 15", "source": "nextjs.org"}
    res3 = agent.publish_after_approval("Title", "react.dev", "Post text", [], Path("img.png"), tg=mock_tg)
    assert res3["status"] == "new_topic"
    assert res3["topic"] == "Next.js 15"

    # Flow 4: New Topic directly
    mock_tg.wait_for_decision.return_value = {"action": "new_topic", "topic": "Tailwind v4", "source": "tailwindcss.com"}
    res4 = agent.publish_after_approval("Title", "react.dev", "Post text", [], Path("img.png"), tg=mock_tg)
    assert res4["status"] == "new_topic"
    assert res4["topic"] == "Tailwind v4"

    # Flow 5: Rejected
    mock_tg.wait_for_decision.return_value = {"action": "rejected"}
    res5 = agent.publish_after_approval("Title", "react.dev", "Post text", [], Path("img.png"), tg=mock_tg)
    assert res5["status"] == "rejected"


def test_write_draft_topic_and_source(monkeypatch):
    mock_call_json = MagicMock(return_value={
        "post": "Insightful post content on React Compiler",
        "headline": "React Compiler in Action",
        "sources": [{"url": "https://react.dev", "published": "2026-10-25", "claim": "Memoization automation"}],
        "infographic_idea": "Side by side comparison of manual useMemo vs automatic compiler."
    })
    monkeypatch.setattr(agent, "call_json", mock_call_json)

    # 1. Custom topic
    draft1 = agent.write_draft("react.dev", feedback=None, posted=set(), topic="React Compiler")
    assert draft1["headline"] == "React Compiler in Action"

    # 2. Source browsing with feedback
    draft2 = agent.write_draft("openai.com/news/", feedback="Previous post had repetitive words", posted={"https://prev.com"})
    assert "post" in draft2


def test_editorial_review_and_fact_check(tmp_path: Path, monkeypatch):
    dummy_img = tmp_path / "rev_img.png"
    dummy_img.write_bytes(b"dummy image")

    # Mock reviewer approving
    mock_rev_call = {
        "approved": True,
        "scores": {"meaningful": 5, "sourced": 5, "on_topic": 5, "image_text": 5,
                   "image_match": 5, "professional": 5, "technical_depth": 5, "takeaway": 5},
        "issues": []
    }
    mock_fc_call = {
        "approved": True,
        "claims_checked": 1,
        "evidence": [{"url": "https://react.dev", "quote": "React documents reusable interface components"}],
        "issues": []
    }

    monkeypatch.setattr(agent, "call_json", MagicMock(side_effect=[mock_rev_call, mock_fc_call]))
    monkeypatch.setattr(agent, "verify_sources", MagicMock(return_value=[
        {"url": "https://react.dev/", "text": "React documents reusable interface components for practical web applications.",
         "published_dates": []}
    ]))
    monkeypatch.setitem(agent.CFG["review"], "passes", 1)

    ok, issues, detail = agent.review_all(
        "Headline", "Post content",
        [{"url": "https://react.dev", "claim": "React documents reusable interface components"}],
        dummy_img, is_custom_topic=True
    )
    assert ok is True
    assert issues == []


def test_suggest_topics(tmp_path, monkeypatch):
    monkeypatch.setattr(agent, "ROOT", tmp_path)
    monkeypatch.setattr(agent, "load_log", MagicMock(return_value=[]))
    monkeypatch.setattr(agent.random, "sample", lambda values, count: ["react.dev/reference"])
    monkeypatch.setattr(agent, "verify_sources", MagicMock(return_value=[
        {"url": "https://react.dev/reference",
         "text": "React effects synchronize components with external systems when needed.",
         "published_dates": []}
    ]))
    candidate = {
        "topic": "Use React effects only for external synchronization",
        "angle": "Avoid unnecessary effects in local state calculations",
        "technical_takeaway": "Move derived values into render and reserve effects for external systems",
        "topic_kind": "evergreen", "source_url": "https://react.dev/reference",
        "published": None, "source_claim": "Effects synchronize React components with external systems"
    }
    mock_call = MagicMock(side_effect=[candidate, {
        "approved": True,
        "evidence_quote": "React effects synchronize components with external systems when needed.",
        "issues": [],
    }, candidate])
    monkeypatch.setattr(agent, "call_json", mock_call)

    topics = agent.suggest_topics(count=2)
    assert len(topics) >= 1
    assert "topic" in topics[0]
    assert (tmp_path / "topic_history.json").exists()
    assert agent.suggest_topics(count=2) == []


def test_call_anthropic_json_success_and_pause(monkeypatch):
    # Test pause turn followed by successful completion
    mock_pause = MagicMock()
    mock_pause.stop_reason = "pause_turn"
    mock_pause.content = []

    mock_done = MagicMock()
    mock_done.stop_reason = "end_turn"
    mock_block = MagicMock()
    mock_block.type = "text"
    mock_block.text = '{"status": "ok"}'
    mock_done.content = [mock_block]

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [mock_pause, mock_done]
    monkeypatch.setattr(agent, "anthropic_client", mock_client)

    res = agent.call_anthropic_json("system", "content", tools=[{"type": "web_search"}])
    assert res == {"status": "ok"}


def test_call_anthropic_json_max_tokens_error(monkeypatch):
    mock_cut = MagicMock()
    mock_cut.stop_reason = "max_tokens"
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_cut
    monkeypatch.setattr(agent, "anthropic_client", mock_client)

    with pytest.raises(ValueError, match="Model output was cut off"):
        agent.call_anthropic_json("system", "content")


def test_call_openai_json_tools_and_multimodal(monkeypatch):
    mock_client = MagicMock()
    monkeypatch.setattr(agent, "openai_client", mock_client)

    # 1. With tools (responses.create)
    mock_resp = MagicMock()
    mock_resp.output_text = '{"result": "responses_api"}'
    mock_client.responses.create.return_value = mock_resp

    res1 = agent.call_openai_json("system", "content", tools=[{"allowed_domains": ["react.dev"]}])
    assert res1 == {"result": "responses_api"}

    # 2. Without tools + multimodal list (chat.completions.create)
    mock_choice = MagicMock()
    mock_choice.message.content = '{"result": "chat_api"}'
    mock_client.chat.completions.create.return_value.choices = [mock_choice]

    multimodal_content = [
        {"type": "text", "text": "Describe image"},
        {"type": "image", "source": {"data": "base64data", "media_type": "image/png"}}
    ]
    res2 = agent.call_openai_json("system", multimodal_content)
    assert res2 == {"result": "chat_api"}


def test_call_openai_json_self_healing(monkeypatch):
    mock_client = MagicMock()
    monkeypatch.setattr(agent, "openai_client", mock_client)

    # First call returns malformed text, second formatting call returns valid JSON
    bad_choice = MagicMock()
    bad_choice.message.content = "Here is your response without braces."
    good_choice = MagicMock()
    good_choice.message.content = '{"healed": true}'

    mock_client.chat.completions.create.side_effect = [
        MagicMock(choices=[bad_choice]),
        MagicMock(choices=[good_choice]),
    ]

    res = agent.call_openai_json("system", "content")
    assert res == {"healed": True}


def test_handle_direct_post_approved(tmp_path: Path, monkeypatch):
    mock_tg = MagicMock()
    mock_tg.send_draft.return_value = 101
    mock_tg.wait_for_decision.return_value = {"action": "approved"}
    monkeypatch.setattr(agent, "publish_to_linkedin_and_groups", MagicMock(return_value="urn:li:direct:1"))
    monkeypatch.setattr(agent, "append_log", MagicMock())
    monkeypatch.setattr(agent, "ROOT", tmp_path)

    # Provide custom image so SVG design is skipped
    custom_img = tmp_path / "custom.png"
    custom_img.write_bytes(b"data")

    agent.handle_direct_post(
        post_text="Direct post text content",
        custom_image_path=custom_img,
        generate_infographic=False,
        tg=mock_tg,
        tracker_id=555
    )

    mock_tg.send_draft.assert_called_once()
    agent.publish_to_linkedin_and_groups.assert_called_once()


def test_handle_direct_post_cancelled(tmp_path: Path, monkeypatch):
    mock_tg = MagicMock()
    mock_tg.send_text_draft.return_value = 102
    mock_tg.wait_for_decision.return_value = {"action": "rejected"}
    monkeypatch.setattr(agent, "ROOT", tmp_path)

    agent.handle_direct_post(
        post_text="Direct text cancelled",
        custom_image_path=None,
        generate_infographic=False,
        tg=mock_tg,
    )

    mock_tg.send_text_draft.assert_called_once()


def test_run_dry_run_success(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(agent, "ROOT", tmp_path)
    monkeypatch.setattr(agent, "load_log", MagicMock(return_value=[]))
    monkeypatch.setattr(agent, "pick_source", MagicMock(return_value="react.dev/blog"))

    from datetime import datetime, timedelta
    recent_date = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")

    mock_draft = {
        "post": "🚀 Practical insight on modern frontends! " + "word " * 180 + "#Tech #Dev #Coding",
        "headline": "Modern frontend rendering tradeoffs",
        "topic_kind": "evergreen",
        "technical_takeaway": "Check modern frontend rendering tradeoffs before choosing a large library",
        "sources": [{"url": "https://react.dev/blog/item", "published": recent_date, "claim": "Fast builds"}],
        "infographic_idea": "Diagram showing the compilation steps clearly."
    }
    monkeypatch.setattr(agent, "write_draft", MagicMock(return_value=mock_draft))
    monkeypatch.setattr(agent, "design_svg", MagicMock(return_value=f"<svg viewBox='0 0 1080 1350'><text font-size='24'>Title</text><text font-size='22'>A</text><text font-size='22'>B</text></svg>"))
    monkeypatch.setattr(agent, "render_svg", MagicMock())
    monkeypatch.setattr(agent, "render_svg_to_gif", MagicMock())
    monkeypatch.setattr(agent, "review_all", MagicMock(return_value=(True, [], {"scores": {}})))

    mock_tg = MagicMock()
    # Execute dry run pipeline
    agent.run(source_arg="react.dev/blog", dry_run=True, tg=mock_tg, tracker_id=999)
    mock_tg.update_progress.assert_called()

    # A topic selected from Suggest Topics must not reject itself as a duplicate.
    from quality import remember_topic
    remember_topic(tmp_path / "topic_history.json", "Modern frontend rendering tradeoffs",
                   ["https://react.dev/blog/item"], "evergreen",
                   status="suggested", source="react.dev/blog")
    agent.run(source_arg="react.dev/blog", topic_arg="Modern frontend rendering tradeoffs",
              dry_run=True, tg=mock_tg, tracker_id=999)

