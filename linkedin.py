"""Minimal LinkedIn client: Upload images, publish feed posts, and attach source comments.

Uses LinkedIn's modern versioned REST API (Images API + Posts API).
Requires an OAuth 2.0 access token with scopes:
- openid: To identify the user via userinfo endpoint.
- profile: To retrieve personal profile details.
- w_member_social: To author and publish posts/comments on the user's personal feed.
"""

from pathlib import Path
from urllib.parse import quote
import re
import requests


class LinkedInClient:
    """Client for publishing media and text updates to LinkedIn's Member Posts API."""
    
    def __init__(self, token: str, api_version: str):
        # Configure headers according to LinkedIn's Restli 2.0 specifications
        self.h = {
            "Authorization": f"Bearer {token}",
            "LinkedIn-Version": api_version,
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
        }
        # Fetch authenticated person's URN (e.g., 'urn:li:person:abcdef123')
        self.author = self._me()

    def _me(self) -> str:
        """Fetch the OpenID subject identifier for the authenticated user."""
        r = requests.get(
            "https://api.linkedin.com/v2/userinfo",
            headers={"Authorization": self.h["Authorization"]},
            timeout=30
        )
        r.raise_for_status()
        return f"urn:li:person:{r.json()['sub']}"

    def upload_image(self, path: Path) -> str:
        """Two-step media upload required by LinkedIn Images API:
        
        Step 1: Initialize upload to request a pre-signed binary upload URL.
        Step 2: PUT the raw binary image data (PNG or GIF) to the designated upload URL.
        Returns the registered LinkedIn image URN (e.g. 'urn:li:image:D5622AQ...').
        """
        # Step 1: Initialize upload ticket
        r = requests.post(
            "https://api.linkedin.com/rest/images?action=initializeUpload",
            headers=self.h,
            json={"initializeUploadRequest": {"owner": self.author}},
            timeout=30
        )
        r.raise_for_status()
        v = r.json()["value"]
        
        # Step 2: Upload raw image binary to the signed storage URL
        put = requests.put(
            v["uploadUrl"],
            data=path.read_bytes(),
            headers={"Authorization": self.h["Authorization"]},
            timeout=60
        )
        put.raise_for_status()
        return v["image"]  # urn:li:image:...

    @staticmethod
    def _escape(text: str) -> str:
        """Escape reserved punctuation characters required by LinkedIn's 'little text' syntax.
        
        LinkedIn's Posts API reserves symbols like {}, @, [], (), <>, #, *, _, and ~.
        We escape them with a leading backslash to prevent formatting parse errors.
        """
        for ch in "\\|{}@[]()<>#*_~":
            text = text.replace(ch, "\\" + ch)
        return text

    def comment(self, post_urn: str, text: str) -> None:
        """Add a comment under a live LinkedIn post (used to list clean clickable references)."""
        r = requests.post(
            f"https://api.linkedin.com/rest/socialActions/{quote(post_urn, safe='')}/comments",
            headers=self.h,
            json={"actor": self.author, "object": post_urn, "message": {"text": text[:1200]}},
            timeout=30
        )
        if r.status_code >= 400:
            raise RuntimeError(f"Comment failed {r.status_code}: {r.text}")

    def post_text(self, text: str) -> str:
        """Publish a plain-text post to the personal feed."""
        # Un-escape leading hashtags (#word) so LinkedIn renders them as clickable tags
        body = re.sub(r"\\#(\w)", r"#\1", self._escape(text))
        payload = {
            "author": self.author,
            "commentary": body,
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": []
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }
        r = requests.post(
            "https://api.linkedin.com/rest/posts",
            headers=self.h,
            json=payload,
            timeout=30
        )
        if r.status_code >= 400:
            raise RuntimeError(f"LinkedIn post failed {r.status_code}: {r.text}")
        return r.headers.get("x-restli-id", "")

    def post_with_image(self, text: str, image_path: Path, alt_text: str = "") -> str:
        """Upload an image/GIF and publish a media post to the personal feed."""
        image_urn = self.upload_image(image_path)
        # Preserve clickable hashtags while escaping other reserved symbols
        body = re.sub(r"\\#(\w)", r"#\1", self._escape(text))
        payload = {
            "author": self.author,
            "commentary": body,
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": []
            },
            "content": {"media": {"id": image_urn, "altText": alt_text[:300]}},
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }
        r = requests.post(
            "https://api.linkedin.com/rest/posts",
            headers=self.h,
            json=payload,
            timeout=30
        )
        if r.status_code >= 400:
            raise RuntimeError(f"LinkedIn post failed {r.status_code}: {r.text}")
        return r.headers.get("x-restli-id", "")
