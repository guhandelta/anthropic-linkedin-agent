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


def is_logged_in(page) -> bool:
    """Verify whether the browser currently holds an authenticated LinkedIn session.
    
    Checks for the presence of global navigation modules or redirects to the login screen.
    """
    page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(2000)
    # Check for feed navbar or identity widget
    if page.locator("nav.global-nav, #global-nav, .feed-identity-module").count() > 0:
        return True
    if "login" in page.url or page.locator("input#username").count() > 0:
        return False
    return True


def post_to_single_group(page, group_url: str, text: str, image_path: Path | None = None) -> bool:
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
    start_selectors = [
        "button:has-text('Start a post')",
        "button:has-text('Start a public post')",
        "button:has-text('Start a')",
        "div[data-placeholder*='Start a']",
        "button.share-box-feed-entry__trigger",
        "button[aria-label*='Start a']",
    ]
    started = False
    for sel in start_selectors:
        loc = page.locator(sel).first
        if loc.is_visible():
            loc.click()
            started = True
            break

    if not started:
        print(f"  ⚠️ Could not find 'Start a post' button on {group_url} (are you a member of this group?)")
        return False

    page.wait_for_timeout(2500)

    # 2. Upload image or GIF attachment if provided
    if image_path and image_path.exists():
        media_btn = page.locator("button[aria-label*='Add media' i], button[aria-label*='photo' i]").first
        if media_btn.is_visible():
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
                print(f"  ⚠️ Warning: Image attachment failed: {e}")

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
    if not groups:
        return results

    print(f"\n--- Starting LinkedIn Group Posting ({len(groups)} groups) ---")
    with sync_playwright() as p:
        context = get_browser_context(p, headless=headless)
        page = context.new_page()

        # Check authentication state before starting loop
        if not is_logged_in(page):
            msg = (
                "Not logged in to LinkedIn in browser_profile. "
                "Run: python linkedin_groups.py --login once to authenticate."
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
            try:
                ok = post_to_single_group(page, group_url, text, image_path)
                if ok:
                    results["success"].append(group_url)
                else:
                    results["failed"].append(group_url)
            except Exception as e:
                print(f"  ❌ Error posting to {group_url}: {e}")
                results["failed"].append(group_url)

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
    else:
        parser.print_help()
