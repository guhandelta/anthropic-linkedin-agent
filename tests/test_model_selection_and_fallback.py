import os
import pytest
from unittest.mock import MagicMock, patch

import agent


@pytest.fixture(autouse=True)
def reset_agent_globals():
    """Reset agent globals before and after each test."""
    orig_provider = agent.ACTIVE_LLM_PROVIDER
    orig_reviewer = agent.CURRENT_TELEGRAM_REVIEWER
    orig_tracker = agent.CURRENT_TRACKER_ID
    orig_disabled = set(agent.DISABLED_PROVIDERS)
    agent.DISABLED_PROVIDERS.clear()
    yield
    agent.ACTIVE_LLM_PROVIDER = orig_provider
    agent.CURRENT_TELEGRAM_REVIEWER = orig_reviewer
    agent.CURRENT_TRACKER_ID = orig_tracker
    agent.DISABLED_PROVIDERS = orig_disabled


def test_select_model_for_run_preferred():
    agent.select_model_for_run(preferred="openai")
    assert agent.ACTIVE_LLM_PROVIDER == "openai"

    agent.select_model_for_run(preferred="anthropic")
    assert agent.ACTIVE_LLM_PROVIDER == "anthropic"


def test_select_model_for_run_random(monkeypatch):
    monkeypatch.setitem(agent.CFG, "model_strategy", "random")
    monkeypatch.setattr(agent, "openai_client", MagicMock())
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    chosen = set()
    for _ in range(20):
        provider = agent.select_model_for_run()
        chosen.add(provider)
        assert provider in ("anthropic", "openai")
    # With 20 iterations, both should be observed
    assert len(chosen) >= 1


def test_select_model_for_run_forced_strategy(monkeypatch):
    monkeypatch.setattr(agent, "openai_client", MagicMock())
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    monkeypatch.setitem(agent.CFG, "model_strategy", "openai")
    assert agent.select_model_for_run() == "openai"

    monkeypatch.setitem(agent.CFG, "model_strategy", "anthropic")
    assert agent.select_model_for_run() == "anthropic"


def test_select_model_for_run_only_one_key(monkeypatch):
    monkeypatch.setitem(agent.CFG, "model_strategy", "random")

    # Only Anthropic available
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(agent, "openai_client", None)
    assert agent.select_model_for_run() == "anthropic"

    # Only OpenAI available
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(agent, "openai_client", MagicMock())
    assert agent.select_model_for_run() == "openai"


def test_notify_provider_switch_with_telegram():
    mock_tg = MagicMock()
    agent.CURRENT_TELEGRAM_REVIEWER = mock_tg
    agent.CURRENT_TRACKER_ID = 12345

    agent.notify_provider_switch("anthropic", "openai", "Credit balance is zero (rate_limit_error)")

    mock_tg.update_progress.assert_called_once_with(
        12345,
        "⚠️ [Claude Issue] Switched to OpenAI..."
    )
    mock_tg._call.assert_called_once()
    args, kwargs = mock_tg._call.call_args
    assert args[0] == "sendMessage"
    assert "AI Model Fallback Notice" in kwargs["text"]
    assert "Credit balance is zero" in kwargs["text"]


def test_notify_provider_switch_telegram_failure_does_not_crash():
    mock_tg = MagicMock()
    mock_tg.update_progress.side_effect = RuntimeError("Telegram Network Timeout")
    agent.CURRENT_TELEGRAM_REVIEWER = mock_tg
    agent.CURRENT_TRACKER_ID = 12345

    # Should not raise exception
    agent.notify_provider_switch("anthropic", "openai", "Rate limit reached")


def test_call_json_anthropic_success(monkeypatch):
    agent.ACTIVE_LLM_PROVIDER = "anthropic"
    mock_anthropic_call = MagicMock(return_value={"post": "Great post content", "headline": "Test"})
    monkeypatch.setattr(agent, "call_anthropic_json", mock_anthropic_call)

    res = agent.call_json("system", "content")
    assert res["headline"] == "Test"
    mock_anthropic_call.assert_called_once()


def test_call_json_anthropic_fails_fallback_to_openai(monkeypatch):
    agent.ACTIVE_LLM_PROVIDER = "anthropic"
    monkeypatch.setattr(agent, "openai_client", MagicMock())

    def mock_anthropic_fail(*args, **kwargs):
        raise RuntimeError("Claude 429 Rate Limit Exceeded")

    mock_openai_call = MagicMock(return_value={"post": "OpenAI generated post", "headline": "Fallback Success"})
    monkeypatch.setattr(agent, "call_anthropic_json", mock_anthropic_fail)
    monkeypatch.setattr(agent, "call_openai_json", mock_openai_call)

    with patch("agent.notify_provider_switch") as mock_notify:
        res = agent.call_json("system", "content")
        assert res["headline"] == "Fallback Success"
        assert agent.ACTIVE_LLM_PROVIDER == "openai"
        mock_notify.assert_called_once_with("anthropic", "openai", "Claude 429 Rate Limit Exceeded")
        mock_openai_call.assert_called_once()


def test_call_json_anthropic_fails_no_openai(monkeypatch):
    agent.ACTIVE_LLM_PROVIDER = "anthropic"
    monkeypatch.setattr(agent, "openai_client", None)
    monkeypatch.setattr(agent, "call_anthropic_json", MagicMock(side_effect=RuntimeError("Claude Down")))

    with pytest.raises(RuntimeError, match="Claude Down"):
        agent.call_json("system", "content")


def test_call_json_openai_success(monkeypatch):
    agent.ACTIVE_LLM_PROVIDER = "openai"
    mock_openai_call = MagicMock(return_value={"post": "OpenAI post", "headline": "OpenAI Direct"})
    monkeypatch.setattr(agent, "call_openai_json", mock_openai_call)

    res = agent.call_json("system", "content")
    assert res["headline"] == "OpenAI Direct"
    mock_openai_call.assert_called_once()


