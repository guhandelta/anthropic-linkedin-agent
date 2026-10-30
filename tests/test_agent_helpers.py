import json
from pathlib import Path
import pytest
from unittest.mock import MagicMock

import agent


def test_domain_for_source():
    assert agent.domain_for_source("react.dev/blog") == "react.dev"
    assert agent.domain_for_source("https://www.openai.com/news/") == "openai.com"
    assert agent.domain_for_source("daily.dev/tags/generative-ui") == "daily.dev"


def test_domain_allowed():
    assert agent.domain_allowed("https://react.dev/blog/2024/new-feature") is True
    assert agent.domain_allowed("https://blog.langchain.dev/article") is True
    assert agent.domain_allowed("https://malicious-site.com/fake-news") is False


def test_extract_json_object():
    valid_json = '{"headline": "Test Title", "post": "Test post content"}'
    assert agent.extract_json_object(valid_json)["headline"] == "Test Title"

    with_markdown = '```json\n{"headline": "Inside Code Block"}\n```'
    assert agent.extract_json_object(with_markdown)["headline"] == "Inside Code Block"

    with_surrounding = 'Some intro text\n{"headline": "Embedded"}\nSome outro notes'
    assert agent.extract_json_object(with_surrounding)["headline"] == "Embedded"

    with pytest.raises(ValueError, match="Could not parse valid JSON"):
        agent.extract_json_object("Not JSON at all")


def test_clamp_emojis():
    # Post with 10 emojis should be clamped to max_emojis (7)
    text = "🚀 A 💡 B ⚡ C 🛠️ D 🎯 E 📦 F 🔍 G 💥 H 🌟 I ✨ J"
    clamped = agent.clamp_emojis(text)
    found = agent.EMOJI_RE.findall(clamped)
    assert len(found) <= agent.CFG["post"]["max_emojis"]


def test_hard_checks():
    short_post = "Too short"
    issues = agent.hard_checks(short_post)
    assert any("must be >=" in i for i in issues)

    # Post with adjacent emojis
    adjacent_emoji_post = "Check this out 🚀💡! " + "word " * 180 + "#Tech #AI #Coding"
    issues2 = agent.hard_checks(adjacent_emoji_post)
    assert any("emojis next to each other" in i for i in issues2)


def test_source_checks():
    from datetime import datetime, timedelta
    recent_date = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    sources = [
        {"url": "https://react.dev/blog/2026/react-19", "published": recent_date, "claim": "React 19 compiler"},
    ]
    posted = set()
    issues = agent.source_checks(sources, posted, is_custom_topic=False)
    assert issues == []

    # Non-whitelisted domain
    disallowed_source = [
        {"url": "https://randomblog.com/post", "published": "2026-10-20", "claim": "claim"},
    ]
    issues2 = agent.source_checks(disallowed_source, posted, is_custom_topic=False)
    assert any("not on the allowed list" in i for i in issues2)

    # Already posted URL
    already_posted = {"https://react.dev/blog/2026/react-19"}
    issues3 = agent.source_checks(sources, already_posted, is_custom_topic=False)
    assert any("Already posted before" in i for i in issues3)


def test_pick_source():
    log = [{"source_domain": "react.dev", "date": "2026-10-28T10:00:00"}]
    picked = agent.pick_source(log, exclude={"openai.com"})
    assert picked is not None
    assert picked != "openai.com"


def test_load_and_append_log(tmp_path: Path, monkeypatch):
    log_file = tmp_path / "test_posted.json"
    monkeypatch.setattr(agent, "ROOT", tmp_path)

    assert agent.load_log() == []

    entry = {"date": "2026-10-29T10:00:00", "headline": "Test Entry", "post_urn": "urn:li:post:123"}
    agent.append_log(entry)

    loaded = agent.load_log()
    assert len(loaded) == 1
    assert loaded[0]["headline"] == "Test Entry"

    urls = agent.posted_urls(loaded)
    assert isinstance(urls, set)


def test_get_agent_status_text(monkeypatch):
    monkeypatch.setattr(agent, "load_log", MagicMock(return_value=[
        {"date": "2026-10-29T12:00:00", "headline": "Status Test Headline", "source_domain": "react.dev"}
    ]))
    status_text = agent.get_agent_status_text()
    assert "LinkedIn Agent Status & History" in status_text
    assert "Status Test Headline" in status_text
    assert "Primary LLM:" in status_text
    assert "Currently Active:" in status_text


def test_is_claude_limit_error():
    assert agent.is_claude_limit_error(Exception("rate_limit_error: 429")) is True
    assert agent.is_claude_limit_error(Exception("credit balance is zero")) is True
    assert agent.is_claude_limit_error(Exception("SyntaxError in code")) is False


def test_web_tools():
    tools = agent.web_tools(["react.dev", "web.dev"])
    assert len(tools) == 1
    assert tools[0]["type"] == agent.CFG["research"]["search_tool"]
    assert "react.dev" in tools[0]["allowed_domains"]
