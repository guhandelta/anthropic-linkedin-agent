"""LinkedIn Groups automated publisher using Playwright headless browser automation.

Why Playwright for LinkedIn Groups?
The official LinkedIn Community Management & Share APIs require special enterprise partner
permissions to publish into LinkedIn Groups. This module provides a reliable browser automation
alternative:
1. Uses a persistent browser profile directory (`browser_profile/`) or a session cookie (`LI_AT`),
   meaning you log in once interactively and subsequent automated runs remain authenticated.
2. Navigates sequentially to each target group URL configured in `config.yaml`.
3. Handles image/GIF media file dialogs, inputs the post copy into the contenteditable composer,
   and clicks the primary submit button.
4. Enforces configurable inter-group delays (default 12s) to emulate natural user posting behavior
   and avoid rate-limiting triggers.
5. Provides progress callbacks to keep the Telegram user updated during live distribution.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

# Project roots and persistent browser cache location
ROOT = Path(__file__).parent
PROFILE_DIR = ROOT / "browser_profile"
load_dotenv(ROOT / ".env")


def get_browser_context(playwright_instance, headless: bool = True):
    """Launch a Chromium persistent context that preserves login cookies across runs.
    
    - Disables automation blink flags to avoid bot detection interstitials.
    - If LINKEDIN_COOKIE or LI_AT is defined in the environment, injects it directly into
      the browser cookies for headless environments like GitHub Actions or servers.
    """
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    ctx = playwright_instance.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=headless,
        viewport={"width": 1280, "height": 900},
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
        ],
    )
    
    # Inject li_at session cookie if provided via environment / secrets
    li_at = os.getenv("LINKEDIN_COOKIE") or os.getenv("LI_AT")
    if li_at:
        ctx.add_cookies([{
            "name": "li_at",
            "value": li_at.strip(),
            "domain": ".www.linkedin.com",
            "path": "/",
            "httpOnly": True,
            "secure": True,
            "sameSite": "None",
        }, {
            "name": "li_at",
            "value": li_at.strip(),
            "domain": ".linkedin.com",
            "path": "/",
            "httpOnly": True,
            "secure": True,
            "sameSite": "None",
        }])
    return ctx


def login_interactive():
    """Open a visible Chromium window allowing the user to complete one-time LinkedIn authentication."""
    print(f"Opening browser for one-time LinkedIn login. Profile saved to: {PROFILE_DIR}")
    with sync_playwright() as p:
        context = get_browser_context(p, headless=False)
        page = context.new_page()
        page.goto("https://www.linkedin.com/login")
        print("\nPlease log in to LinkedIn in the opened browser window.")
        print("Once you see your LinkedIn feed / home page, return here and press Enter...")
        try:
            input("\nPress [ENTER] here after logging in successfully: ")
        except (KeyboardInterrupt, EOFError):
            pass
        context.close()
    print("Browser profile updated! You are now logged in for automated group posts.")


BLOCKED_URL_PARTS = ("/login", "/authwall", "/checkpoint", "/uas/", "/signup", "/m/login")
DEBUG_DIR = ROOT / "output" / "group_debug"
STOP_AFTER_NO_POST_BOX = 2


def page_block_reason(page) -> str:
    """Why this page is LinkedIn's sign-in wall or security check, or "" when it looks normal."""
    url = page.url or ""
    if any(part in url for part in BLOCKED_URL_PARTS):
        return f"LinkedIn sent the browser to {url.split('?')[0]}"
    if page.locator("input#username, input[name='session_key']").count() > 0:
        return "LinkedIn showed its sign-in form"
    if page.locator("form#join-form, a[data-tracking-control-name*='auth_wall'], "
                    "a[href*='/login']:has-text('Sign in')").count() > 0 \
            and page.locator("nav.global-nav, #global-nav").count() == 0:
        return "LinkedIn showed its sign-in wall"
    if page.locator("#captcha-internal, iframe[src*='captcha'], form[action*='checkpoint']").count() > 0:
        return "LinkedIn showed a security check"
    return ""


