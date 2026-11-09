import pytest

import agent


@pytest.fixture(autouse=True)
def no_live_gemini(monkeypatch):
    """Tests must never call the real Gemini API; tests that need it install their own mock."""
    monkeypatch.setattr(agent, "gemini_client", None)


@pytest.fixture(autouse=True)
def poster_style_in_tmp(monkeypatch, tmp_path):
    """The remembered poster style lives in a temporary folder, never in the real state folder."""
    monkeypatch.setattr(agent, "poster_style_path", lambda: tmp_path / "state" / "poster_style.json")


@pytest.fixture(autouse=True)
def reset_lower_models():
    """A lower model chosen in one test must not carry over to the next."""
    agent.MODEL_OVERRIDE.clear()
    yield
    agent.MODEL_OVERRIDE.clear()
