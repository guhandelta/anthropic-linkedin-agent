import pytest

import agent


@pytest.fixture(autouse=True)
def no_live_gemini(monkeypatch):
    """Tests must never call the real Gemini API; tests that need it install their own mock."""
    monkeypatch.setattr(agent, "gemini_client", None)
