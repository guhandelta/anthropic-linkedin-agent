"""Checks that editorial gates fail closed on repeats and unsupported facts."""

from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import agent
from quality import duplicate_topic, quote_in_page, verify_sources


def test_topic_dedup_catches_rephrasing_and_same_release_url():
    history = [{"topic": "Cancel stale fetches with AbortController",
                "technical_takeaway": "Call abort on the prior request before starting another search",
                "source_urls": ["https://developer.mozilla.org/en-US/docs/Web/API/AbortController"]}]
    assert duplicate_topic("Use AbortController to cancel stale fetches", history)
    assert duplicate_topic("A release with a different title", history,
                           "https://developer.mozilla.org/en-US/docs/Web/API/AbortController",
                           "update")
    assert not duplicate_topic("Observe element size using ResizeObserver", history,
                               "https://developer.mozilla.org/en-US/docs/Web/API/AbortController",
                               "evergreen")


def test_source_date_must_match_page_but_old_evergreen_content_is_valid():
    old = (date.today() - timedelta(days=900)).isoformat()
    page = {"url": "https://react.dev/reference", "text": "React documents how to use effects for external synchronization." * 3,
            "published_dates": [old]}
    source = {"url": "https://react.dev/reference", "claim": "Effects synchronize external systems",
              "published": old}
    assert verify_sources([source], {"react.dev"}, fetcher=lambda url, hosts: page) == [page]
    with pytest.raises(ValueError, match="not verified"):
        verify_sources([dict(source, published="2020-01-01")], {"react.dev"},
                       fetcher=lambda url, hosts: page)
    with pytest.raises(ValueError, match="future"):
        verify_sources([dict(source, published=(date.today() + timedelta(days=1)).isoformat())],
                       {"react.dev"}, fetcher=lambda url, hosts: page)


def test_unmatched_fact_check_quote_blocks_approval(monkeypatch):
    monkeypatch.setattr(agent, "verify_sources", lambda sources, hosts: [{
        "url": "https://react.dev/reference",
        "text": "Effects synchronize a component with an external system. " * 4,
        "published_dates": [],
    }])
    monkeypatch.setattr(agent, "call_json", lambda *args, **kwargs: {
        "approved": True, "claims_checked": 1,
        "evidence": [{"url": "https://react.dev/reference",
                      "quote": "This invented behavior is nowhere on the page"}],
        "issues": [],
    })
    result = agent.fact_check("Effects synchronize with external systems", [
        {"url": "https://react.dev/reference", "claim": "Effects synchronize external systems"}
    ])
    assert result["approved"] is False
    assert "No matching page quote" in result["issues"][0]
    assert quote_in_page("Effects synchronize a component", "Effects synchronize a component with an external system")


def test_custom_topic_cannot_bypass_failed_fact_check(monkeypatch):
    monkeypatch.setattr(agent, "editorial_review", MagicMock(return_value={
        "approved": True, "scores": {}, "issues": []}))
    monkeypatch.setattr(agent, "fact_check", MagicMock(return_value={
        "approved": False, "claims_checked": 1, "issues": ["Claim is unsupported"]}))
    monkeypatch.setitem(agent.CFG["review"], "passes", 1)
    passed, issues, _ = agent.review_all(
        "Evergreen idea", "Post", [{"url": "https://react.dev"}],
        Path("unused.png"), is_custom_topic=True)
    assert passed is False
    assert any("unsupported" in issue for issue in issues)


def test_source_checks_accept_evergreen_and_reject_future_updates():
    source = {"url": "https://developer.mozilla.org/en-US/docs/Web/API/AbortController",
              "published": None, "claim": "AbortController can cancel fetch requests"}
    assert agent.source_checks([source], set(), topic_kind="evergreen") == []
    future = dict(source, published=(date.today() + timedelta(days=1)).isoformat())
    assert any("future" in issue for issue in agent.source_checks([future], set(), topic_kind="update"))


def test_suggestion_fails_when_its_quote_is_not_on_the_page(monkeypatch):
    monkeypatch.setattr(agent, "call_json", lambda *args, **kwargs: {
        "approved": True, "evidence_quote": "A made-up API behavior that the page never states",
        "issues": []})
    item = {"topic": "Use the API", "angle": "A specific application",
            "technical_takeaway": "Check the browser support before removing a dependency",
            "source_claim": "The API supports cancellation"}
    page = {"text": "The official page explains how to cancel fetch requests with AbortController.",
            "published_dates": []}
    assert agent.verify_topic_suggestion(item, page) is False
