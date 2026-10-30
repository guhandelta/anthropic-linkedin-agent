"""One-time LinkedIn OAuth 2.0 authorization script.

Flow:
1. Generates a secure CSRF state token and starts a temporary local HTTP server on port 8765.
2. Opens the official LinkedIn OAuth 2.0 consent URL in your default browser.
3. You sign in and authorize the requested scopes:
   - openid: OpenID Connect identity authentication
   - profile: Access to basic member profile name/id
   - w_member_social: Permission to post content, images, and comments to your feed
4. LinkedIn redirects to http://localhost:8765/callback with an authorization code.
5. Exchanges the temporary authorization code for an OAuth 2.0 access token via LinkedIn's token endpoint.
6. Automatically saves the resulting LINKEDIN_ACCESS_TOKEN into your local .env file.
Tokens are valid for 60 days; rerun this script whenever your token approaches expiration.
"""

import os
import secrets
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import requests
from dotenv import load_dotenv, set_key

# Load existing environment credentials
ENV = Path(__file__).parent / ".env"
load_dotenv(ENV)

# Verify required client credentials
if "LINKEDIN_CLIENT_ID" not in os.environ or "LINKEDIN_CLIENT_SECRET" not in os.environ:
    raise SystemExit("Missing LINKEDIN_CLIENT_ID or LINKEDIN_CLIENT_SECRET in .env.")

CLIENT_ID = os.environ["LINKEDIN_CLIENT_ID"]
CLIENT_SECRET = os.environ["LINKEDIN_CLIENT_SECRET"]
REDIRECT = "http://localhost:8765/callback"

# Cryptographically random state parameter to prevent CSRF attacks
STATE = secrets.token_urlsafe(16)
result = {}


class Handler(BaseHTTPRequestHandler):
    """Temporary local HTTP request handler to capture OAuth redirect callback."""
    
    def do_GET(self):
        result["path"] = self.path
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        
        if "error" in q:
            result["error"] = q["error"][0] + " " + q.get("error_description", [""])[0]
        elif q.get("state", [""])[0] == STATE and "code" in q:
            result["code"] = q["code"][0]
            
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        ok = "code" in result
        self.wfile.write(("Done, you can close this tab." if ok
                          else "Login failed. Check the terminal.").encode())

    def log_message(self, *a):
        """Suppress default HTTP server access logs in stdout."""
        pass


if __name__ == "__main__":
    # Construct official LinkedIn OAuth authorization URL
    auth_url = "https://www.linkedin.com/oauth/v2/authorization?" + urllib.parse.urlencode({
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT,
        "state": STATE,
        "scope": "openid profile w_member_social"
    })
    print("Opening LinkedIn login in your browser...\n", auth_url)
    webbrowser.open(auth_url)
    
    # Wait for the browser redirect to hit localhost:8765
    HTTPServer(("localhost", 8765), Handler).handle_request()

    # Validate callback outcome
    if "error" in result:
        raise SystemExit(f"LinkedIn returned an error: {result['error']}")
    if "code" not in result:
        raise SystemExit(f"No valid code received. Callback was: {result.get('path')}")

    # Exchange authorization code for a long-lived access token
    tok = requests.post(
        "https://www.linkedin.com/oauth/v2/accessToken",
        data={
            "grant_type": "authorization_code",
            "code": result["code"],
            "redirect_uri": REDIRECT,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET
        },
        timeout=30
    ).json()

    if "access_token" not in tok:
        raise SystemExit(f"Token exchange failed: {tok}")

    # Persist token to .env file
    set_key(str(ENV), "LINKEDIN_ACCESS_TOKEN", tok["access_token"])
    days = tok.get("expires_in", 0) // 86400
    print(f"\n✅ Successfully saved LINKEDIN_ACCESS_TOKEN to .env (valid for approximately {days} days).")