"""Trying a provider's lower models before switching to another AI."""
import pytest

import agent


@pytest.fixture(autouse=True)
def chains(monkeypatch):
    monkeypatch.setitem(agent.CFG, "model", "claude-sonnet-5-5")
    monkeypatch.setitem(agent.CFG, "openai_fallback_model", "gpt-6.1-sol")
    monkeypatch.setitem(agent.CFG, "gemini_fallback_model", "gemini-3.8-flash")
    monkeypatch.setitem(agent.CFG, "model_fallbacks", {
        "anthropic": ["claude-sonnet-4-6"], "openai": ["gpt-6-sol"], "gemini": ["gemini-3.1-pro-preview"]})
    monkeypatch.setattr(agent, "CURRENT_TELEGRAM_REVIEWER", None)


def test_provider_models_order():
    assert agent.provider_models("anthropic") == ["claude-sonnet-5-5", "claude-sonnet-4-6"]
    assert agent.provider_models("openai") == ["gpt-6.1-sol", "gpt-6-sol"]
    assert agent.provider_models("gemini") == ["gemini-3.8-flash", "gemini-3.1-pro-preview"]


def test_no_fallbacks_configured(monkeypatch):
    monkeypatch.setitem(agent.CFG, "model_fallbacks", None)
    assert agent.provider_models("anthropic") == ["claude-sonnet-5-5"]


@pytest.mark.parametrize("msg,expected", [
    ("Error code: 529 - overloaded_error", True),
    ("Error code: 404 - model not found", True),
    ("Could not parse valid JSON from model output", True),
    ("Error code: 429 - insufficient_quota: You have no credits remaining", False),
    ("Your credit balance is too low to access the Anthropic API", False),
    ("Error code: 401 - invalid x-api-key authentication_error", False),
    ("Model output was cut off. Increase max_tokens.", False),
])
def test_model_specific_classification(msg, expected):
    assert agent.is_model_specific_failure(RuntimeError(msg)) is expected


def test_lower_model_used_after_overload():
    seen = []

    def call():
        seen.append(agent.current_model("anthropic"))
        if len(seen) == 1:
            raise RuntimeError("Error code: 529 - overloaded_error")
        return "ok"

    assert agent.call_with_lower_models("anthropic", call) == "ok"
    assert seen == ["claude-sonnet-5-5", "claude-sonnet-4-6"]
    # The lower model sticks for the rest of the run
    assert agent.current_model("anthropic") == "claude-sonnet-4-6"


def test_credit_error_skips_lower_models():
    seen = []

    def call():
        seen.append(agent.current_model("openai"))
        raise RuntimeError("Error code: 429 - insufficient_quota")

    with pytest.raises(RuntimeError):
        agent.call_with_lower_models("openai", call)
    assert seen == ["gpt-6.1-sol"]


def test_all_lower_models_fail_then_raise():
    seen = []

    def call():
        seen.append(agent.current_model("gemini"))
        raise RuntimeError("503 service unavailable")

    with pytest.raises(RuntimeError):
        agent.call_with_lower_models("gemini", call)
    assert seen == ["gemini-3.8-flash", "gemini-3.1-pro-preview"]


def test_call_json_tries_lower_model_before_next_provider(monkeypatch):
    monkeypatch.setattr(agent, "ACTIVE_LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(agent, "_failover_chain", lambda start: ["anthropic", "gemini"])
    monkeypatch.setattr(agent, "_with_network_retries", lambda call: call())
    calls = []

    def fake_claude(system, content, tools=None, max_tokens=4000):
        calls.append(agent.current_model("anthropic"))
        if len(calls) == 1:
            raise RuntimeError("Error code: 404 - not_found_error model")
        return {"ok": True}

    def fake_gemini(*a, **k):
        raise AssertionError("Gemini should not be needed")

    monkeypatch.setattr(agent, "call_anthropic_json", fake_claude)
    monkeypatch.setattr(agent, "call_gemini_json", fake_gemini)
    assert agent.call_json("sys", "hi") == {"ok": True}
    assert calls == ["claude-sonnet-5-5", "claude-sonnet-4-6"]
