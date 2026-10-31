import base64
from unittest.mock import MagicMock

import pytest

import agent


@pytest.fixture(autouse=True)
def reset_globals():
    orig = agent.ACTIVE_LLM_PROVIDER
    agent.DISABLED_PROVIDERS.clear()
    yield
    agent.ACTIVE_LLM_PROVIDER = orig
    agent.DISABLED_PROVIDERS.clear()


def _gemini(monkeypatch, text='{"ok": true}'):
    client = MagicMock()
    client.models.generate_content.return_value = MagicMock(text=text)
    monkeypatch.setattr(agent, "gemini_client", client)
    return client


def test_fmt_provider_gemini():
    assert agent._fmt_provider("gemini") == "Gemini"


def test_select_model_prefers_gemini_strategy_and_last_resort(monkeypatch):
    _gemini(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setitem(agent.CFG, "model_strategy", "gemini")
    assert agent.select_model_for_run() == "gemini"
    # With Claude and OpenAI unavailable, Gemini is chosen automatically
    monkeypatch.setitem(agent.CFG, "model_strategy", "random")
    monkeypatch.setattr(agent, "openai_client", None)
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert agent.select_model_for_run() == "gemini"


def test_call_gemini_json_plain_mode(monkeypatch):
    client = _gemini(monkeypatch)
    assert agent.call_gemini_json("sys", "hello") == {"ok": True}
    cfg = client.models.generate_content.call_args.kwargs["config"]
    assert cfg.response_mime_type == "application/json"


def test_call_gemini_json_search_and_multimodal(monkeypatch):
    client = _gemini(monkeypatch, text='noise {"a": 1} noise')
    png = base64.b64encode(b"\x89PNG").decode()
    content = [{"type": "text", "text": "look"},
               {"type": "image", "source": {"data": png, "media_type": "image/png"}}]
    tools = [{"type": "web_search", "allowed_domains": ["react.dev"]}, "ignored"]
    assert agent.call_gemini_json("sys", content, tools=tools) == {"a": 1}
    cfg = client.models.generate_content.call_args.kwargs["config"]
    assert cfg.tools and "react.dev" in cfg.system_instruction
    assert len(client.models.generate_content.call_args.kwargs["contents"]) == 2


def test_call_gemini_json_search_without_domains(monkeypatch):
    _gemini(monkeypatch)
    assert agent.call_gemini_json("sys", "x", tools=[{"type": "web_search"}]) == {"ok": True}


def test_call_gemini_requires_key():
    with pytest.raises(RuntimeError, match="Gemini API key"):
        agent.call_gemini_json("s", "m")
    with pytest.raises(RuntimeError, match="Gemini API key"):
        agent.call_gemini_svg("s", "m")


def test_call_gemini_svg_strips_emoji(monkeypatch):
    _gemini(monkeypatch, text='<svg viewBox="0 0 1080 1350"><text x="1" y="2">Hi 🚀</text></svg>')
    svg = agent.call_gemini_svg("sys", "msg")
    assert "<svg" in svg and "🚀" not in svg


def test_call_json_chain_claude_openai_gemini(monkeypatch):
    _gemini(monkeypatch)
    monkeypatch.setattr(agent, "openai_client", MagicMock())
    agent.ACTIVE_LLM_PROVIDER = "anthropic"
    monkeypatch.setattr(agent, "call_anthropic_json", MagicMock(side_effect=RuntimeError("claude down")))
    monkeypatch.setattr(agent, "call_openai_json", MagicMock(side_effect=RuntimeError("openai down")))
    monkeypatch.setattr(agent, "call_gemini_json", MagicMock(return_value={"from": "gemini"}))
    assert agent.call_json("s", "m") == {"from": "gemini"}
    assert agent.ACTIVE_LLM_PROVIDER == "gemini"
    assert {"anthropic", "openai"} <= agent.DISABLED_PROVIDERS


def test_call_json_raises_when_gemini_also_fails(monkeypatch):
    _gemini(monkeypatch)
    monkeypatch.setattr(agent, "openai_client", None)
    agent.ACTIVE_LLM_PROVIDER = "anthropic"
    monkeypatch.setattr(agent, "call_anthropic_json", MagicMock(side_effect=RuntimeError("claude down")))
    monkeypatch.setattr(agent, "call_gemini_json", MagicMock(side_effect=RuntimeError("gemini down")))
    with pytest.raises(RuntimeError, match="gemini down"):
        agent.call_json("s", "m")


def test_call_json_gemini_active_fails_over_to_claude(monkeypatch):
    _gemini(monkeypatch)
    monkeypatch.setattr(agent, "openai_client", None)
    agent.ACTIVE_LLM_PROVIDER = "gemini"
    monkeypatch.setattr(agent, "call_gemini_json", MagicMock(side_effect=RuntimeError("gemini down")))
    monkeypatch.setattr(agent, "call_anthropic_json", MagicMock(return_value={"from": "claude"}))
    assert agent.call_json("s", "m") == {"from": "claude"}


def test_design_svg_chain_reaches_gemini(monkeypatch):
    _gemini(monkeypatch)
    monkeypatch.setattr(agent, "openai_client", MagicMock())
    agent.ACTIVE_LLM_PROVIDER = "anthropic"
    monkeypatch.setattr(agent, "_call_claude_svg", MagicMock(side_effect=RuntimeError("claude down")))
    monkeypatch.setattr(agent, "call_openai_svg", MagicMock(side_effect=RuntimeError("openai down")))
    monkeypatch.setattr(agent, "call_gemini_svg", MagicMock(return_value="<svg/>"))
    assert agent.design_svg("post", "idea", "Head", None, "foot") == "<svg/>"


def test_design_svg_claude_cutoff_does_not_fail_over(monkeypatch):
    _gemini(monkeypatch)
    agent.ACTIVE_LLM_PROVIDER = "anthropic"
    monkeypatch.setattr(agent, "_call_claude_svg", MagicMock(side_effect=ValueError("cut off")))
    with pytest.raises(ValueError, match="cut off"):
        agent.design_svg("post", "idea", "Head", None, "foot")
