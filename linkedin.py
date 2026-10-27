"""Minimal LinkedIn client: upload an image and publish a post on your own feed.

Uses LinkedIn's versioned REST API (Images API + Posts API).
Requires an access token with scopes: openid profile w_member_social
"""
from pathlib import Path

import requests


class LinkedInClient:
    def __init__(self, token: str, api_version: str):
        self.h = {
            "Authorization": f"Bearer {token}",
            "LinkedIn-Version": api_version,
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
        }
        self.author = self._me()

    def _me(self) -> str:
        r = requests.get("https://api.linkedin.com/v2/userinfo",
                         headers={"Authorization": self.h["Authorization"]}, timeout=30)
        r.raise_for_status()
        return f"urn:li:person:{r.json()['sub']}"

    def upload_image(self, path: Path) -> str:
        r = requests.post(
            "https://api.linkedin.com/rest/images?action=initializeUpload",
            headers=self.h, json={"initializeUploadRequest": {"owner": self.author}}, timeout=30)
        r.raise_for_status()
        v = r.json()["value"]
        put = requests.put(v["uploadUrl"], data=path.read_bytes(),
                           headers={"Authorization": self.h["Authorization"]}, timeout=60)
        put.raise_for_status()
        return v["image"]  # urn:li:image:...

    @staticmethod
    def _escape(text: str) -> str:
        # The Posts API "little text" format reserves these characters
        for ch in "\\|{}@[]()<>#*_~":
            text = text.replace(ch, "\\" + ch)
        return text

    def post_with_image(self, text: str, image_path: Path, alt_text: str = "") -> str:
        image_urn = self.upload_image(image_path)
        # Keep hashtags clickable: escape everything, then restore "#word"
        import re
        body = re.sub(r"\\#(\w)", r"#\1", self._escape(text))
        payload = {
            "author": self.author,
            "commentary": body,
            "visibility": "PUBLIC",
            "distribution": {"feedDistribution": "MAIN_FEED",
                             "targetEntities": [], "thirdPartyDistributionChannels": []},
            "content": {"media": {"id": image_urn, "altText": alt_text[:300]}},
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }
        r = requests.post("https://api.linkedin.com/rest/posts",
                          headers=self.h, json=payload, timeout=30)
        if r.status_code >= 400:
            raise RuntimeError(f"LinkedIn post failed {r.status_code}: {r.text}")
        return r.headers.get("x-restli-id", "")