def save_page_debug(page, label: str) -> str:
    """Save a screenshot and the address and title of what LinkedIn showed. Returns a summary."""
    try:
        title = page.title()
    except Exception:  # noqa: BLE001 - the summary is best effort
        title = ""
    summary = f"{page.url.split('?')[0]} (title: {title or 'none'})"
    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(DEBUG_DIR / f"{label}.png"), full_page=False)
        (DEBUG_DIR / f"{label}.txt").write_text(f"url: {page.url}\ntitle: {title}\n")
    except Exception as e:  # noqa: BLE001
        print(f"  (could not save a screenshot: {e})")
    return summary


def is_logged_in(page) -> bool:
    """Whether the browser holds a LinkedIn session that LinkedIn accepts.

    The feed must show LinkedIn's own navigation. A sign-in wall, the login form or a security
    check all count as not logged in (they used to pass, so group posting failed later instead).
    """
    page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(2000)
    if page_block_reason(page):
        return False
    if page.locator("nav.global-nav, #global-nav, .feed-identity-module, "
                    "header.global-nav, [data-test-global-nav]").count() > 0:
        return True
    # LinkedIn's newer layout has none of those markers; staying on /feed (for example
    # /feed/foryou/) without a sign-in wall means LinkedIn accepted the session.
    return "linkedin.com/feed" in (page.url or "")


def describe_controls(page, limit: int = 40) -> str:
    """The visible buttons and editable boxes on the page, so a missing post box can be diagnosed."""
    try:
        items = page.evaluate("""(limit) => {
            const out = [];
            for (const el of document.querySelectorAll('button, [role=button], [contenteditable=true], [data-placeholder]')) {
                const r = el.getBoundingClientRect();
                if (!r.width || !r.height) continue;
                const label = (el.getAttribute('aria-label') || el.getAttribute('data-placeholder') ||
                               el.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 60);
                if (label) out.push(el.tagName.toLowerCase() + ': ' + label);
                if (out.length >= limit) break;
            }
            return out;
        }""", limit)
    except Exception as e:  # noqa: BLE001 - diagnostics only
        return f"(could not list controls: {e})"
    return "; ".join(items) or "(no visible controls)"


START_SELECTORS = [
    "button:has-text('Start a post')",
    "button:has-text('Start a public post')",
    "button:has-text('Start a')",
    "div[data-placeholder*='Start a']",
    "button.share-box-feed-entry__trigger",
    "button[aria-label*='Start a']",
]


def find_start_button(page):
    """The group's visible 'Start a post' control, or None when the page has no post box."""
    for sel in START_SELECTORS:
        loc = page.locator(sel).first
        if loc.is_visible():
            return loc
    return None


