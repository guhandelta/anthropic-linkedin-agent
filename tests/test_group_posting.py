"""Group posting must recognise LinkedIn's sign-in wall and stop early with a clear reason."""
from __future__ import annotations

import os

import pytest
from playwright.sync_api import sync_playwright

import agent
import linkedin_groups as lg

SIGNED_IN_FEED = "<html><head><title>Feed | LinkedIn</title></head><body><nav class='global-nav'>nav</nav></body></html>"
GROUP_NO_BOX = "<html><head><title>Group | LinkedIn</title></head><body><nav class='global-nav'>nav</nav><p>About</p></body></html>"
AUTHWALL = ("<html><head><title>LinkedIn Login, Sign in | LinkedIn</title></head><body>"
            "<form id='join-form'></form><a href='https://www.linkedin.com/login'>Sign in</a></body></html>")


def _browser_with(pages: dict[str, str], redirects: dict[str, str] | None = None):
    """A get_browser_context replacement whose LinkedIn pages are served from `pages`."""
    redirects = redirects or {}

    def fake_context(p, headless=True):
        exe = os.environ.get("PLAYWRIGHT_CHROMIUM_PATH")
        browser = p.chromium.launch(**({"executable_path": exe} if exe else {}))
        ctx = browser.new_context()

        def handle(route):
            url = route.request.url
            for prefix, target in redirects.items():
                if url.split('?')[0] == prefix:  # LinkedIn's bounce to another page
                    return route.fulfill(status=200, content_type="text/html",
                                         body=f"<script>location.replace({target!r})</script>")
            for prefix, html in pages.items():
                if url.startswith(prefix):
                    return route.fulfill(status=200, content_type="text/html", body=html)
            return route.fulfill(status=404, body="not found")

        ctx.route("https://www.linkedin.com/**", handle)
        close = ctx.close
        ctx.close = lambda: (close(), browser.close())
        return ctx

    return fake_context


@pytest.fixture
def debug_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(lg, "DEBUG_DIR", tmp_path / "group_debug")
    return tmp_path / "group_debug"


def test_authwall_redirect_is_not_logged_in(monkeypatch, debug_dir):
    fake = _browser_with({"https://www.linkedin.com/authwall": AUTHWALL},
                         {"https://www.linkedin.com/feed/": "https://www.linkedin.com/authwall?trk=x"})
    with sync_playwright() as p:
        ctx = fake(p)
        page = ctx.new_page()
        assert lg.is_logged_in(page) is False
        assert "authwall" in lg.page_block_reason(page)
        ctx.close()


def test_sign_in_wall_without_redirect_is_not_logged_in(debug_dir):
    fake = _browser_with({"https://www.linkedin.com/feed/": AUTHWALL})
    with sync_playwright() as p:
        ctx = fake(p)
        page = ctx.new_page()
        assert lg.is_logged_in(page) is False
        ctx.close()


def test_signed_in_feed_is_logged_in(debug_dir):
    fake = _browser_with({"https://www.linkedin.com/feed/": SIGNED_IN_FEED})
    with sync_playwright() as p:
        ctx = fake(p)
        page = ctx.new_page()
        assert lg.is_logged_in(page) is True
        ctx.close()


def test_sign_in_wall_stops_before_any_group(monkeypatch, debug_dir):
    monkeypatch.setattr(lg, "get_browser_context", _browser_with(
        {"https://www.linkedin.com/authwall": AUTHWALL},
        {"https://www.linkedin.com/feed/": "https://www.linkedin.com/authwall"}))
    messages = []
    groups = [f"https://www.linkedin.com/groups/{n}/" for n in range(1, 9)]
    res = lg.post_to_groups(groups, "text", delay_seconds=0, progress_callback=messages.append)
    assert res["success"] == [] and res["failed"] == groups
    assert "LI_AT" in res["error"] and "authwall" in res["error"]
    assert (debug_dir / "login-check.png").exists()
    assert messages and "LI_AT" in messages[-1]


def test_missing_post_box_stops_after_two_groups_with_a_screenshot(monkeypatch, debug_dir):
    monkeypatch.setattr(lg, "get_browser_context", _browser_with({
        "https://www.linkedin.com/feed/": SIGNED_IN_FEED,
        "https://www.linkedin.com/groups/": GROUP_NO_BOX}))
    monkeypatch.setattr(lg, "post_to_single_group", _fast(lg.post_to_single_group))
    messages = []
    groups = [f"https://www.linkedin.com/groups/{n}/" for n in range(1, 9)]
    res = lg.post_to_groups(groups, "text", delay_seconds=0, progress_callback=messages.append)
    assert res["success"] == [] and res["failed"] == groups
    assert res["error"].startswith("Stopped after 2 of 8 groups")
    assert "title: Group | LinkedIn" in res["error"]
    assert (debug_dir / "group-1.png").exists() and (debug_dir / "group-2.png").exists()
    assert not (debug_dir / "group-3.png").exists()


def _fast(fn):
    """Skip the 3 s settle wait inside post_to_single_group."""
    def wrapper(page, *a, **kw):
        original = page.wait_for_timeout
        page.wait_for_timeout = lambda ms: original(min(ms, 50))
        return fn(page, *a, **kw)
    return wrapper


