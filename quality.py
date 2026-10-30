"""Deterministic topic and source checks shared by suggestions and daily drafts.

This module enforces journalistic and technical integrity without relying solely on LLMs:
1. Canonicalizes URLs to prevent duplicates with trailing slashes or varying subdomains.
2. Extracts meaningful tokens from topic headlines and technical takeaways to prevent
   repetitive topics using token set overlaps and sequence similarity ratios.
3. Defends against SSRF (Server-Side Request Forgery) by ensuring source hostnames resolve
   strictly to public IP addresses before making HTTP requests.
4. Parses live HTML pages safely using Python's standard HTMLParser to extract readable
   copy, detect publication dates in metadata tags (<meta>, <time>), and verify claims.
"""

from __future__ import annotations

import ipaddress
import json
import re
import socket
from datetime import date
from difflib import SequenceMatcher
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

import requests

# Common English stopwords ignored when calculating topic similarity tokens
STOP_WORDS = {
    "a", "an", "and", "as", "at", "by", "for", "from", "how", "in", "into",
    "is", "of", "on", "or", "the", "to", "using", "with", "why", "your",
}

# HTML meta tag names and properties typically used by publication blogs to denote article date
DATE_KEYS = {"article:published_time", "datepublished", "pubdate", "dc.date", "date"}

# Max bytes to stream per web page to protect memory against huge downloads or zip bombs
MAX_PAGE_BYTES = 1_000_000


def canonical_url(url: str) -> str:
    """Normalize a web URL to ensure consistent comparison across the system.
    
    - Enforces http or https schemes.
    - Strips 'www.' prefixes and converts hostname to lowercase.
    - Trims trailing slashes and discards fragments (#...) while preserving queries (?foo=bar).
    """
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Source must be an HTTP or HTTPS page")
    host = parsed.hostname.lower().removeprefix("www.")
    return urlunparse((parsed.scheme.lower(), host, parsed.path.rstrip("/") or "/",
                       "", parsed.query, ""))


def topic_tokens(value: str) -> set[str]:
    """Extract informative alphanumeric keywords from a topic headline or takeaway.
    
    Filters out single-character tokens and common stop words so comparison focuses
    on substantive technical concepts (e.g. 'react', 'compiler', 'memoization').
    """
    return {word for word in re.findall(r"[a-z0-9]+", value.casefold())
            if len(word) > 1 and word not in STOP_WORDS}


def duplicate_topic(topic: str, history: list[dict], source_url: str = "",
                    kind: str = "evergreen", takeaway: str = "") -> bool:
    """Determine whether a candidate topic repeats a previously suggested or published post.
    
    Checks three layers of deduplication:
    1. Exact token match or high Jaccard token overlap (>= 60% with >= 3 shared words).
    2. String character similarity ratio (SequenceMatcher >= 0.84).
    3. Technical takeaway similarity (shared actionable tradeoff or engineering insight).
    4. Canonical source URL reuse for non-evergreen (news/release) updates.
    """
    tokens = topic_tokens(topic)
    if len(tokens) < 2:
        return True  # Reject vague 1-word topics immediately
    source = canonical_url(source_url) if source_url else ""
    for entry in history:
        earlier = str(entry.get("topic") or entry.get("headline") or "")
        old_tokens = topic_tokens(earlier)
        # Check token equality or strong intersection
        if tokens == old_tokens or (
            len(tokens & old_tokens) >= 3
            and len(tokens & old_tokens) / len(tokens | old_tokens) >= 0.6
        ) or SequenceMatcher(None, topic.casefold(), earlier.casefold()).ratio() >= 0.84:
            return True
        
        # Check technical takeaway similarity to avoid covering identical architectural advice
        earlier_takeaway = str(entry.get("technical_takeaway") or "")
        if takeaway and earlier_takeaway:
            new_detail, old_detail = topic_tokens(takeaway), topic_tokens(earlier_takeaway)
            if (len(new_detail & old_detail) >= 4
                    and len(new_detail & old_detail) / len(new_detail | old_detail) >= 0.65):
                return True
        
        # News and releases cannot reuse the exact same source URL
        if source and kind != "evergreen":
            for old_url in entry.get("source_urls", []):
                try:
                    if canonical_url(old_url) == source:
                        return True
                except ValueError:
                    continue
    return False