def check_groups(groups: list[str], headless: bool = True, settle_ms: int = 3000) -> dict:
    """Check, without posting anything, that LinkedIn accepts the session and shows a post box.

    Opens the feed and the first group only. Screenshots go to output/group_debug.
    Returns {"ok": bool, "logged_in": bool, "post_box": bool, "detail": str}.
    """
    result = {"ok": False, "logged_in": False, "post_box": False, "detail": ""}
    with sync_playwright() as p:
        context = get_browser_context(p, headless=headless)
        page = context.new_page()
        try:
            if not is_logged_in(page):
                seen = save_page_debug(page, "check-login")
                reason = page_block_reason(page) or "the feed did not load as a signed-in page"
                result["detail"] = f"LinkedIn did not accept the session: {reason}. Page: {seen}"
                return result
            result["logged_in"] = True
            save_page_debug(page, "check-feed")
            if not groups:
                result.update(ok=True, detail="Signed in. No target groups are configured.")
                return result
            page.goto(groups[0], wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(settle_ms)
            seen = save_page_debug(page, "check-group")
            if find_start_button(page) is not None:
                result.update(ok=True, post_box=True,
                              detail=f"Signed in, and {groups[0]} shows the post box. Nothing was posted.")
            else:
                reason = page_block_reason(page) or "no post box on the group page"
                result["detail"] = (f"Signed in, but {groups[0]}: {reason}. Page: {seen}. "
                                    f"Controls on the page: {describe_controls(page)}")
            return result
        finally:
            context.close()


def post_to_single_group(page, group_url: str, text: str, image_path: Path | None = None,
                         diagnostics: dict | None = None) -> bool:
    """Publish an update (with optional image/GIF attachment) to a single LinkedIn group page.
    
    Workflow steps:
    1. Navigate to target group page.
    2. Click 'Start a post' trigger button.
    3. If an image/GIF is provided, open the file picker and confirm upload preview.
    4. Fill post commentary text into the rich contenteditable editor.
    5. Click the primary 'Post' button and confirm the modal closes.
    """
    print(f"Navigating to group: {group_url}")
    page.goto(group_url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(3000)

    # 1. Locate and click the 'Start a post' button
    start_button = find_start_button(page)
    started = start_button is not None
    if started:
        start_button.click()

    if not started:
        label = "group-" + group_url.rstrip("/").rsplit("/", 1)[-1]
        reason = page_block_reason(page)
        seen = save_page_debug(page, label)
        print(f"  ⚠️ Could not find 'Start a post' button on {group_url}: {reason or 'no post box'}; page: {seen}")
        print(f"  Controls on the page: {describe_controls(page)}")
        if diagnostics is not None:
            diagnostics.update(no_post_box=True, blocked=reason, page=seen)
        return False

    page.wait_for_timeout(2500)

    # 2. Upload image or GIF attachment if provided
    if image_path and image_path.exists():
        media_btn = page.locator("button[aria-label*='Add media' i], button[aria-label*='photo' i]").first
        if not media_btn.is_visible():
            print(f"  ⚠️ Media button unavailable for {group_url}; skipping text-only post")
            return False
        try:
            # Intercept file chooser dialog
            with page.expect_file_chooser(timeout=7000) as fc_info:
                media_btn.click()
            file_chooser = fc_info.value
            file_chooser.set_files(str(image_path.resolve()))
            page.wait_for_timeout(3000)
            # Confirm preview modal by clicking 'Next'
            next_btn = page.locator("button:has-text('Next'), button.share-box-footer__primary-btn").first
            if next_btn.is_visible():
                next_btn.click()
                page.wait_for_timeout(2000)
        except Exception as e:
            print(f"  ⚠️ Media attachment failed on {group_url}: {e}; skipping text-only post")
            return False

    # 3. Enter post text into the contenteditable composer
    editor = page.locator("div[role='textbox'], div[contenteditable='true']").first
    editor.wait_for(state="visible", timeout=10000)
    editor.click()
    editor.fill(text)
    page.wait_for_timeout(1500)

    # 4. Click the primary 'Post' button (targeting the primary action button to avoid audience dropdowns)
    submit_btn = page.locator("button.share-actions__primary-action").first
    if submit_btn.is_visible() and submit_btn.is_enabled():
        submit_btn.click()
        try:
            # Wait for post dialog to disappear, indicating successful submission
            submit_btn.wait_for(state="hidden", timeout=15000)
            page.wait_for_timeout(3000)
            print(f"  ✅ Successfully posted to {group_url}")
            return True
        except Exception:
            if submit_btn.is_visible():
                print(f"  ⚠️ Submission dialog stayed open on {group_url}")
                return False
            print(f"  ✅ Successfully posted to {group_url}")
            return True

    print(f"  ⚠️ 'Post' submit button was not enabled on {group_url}")
    return False


def post_to_groups(
    groups: list[str],
    text: str,
    image_path: Path | None = None,
    delay_seconds: int = 12,
    headless: bool = True,
    progress_callback: callable | None = None,
) -> dict:
    """Iterate through target LinkedIn groups sequentially with delays between each.
    
    Returns a dictionary of:
    - 'success': list of group URLs where publication succeeded
    - 'failed': list of group URLs that encountered errors
    """
    results = {"success": [], "failed": []}
    no_box_streak = 0
    if not groups:
        return results

    print(f"\n--- Starting LinkedIn Group Posting ({len(groups)} groups) ---")
    with sync_playwright() as p:
        context = get_browser_context(p, headless=headless)
        page = context.new_page()

        # Check authentication state before starting loop
        if not is_logged_in(page):
            seen = save_page_debug(page, "login-check")
            reason = page_block_reason(page) or "LinkedIn's feed did not load as a signed-in page"
            msg = (
                f"LinkedIn did not accept the group-posting session: {reason}. Page: {seen}. "
                "On GitHub Actions, replace the LI_AT secret with a fresh cookie; "
                "on the Mac, run: python linkedin_groups.py --login"
            )
            print(f"❌ {msg}")
            if progress_callback:
                progress_callback(f"⚠️ {msg}")
            context.close()
            return {"error": msg, "success": [], "failed": groups}

        # Sequentially post to each target group
        for idx, group_url in enumerate(groups, 1):
            status_msg = f"📢 Publishing to group [{idx}/{len(groups)}]: {group_url}..."
            print(f"[{idx}/{len(groups)}] Processing group: {group_url}")
            if progress_callback:
                progress_callback(status_msg)
            diag: dict = {}
            try:
                ok = post_to_single_group(page, group_url, text, image_path, diagnostics=diag)
                if ok:
                    results["success"].append(group_url)
                else:
                    results["failed"].append(group_url)
            except Exception as e:
                print(f"  ❌ Error posting to {group_url}: {e}")
                results["failed"].append(group_url)

            # A sign-in wall or security check, or no post box on the first two groups, means the
            # session itself is the problem: stop instead of trying every group the same way.
            no_box_streak = no_box_streak + 1 if diag.get("no_post_box") else 0
            if not results["success"] and (diag.get("blocked") or no_box_streak >= STOP_AFTER_NO_POST_BOX):
                skipped = groups[idx:]
                results["failed"].extend(skipped)
                results["error"] = (
                    f"Stopped after {idx} of {len(groups)} groups: "
                    f"{diag.get('blocked') or 'no post box on the group pages'}. "
                    f"LinkedIn showed: {diag.get('page', 'unknown page')}. "
                    "A screenshot is in the run's 'output' download (group_debug)."
                )
                print(f"❌ {results['error']}")
                if progress_callback:
                    progress_callback(f"⚠️ {results['error']}")
                break

            # Wait human-like delay between group posts (except after the final group)
            if idx < len(groups) and delay_seconds > 0:
                print(f"  Waiting {delay_seconds}s before next group...")
                time.sleep(delay_seconds)

        context.close()

    print(f"--- Group Posting Complete: {len(results['success'])} posted, {len(results['failed'])} failed ---\n")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LinkedIn Group Automated Publisher")
    parser.add_argument("--login", action="store_true", help="Launch visible browser to log in to LinkedIn")
    parser.add_argument("--test", action="store_true", help="Verify browser login status")
    parser.add_argument("--check-groups", action="store_true",
                        help="Check the session and the first target group's post box without posting")
    args = parser.parse_args()

    if args.login:
        login_interactive()
    elif args.test:
        with sync_playwright() as p:
            ctx = get_browser_context(p, headless=True)
            pg = ctx.new_page()
            logged_in = is_logged_in(pg)
            print(f"Login status: {'✅ Logged in' if logged_in else '❌ Not logged in'}")
            ctx.close()
    elif args.check_groups:
        import yaml
        config = yaml.safe_load((ROOT / "config.yaml").read_text()) or {}
        outcome = check_groups((config.get("linkedin") or {}).get("target_groups") or [])
        print(("✅ " if outcome["ok"] else "❌ ") + outcome["detail"])
        sys.exit(0 if outcome["ok"] else 1)
    else:
        parser.print_help()
