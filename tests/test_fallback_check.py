from unittest.mock import MagicMock

import pytest
from anthropic import BadRequestError

import agent
from scripts import check_fallback


def test_simulated_billing_error_matches_anthropic_failure():
    error = check_fallback.simulated_anthropic_billing_error()
    assert isinstance(error, BadRequestError)
    assert error.status_code == 400
    assert "credit balance" in str(error)


def test_fallback_check_uses_openai_then_gemini_and_does_not_publish(monkeypatch):
    monkeypatch.setattr(agent, "openai_client", MagicMock())
    monkeypatch.setattr(agent, "gemini_client", MagicMock())
    monkeypatch.setattr(agent, "call_openai_json", MagicMock(return_value={"ok": True}))
    monkeypatch.setattr(agent, "call_gemini_json", MagicMock(return_value={"ok": True}))
    monkeypatch.setattr(agent, "publish_after_approval", MagicMock())
    agent.DISABLED_PROVIDERS.clear()
    try:
        check_fallback.main()
        assert agent.ACTIVE_LLM_PROVIDER == "gemini"
        agent.call_openai_json.assert_called_once()
        agent.call_gemini_json.assert_called_once()
        agent.publish_after_approval.assert_not_called()
    finally:
        agent.DISABLED_PROVIDERS.clear()


def test_fallback_check_requires_openai_key(monkeypatch):
    monkeypatch.setattr(agent, "openai_client", None)
    with pytest.raises(SystemExit, match="OPENAI_API_KEY"):
        check_fallback.main()


def test_fallback_check_requires_gemini_key(monkeypatch):
    monkeypatch.setattr(agent, "openai_client", MagicMock())
    monkeypatch.setattr(agent, "gemini_client", None)
    with pytest.raises(SystemExit, match="GOOGLE_API_KEY"):
        check_fallback.main()


@pytest.mark.parametrize(
    ("start", "expected_order"),
    [
        ("anthropic", ["anthropic", "openai", "gemini"]),
        ("openai", ["openai", "anthropic", "gemini"]),
        ("gemini", ["gemini", "anthropic", "openai"]),
    ],
)
def test_each_provider_can_fail_over_to_both_others(monkeypatch, start, expected_order):
    calls = []

    def provider_call(name):
        def call(*args, **kwargs):
            calls.append(name)
            if name == expected_order[-1]:
                return {"ok": True}
            if name == "anthropic":
                raise check_fallback.simulated_anthropic_billing_error()
            raise RuntimeError(f"Simulated {name} failure")
        return call

    monkeypatch.setattr(agent, "anthropic_client", MagicMock())
    monkeypatch.setattr(agent, "openai_client", MagicMock())
    monkeypatch.setattr(agent, "gemini_client", MagicMock())
    monkeypatch.setattr(agent, "call_anthropic_json", provider_call("anthropic"))
    monkeypatch.setattr(agent, "call_openai_json", provider_call("openai"))
    monkeypatch.setattr(agent, "call_gemini_json", provider_call("gemini"))
    monkeypatch.setattr(agent, "CURRENT_TELEGRAM_REVIEWER", None)
    monkeypatch.setattr(agent, "publish_after_approval", MagicMock())
    agent.ACTIVE_LLM_PROVIDER = start
    agent.DISABLED_PROVIDERS.clear()
    try:
        assert agent.call_json("system", "content") == {"ok": True}
        assert calls == expected_order
        assert agent.ACTIVE_LLM_PROVIDER == expected_order[-1]
        assert set(expected_order[:-1]) <= agent.DISABLED_PROVIDERS
        agent.publish_after_approval.assert_not_called()
    finally:
        agent.DISABLED_PROVIDERS.clear()