def load_history(path: Path, posted: list[dict]) -> list[dict]:
    """Load historical topics from disk and merge them with logged LinkedIn posts.
    
    Provides the full retrospective context needed to prevent duplicate suggestions.
    """
    saved = json.loads(path.read_text()) if path.exists() else []
    if not isinstance(saved, list):
        raise ValueError("Topic history must be a list")
    for post in posted:
        saved.append({"topic": post.get("headline", ""),
                      "source_urls": [s.get("url", "") for s in post.get("sources", [])]})
    return saved


def remember_topic(path: Path, topic: str, source_urls: list[str], kind: str,
                    technical_takeaway: str = "", status: str = "drafted",
                    source: str = "") -> None:
    """Safely append a topic to topic_history.json using atomic file replacement.
    
    Writing to a temporary file first prevents data corruption in the event of an abrupt process termination.
    """
    saved = json.loads(path.read_text()) if path.exists() else []
    if not isinstance(saved, list):
        raise ValueError("Topic history must be a list")
    saved.append({"topic": topic, "source_urls": source_urls,
                  "technical_takeaway": technical_takeaway,
                  "kind": kind, "status": status, "source": source,
                  "recorded_at": date.today().isoformat()})
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(saved, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


class _PageText(HTMLParser):
    """HTML parser to extract visible text copy and discover article publication dates.
    
    Skips non-visible tags (<script>, <style>, <noscript>, <svg>) and captures dates
    from <meta> tags and <time datetime="..."> attributes.
    """
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.parts: list[str] = []
        self.dates: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = dict(attrs)
        # Suppress content inside hidden elements
        if tag in {"script", "style", "noscript", "svg"}:
            self.hidden += 1
        # Extract article publishing timestamps from metadata tags
        if tag == "meta":
            key = (data.get("property") or data.get("name") or "").lower()
            value = data.get("content") or ""
            if key in DATE_KEYS and re.match(r"\d{4}-\d{2}-\d{2}", value):
                self.dates.add(value[:10])
        # Extract date from semantic HTML5 <time> tags
        if tag == "time" and re.match(r"\d{4}-\d{2}-\d{2}", data.get("datetime") or ""):
            self.dates.add(data["datetime"][:10])

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden and data.strip():
            self.parts.append(data)


def _public_allowed_url(url: str, allowed_hosts: set[str]) -> None:
    """Validate that a URL is a public HTTPS host from the approved domains list.
    
    Protects against SSRF (Server-Side Request Forgery) attacks by verifying:
    - Scheme is strictly HTTPS.
    - No user/password credentials in URL.
    - Hostname matches the approved domains allowlist.
    - Resolved DNS IP address is a public, globally routable address (rejects 127.0.0.1, 10.x, etc.).
    """
    parsed = urlparse(url)
    host = parsed.hostname
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        raise ValueError("Source page must be a public HTTPS URL")
    host = host.lower().removeprefix("www.")
    if not any(host == allowed or host.endswith("." + allowed) for allowed in allowed_hosts):
        raise ValueError(f"Source domain is not approved: {host}")
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as error:
        raise ValueError(f"Source host could not be resolved: {host}") from error
    # Verify every resolved IP is globally routable (not private/loopback/link-local)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError(f"Source host is not public: {host}")


def fetch_source_page(url: str, allowed_hosts: set[str]) -> dict:
    """Read a bounded, approved web page and capture its visible copy and publication dates.
    
    - Handles safe HTTP redirects (up to 4 hops).
    - Caps stream at MAX_PAGE_BYTES (1MB).
    - Extracts visible copy and detected publication dates.
    """
    current = url
    for _ in range(4):
        _public_allowed_url(current, allowed_hosts)
        with requests.get(current, timeout=20, allow_redirects=False, stream=True,
                          headers={"User-Agent": "LinkedInEditorialReview/1.0"}) as response:
            if response.status_code in {301, 302, 303, 307, 308}:
                current = urljoin(current, response.headers.get("Location", ""))
                continue
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "").lower()
            if not ("text/html" in content_type or "text/plain" in content_type):
                raise ValueError(f"Source is not a readable web page: {url}")
            chunks = []
            size = 0
            for chunk in response.iter_content(chunk_size=65536):
                size += len(chunk)
                if size > MAX_PAGE_BYTES:
                    raise ValueError(f"Source page is too large: {url}")
                chunks.append(chunk)
            page = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
        parser = _PageText()
        parser.feed(page)
        copy = " ".join(" ".join(parser.parts).split())
        if len(copy) < 100:
            raise ValueError(f"Source page has too little readable text: {url}")
        url_match = re.search(r"/(20\d\d)[/-](0[1-9]|1[0-2])[/-](0[1-9]|[12]\d|3[01])", current)
        if url_match:
            parser.dates.add(f"{url_match.group(1)}-{url_match.group(2)}-{url_match.group(3)}")
        for d in re.findall(r"\b(20\d\d-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01]))\b", page):
            parser.dates.add(d)
        return {"url": canonical_url(current), "text": copy, "published_dates": sorted(parser.dates)}
    raise ValueError(f"Source redirected too many times: {url}")