def test_duplicate_sources_are_cited_once():
    sources = [{"url": "https://v0.dev/docs/api/platform/packages/ai-tools", "claim": "A"},
               {"url": "https://v0.dev/docs/api/platform/packages/ai-tools", "claim": "B"},
               {"url": "https://v0.dev/docs/api/platform/packages/ai-tools", "claim": "A"},
               {"url": "https://react.dev/blog", "claim": "C"}]
    merged = agent.merge_duplicate_sources(sources)
    assert [s["url"] for s in merged] == ["https://v0.dev/docs/api/platform/packages/ai-tools",
                                          "https://react.dev/blog"]
    assert merged[0]["claim"] == "A; B"


def test_group_stop_reason_reaches_telegram(monkeypatch):
    from unittest.mock import MagicMock
    mock_li = MagicMock()
    mock_li.post_text.return_value = mock_li.post_with_image.return_value = "urn:li:share:1"
    monkeypatch.setattr(agent, "LinkedInClient", MagicMock(return_value=mock_li))
    monkeypatch.setattr(agent, "post_to_groups", MagicMock(return_value={
        "success": [], "failed": ["g1", "g2"], "error": "Stopped after 1 of 2 groups: LinkedIn showed its sign-in wall."}))
    monkeypatch.setenv("LINKEDIN_ACCESS_TOKEN", "fake")
    monkeypatch.setitem(agent.CFG, "linkedin", {"api_version": "202610", "target_groups": ["g1", "g2"],
                                                "group_delay_seconds": 0})
    tg = MagicMock()
    tg.send_progress_tracker.return_value = 7
    agent.publish_to_linkedin_and_groups(post="p", image_path=None, headline="h",
                                         sources=[{"url": "https://react.dev", "claim": "c"}],
                                         draft_id="d", message_id=1, tg=tg)
    final = tg.update_progress.call_args_list[-1].args[1]
    assert "0/2" in final and "sign-in wall" in final


GROUP_WITH_BOX = ("<html><head><title>Group | LinkedIn</title></head><body><nav class='global-nav'>nav</nav>"
                  "<button>Start a post</button></body></html>")


def test_check_groups_finds_the_post_box_without_clicking(monkeypatch, debug_dir):
    monkeypatch.setattr(lg, "get_browser_context", _browser_with({
        "https://www.linkedin.com/feed/": SIGNED_IN_FEED,
        "https://www.linkedin.com/groups/": GROUP_WITH_BOX}))
    res = lg.check_groups(["https://www.linkedin.com/groups/1/"], settle_ms=50)
    assert res["ok"] and res["post_box"] and "Nothing was posted" in res["detail"]
    assert (debug_dir / "check-group.png").exists()


def test_check_groups_reports_a_missing_post_box(monkeypatch, debug_dir):
    monkeypatch.setattr(lg, "get_browser_context", _browser_with({
        "https://www.linkedin.com/feed/": SIGNED_IN_FEED,
        "https://www.linkedin.com/groups/": GROUP_NO_BOX}))
    res = lg.check_groups(["https://www.linkedin.com/groups/1/"], settle_ms=50)
    assert res["logged_in"] and not res["ok"] and "no post box" in res["detail"]


def test_check_groups_reports_the_sign_in_wall(monkeypatch, debug_dir):
    monkeypatch.setattr(lg, "get_browser_context", _browser_with({"https://www.linkedin.com/feed/": AUTHWALL}))
    res = lg.check_groups(["https://www.linkedin.com/groups/1/"], settle_ms=50)
    assert not res["logged_in"] and "did not accept" in res["detail"]


def test_workflow_has_a_check_only_groups_mode():
    from pathlib import Path
    text = (Path(lg.__file__).parent / ".github/workflows/daily-post.yml").read_text()
    assert "- groups-check" in text and "python linkedin_groups.py --check-groups" in text


NEW_LAYOUT_FEED = "<html><head><title>Feed | LinkedIn</title></head><body><main>posts</main></body></html>"


def test_new_layout_feed_counts_as_signed_in(monkeypatch, debug_dir):
    """LinkedIn's newer feed (/feed/foryou/) has no global-nav markers but is signed in."""
    fake = _browser_with({"https://www.linkedin.com/feed/foryou/": NEW_LAYOUT_FEED},
                         {"https://www.linkedin.com/feed/": "https://www.linkedin.com/feed/foryou/"})
    with sync_playwright() as p:
        ctx = fake(p)
        page = ctx.new_page()
        assert lg.is_logged_in(page) is True
        ctx.close()


def test_missing_post_box_lists_the_page_controls(monkeypatch, debug_dir):
    monkeypatch.setattr(lg, "get_browser_context", _browser_with({
        "https://www.linkedin.com/feed/": SIGNED_IN_FEED,
        "https://www.linkedin.com/groups/": GROUP_NO_BOX.replace("<p>About</p>", "<button aria-label='Create post'>x</button>")}))
    res = lg.check_groups(["https://www.linkedin.com/groups/1/"], settle_ms=50)
    assert "button: Create post" in res["detail"]


def test_redirect_loop_means_the_cookie_was_rejected(debug_dir):
    """An ended li_at session makes Chromium give up with ERR_TOO_MANY_REDIRECTS on the feed."""
    from playwright.sync_api import Error

    with sync_playwright() as p:
        ctx = _browser_with({})(p)
        page = ctx.new_page()

        def looping_goto(url, **kw):
            raise Error(f"Page.goto: net::ERR_TOO_MANY_REDIRECTS at {url}")

        page.goto = looping_goto
        assert lg.is_logged_in(page) is False
        assert "rejected the LI_AT session" in lg.page_block_reason(page)
        ctx.close()
