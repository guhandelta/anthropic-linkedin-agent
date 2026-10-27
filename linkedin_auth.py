"""One-time LinkedIn login: gets an access token and saves it to .env.

Before running:
  1. Create an app at https://www.linkedin.com/developers/apps
  2. Products tab: add "Sign In with LinkedIn using OpenID Connect" and "Share on LinkedIn"
  3. Auth tab: add redirect URL  http://localhost:8765/callback
  4. Put LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET in .env

Run:  python linkedin_auth.py
A browser opens, you sign in and click Allow, and LINKEDIN_ACCESS_TOKEN is written
to .env. The token lasts about 60 days; run this again to renew it.
"""
import os
import secrets
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import requests
from dotenv import load_dotenv, set_key

ENV = Path(__file__).parent / ".env"
load_dotenv(ENV)
CLIENT_ID = os.environ["LINKEDIN_CLIENT_ID"]
CLIENT_SECRET = os.environ["LINKEDIN_CLIENT_SECRET"]
REDIRECT = "http://localhost:8765/callback"
STATE = secrets.token_urlsafe(16)
result = {}


class Handler(BaseHTTPRequestHandler):
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
        pass


auth_url = "https://www.linkedin.com/oauth/v2/authorization?" + urllib.parse.urlencode({
    "response_type": "code", "client_id": CLIENT_ID, "redirect_uri": REDIRECT,
    "state": STATE, "scope": "openid profile w_member_social"})
print("Opening LinkedIn login...\n", auth_url)
webbrowser.open(auth_url)
HTTPServer(("localhost", 8765), Handler).handle_request()

if "error" in result:
    raise SystemExit(f"LinkedIn returned an error: {result['error']}")
if "code" not in result:
    raise SystemExit(f"No valid code. Callback was: {result.get('path')}")

tok = requests.post("https://www.linkedin.com/oauth/v2/accessToken", data={
    "grant_type": "authorization_code", "code": result["code"], "redirect_uri": REDIRECT,
    "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET}, timeout=30).json()
if "access_token" not in tok:
    raise SystemExit(f"Token exchange failed: {tok}")
set_key(str(ENV), "LINKEDIN_ACCESS_TOKEN", tok["access_token"])
print(f"Saved LINKEDIN_ACCESS_TOKEN to .env (valid about {tok.get('expires_in', 0) // 86400} days).")