def verify_sources(sources: list[dict], allowed_hosts: set[str],
                   fetcher=None) -> list[dict]:
    """Verify cited sources against real live web pages.
    
    Ensures that:
    1. Each source has a substantive factual claim (at least 12 characters).
    2. The source page can be fetched and parsed.
    3. The publication date is not in the future and matches metadata detected on the page.
    """
    if not sources:
        raise ValueError("At least one source is required")
    fetcher = fetcher or fetch_source_page
    pages = []
    for source in sources:
        url = source.get("url", "")
        claim = source.get("claim", "")
        if not isinstance(claim, str) or len(claim.strip()) < 12:
            raise ValueError(f"Source needs a specific claim: {url}")
        page = fetcher(url, allowed_hosts)
        claimed_date = source.get("published")
        if claimed_date:
            try:
                parsed = date.fromisoformat(claimed_date)
            except (TypeError, ValueError) as error:
                raise ValueError(f"Invalid publication date for {url}") from error
            if parsed > date.today():
                raise ValueError(f"Publication date is in the future: {url}")
            if claimed_date not in page["published_dates"]:
                raise ValueError(f"Publication date is not verified on source page: {url}")
        pages.append(page)
    return pages


def quote_in_page(quote: str, page_text: str) -> bool:
    """Verify whether a cited quote or factual excerpt exists within the live page text.
    
    Normalizes whitespace and case to ensure reliable matching across line breaks.
    Supports multi-sentence quotes where individual sentences match the source page.
    """
    clean_quote = " ".join(quote.casefold().split())
    clean_page = " ".join(page_text.casefold().split())
    if len(clean_quote) < 20:
        return False
    if clean_quote in clean_page:
        return True

    # If the LLM combined two non-contiguous sentences, check if any individual sentence matches
    sentences = [s.strip() for s in re.split(r"[.!?\n]", clean_quote) if len(s.strip()) >= 25]
    if sentences and any(s in clean_page for s in sentences):
        return True

    # Also try matching after stripping non-alphanumeric punctuation
    norm_quote = re.sub(r"[^\w\s]", "", clean_quote)
    norm_page = re.sub(r"[^\w\s]", "", clean_page)
    if len(norm_quote) >= 20 and norm_quote in norm_page:
        return True

    return False