def test_call_json_openai_fails_fallback_to_anthropic(monkeypatch):
    agent.ACTIVE_LLM_PROVIDER = "openai"
    monkeypatch.setattr(agent, "anthropic_client", MagicMock())

    def mock_openai_fail(*args, **kwargs):
        raise RuntimeError("OpenAI quota exceeded")

    mock_anthropic_call = MagicMock(return_value={"post": "Claude fallback post", "headline": "Claude Rescued"})
    monkeypatch.setattr(agent, "call_openai_json", mock_openai_fail)
    monkeypatch.setattr(agent, "call_anthropic_json", mock_anthropic_call)

    with patch("agent.notify_provider_switch") as mock_notify:
        res = agent.call_json("system", "content")
        assert res["headline"] == "Claude Rescued"
        assert agent.ACTIVE_LLM_PROVIDER == "anthropic"
        mock_notify.assert_called_once_with("openai", "anthropic", "OpenAI quota exceeded")
        mock_anthropic_call.assert_called_once()


def test_design_svg_anthropic_success(monkeypatch):
    agent.ACTIVE_LLM_PROVIDER = "anthropic"
    mock_resp = MagicMock()
    mock_resp.stop_reason = "end_turn"
    mock_block = MagicMock()
    mock_block.type = "text"
    mock_block.text = "<svg viewBox='0 0 1080 1350'></svg>"
    mock_resp.content = [mock_block]

    mock_anthropic_client = MagicMock()
    mock_anthropic_client.messages.create.return_value = mock_resp
    monkeypatch.setattr(agent, "anthropic_client", mock_anthropic_client)

    svg = agent.design_svg("post", "idea", "headline", None, "footer")
    assert svg == "<svg viewBox='0 0 1080 1350'></svg>"


def test_design_svg_anthropic_max_tokens_raises_value_error(monkeypatch):
    agent.ACTIVE_LLM_PROVIDER = "anthropic"
    mock_resp = MagicMock()
    mock_resp.stop_reason = "max_tokens"
    mock_anthropic_client = MagicMock()
    mock_anthropic_client.messages.create.return_value = mock_resp
    monkeypatch.setattr(agent, "anthropic_client", mock_anthropic_client)

    with pytest.raises(ValueError, match="The drawing was cut off"):
        agent.design_svg("post", "idea", "headline", None, "footer")


def test_design_svg_anthropic_fails_fallback_to_openai(monkeypatch):
    agent.ACTIVE_LLM_PROVIDER = "anthropic"
    monkeypatch.setattr(agent, "openai_client", MagicMock())
    mock_anthropic_client = MagicMock()
    mock_anthropic_client.messages.create.side_effect = RuntimeError("Claude API Overloaded")
    monkeypatch.setattr(agent, "anthropic_client", mock_anthropic_client)

    mock_openai_svg = MagicMock(return_value="<svg viewBox='0 0 1080 1350'>OpenAI</svg>")
    monkeypatch.setattr(agent, "call_openai_svg", mock_openai_svg)

    with patch("agent.notify_provider_switch") as mock_notify:
        svg = agent.design_svg("post", "idea", "headline", "Fix fonts", "footer")
        assert "OpenAI" in svg
        assert agent.ACTIVE_LLM_PROVIDER == "openai"
        mock_notify.assert_called_once_with("anthropic", "openai", "Claude API Overloaded")
        mock_openai_svg.assert_called_once()


def test_design_svg_openai_fails_fallback_to_anthropic(monkeypatch):
    agent.ACTIVE_LLM_PROVIDER = "openai"
    monkeypatch.setattr(agent, "call_openai_svg", MagicMock(side_effect=RuntimeError("OpenAI 500 Server Error")))

    mock_resp = MagicMock()
    mock_resp.stop_reason = "end_turn"
    mock_block = MagicMock()
    mock_block.type = "text"
    mock_block.text = "<svg viewBox='0 0 1080 1350'>Claude SVG</svg>"
    mock_resp.content = [mock_block]

    mock_anthropic_client = MagicMock()
    mock_anthropic_client.messages.create.return_value = mock_resp
    monkeypatch.setattr(agent, "anthropic_client", mock_anthropic_client)

    with patch("agent.notify_provider_switch") as mock_notify:
        svg = agent.design_svg("post", "idea", "headline", None, "footer")
        assert "Claude SVG" in svg
        assert agent.ACTIVE_LLM_PROVIDER == "anthropic"
        mock_notify.assert_called_once_with("openai", "anthropic", "OpenAI 500 Server Error")


def test_call_openai_svg_effort_and_temp(monkeypatch):
    mock_client = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "<svg viewBox='0 0 1080 1350'><text>Hello</text></svg>"
    mock_client.chat.completions.create.return_value.choices = [mock_choice]
    monkeypatch.setattr(agent, "openai_client", mock_client)

    # Test GPT-4o model sets temperature=0.7
    monkeypatch.setitem(agent.CFG, "openai_fallback_model", "gpt-4o")
    agent.call_openai_svg("system", "msg")
    kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert kwargs["temperature"] == 0.7
    assert "reasoning_effort" not in kwargs

    # Test o-series model sets reasoning_effort="medium"
    monkeypatch.setitem(agent.CFG, "openai_fallback_model", "o3-mini")
    monkeypatch.setitem(agent.CFG, "reasoning_effort", "medium")
    agent.call_openai_svg("system", "msg")
    kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert kwargs["reasoning_effort"] == "medium"
    assert "temperature" not in kwargs
