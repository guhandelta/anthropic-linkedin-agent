"""LinkedIn Groups automated publisher using Playwright.

Posts the approved LinkedIn draft and infographic sequentially to configured LinkedIn groups.
Uses a persistent browser profile directory so you log in once and stay authenticated.

Setup:
  python linkedin_groups.py --login   (opens browser to log in to LinkedIn once)
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import os
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent
PROFILE_DIR = ROOT / "browser_profile"
load_dotenv(ROOT / ".env")


def get_browser_context(playwright_instance, headless: bool = True):
    """Launch persistent browser context preserving LinkedIn session cookies."""
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
    """Opens a visible browser tab to log in to LinkedIn once."""
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
    """Verifies whether the current page session is logged in to LinkedIn."""
    page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(2000)
    # Check for feed navbar or user profile icons
    if page.locator("nav.global-nav, #global-nav, .feed-identity-module").count() > 0:
        return True
    if "login" in page.url or page.locator("input#username").count() > 0:
        return False
    return True


def post_to_single_group(page, group_url: str, text: str, image_path: Path | None = None) -> bool:
    """Publishes a post with optional image to a specific LinkedIn group."""
    print(f"Navigating to group: {group_url}")
    page.goto(group_url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(3000)

    # 1. Click "Start a post" button
    start_selectors = [
        "button:has-text('Start a post')",
        "button.share-box-feed-entry__trigger",
        "div[data-placeholder='Start a post']",
        "button[aria-label*='Start a post']",
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

    page.wait_for_timeout(2000)

    # 2. Upload image if provided
    if image_path and image_path.exists():
        media_selectors = [
            "input[type='file'][accept*='image']",
            "input[type='file']",
        ]
        uploaded = False
        for m_sel in media_selectors:
            f_input = page.locator(m_sel).first
            if f_input.count() > 0:
                f_input.set_input_files(str(image_path))
                uploaded = True
                break

        if not uploaded:
            # Try clicking the "Add media" icon to reveal file picker
            add_media_btn = page.locator("button[aria-label*='Add media'], button[aria-label*='media']").first
            if add_media_btn.is_visible():
                with page.expect_file_chooser() as fc_info:
                    add_media_btn.click()
                file_chooser = fc_info.value
                file_chooser.set_files(str(image_path))
                uploaded = True

        if uploaded:
            page.wait_for_timeout(2500)
            # Click "Next" on the media modal
            next_btn = page.locator("button:has-text('Next'), button.share-box-footer__primary-btn").first
            if next_btn.is_visible():
                next_btn.click()
                page.wait_for_timeout(1500)

    # 3. Enter post text into the editor textbox
    editor = page.locator("div[role='textbox'], div[contenteditable='true']").first
    editor.wait_for(state="visible", timeout=10000)
    editor.click()
    editor.fill(text)
    page.wait_for_timeout(1500)

    # 4. Click "Post" button
    post_btn = page.locator("button:has-text('Post'), button.share-actions__primary-action").first
    if post_btn.is_visible() and post_btn.is_enabled():
        post_btn.click()
        page.wait_for_timeout(5000)
        print(f"  ✅ Successfully posted to {group_url}")
        return True

    print(f"  ⚠️ 'Post' button not enabled on {group_url}")
    return False


def post_to_groups(
    groups: list[str],
    text: str,
    image_path: Path | None = None,
    delay_seconds: int = 12,
    headless: bool = True,
) -> dict:
    """Publishes the post sequentially across all listed LinkedIn groups."""
    results = {"success": [], "failed": []}
    if not groups:
        return results

    print(f"\n--- Starting LinkedIn Group Posting ({len(groups)} groups) ---")
    with sync_playwright() as p:
        context = get_browser_context(p, headless=headless)
        page = context.new_page()

        if not is_logged_in(page):
            msg = (
                "Not logged in to LinkedIn in browser_profile. "
                "Run: python linkedin_groups.py --login once to authenticate."
            )
            print(f"❌ {msg}")
            context.close()
            return {"error": msg, "success": [], "failed": groups}

        for idx, group_url in enumerate(groups, 1):
            print(f"[{idx}/{len(groups)}] Processing group: {group_url}")
            try:
                ok = post_to_single_group(page, group_url, text, image_path)
                if ok:
                    results["success"].append(group_url)
                else:
                    results["failed"].append(group_url)
            except Exception as e:
                print(f"  ❌ Error posting to {group_url}: {e}")
                results["failed"].append(group_url)

            # Wait delay between groups (except after the last one)
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
