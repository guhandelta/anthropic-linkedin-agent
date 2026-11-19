"""Reasoning-effort settings sent to each provider for the configured models."""
from unittest.mock import MagicMock

import agent


def test_anthropic_effort_uses_output_config(monkeypatch):
    monkeypatch.setitem(agent.CFG, "reasoning_effort", "medium")
    assert agent._anthropic_effort_kwargs() == {"output_config": {"effort": "medium"}}
    monkeypatch.setitem(agent.CFG, "reasoning_effort", None)
    assert agent._anthropic_effort_kwargs() == {}


def test_call_anthropic_json_sends_effort(monkeypatch):
    monkeypatch.setitem(agent.CFG, "reasoning_effort", "medium")
    client = MagicMock()
    client.messages.create.return_value = MagicMock(
        stop_reason="end_turn", content=[MagicMock(type="text", text='{"ok": true}')])
    monkeypatch.setattr(agent, "anthropic_client", client)
    assert agent.call_anthropic_json("sys", "hi") == {"ok": True}
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["output_config"] == {"effort": "medium"}
    assert "temperature" not in kwargs


def test_openai_sol_is_reasoning_model(monkeypatch):
    monkeypatch.setitem(agent.CFG, "reasoning_effort", "medium")
    kw = agent._openai_chat_kwargs("gpt-6-sol", 4000)
    assert kw == {"max_completion_tokens": 4000, "reasoning_effort": "medium"}
    legacy = agent._openai_chat_kwargs("gpt-4o", 4000)
    assert legacy == {"max_tokens": 4000, "temperature": 0.7}


def test_openai_research_sends_reasoning_effort(monkeypatch):
    monkeypatch.setitem(agent.CFG, "reasoning_effort", "medium")
    monkeypatch.setitem(agent.CFG, "openai_fallback_model", "gpt-6-sol")
    client = MagicMock()
    client.responses.create.return_value = MagicMock(output_text='{"a": 1}')
    monkeypatch.setattr(agent, "openai_client", client)
    assert agent.call_openai_json("sys", "q", tools=[{"allowed_domains": ["x.com"]}]) == {"a": 1}
    assert client.responses.create.call_args.kwargs["reasoning"] == {"effort": "medium"}


def test_gemini_thinking_level(monkeypatch):
    monkeypatch.setitem(agent.CFG, "reasoning_effort", "medium")
    assert agent._gemini_thinking_config().thinking_level.value == "MEDIUM"
    monkeypatch.setitem(agent.CFG, "reasoning_effort", "")
    assert agent._gemini_thinking_config() is None
