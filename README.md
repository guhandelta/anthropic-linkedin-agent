# LinkedIn Post Agent

Posts one quality-checked LinkedIn post with a matching infographic every day.

```
topics.txt → Writer (Claude) → hard checks → render infographic (Pillow)
          → Reviewer (Claude, reads text + looks at image) → approved? → LinkedIn
                         ↑______ rejected: feedback, retry (max 3) ______|
```

If all 3 attempts fail review, **nothing is posted** that day.

## Quality gate
- **Code checks:** character range (config), LinkedIn 3000 limit, repeated words, garbled characters, markdown/JSON leftovers.
- **Reviewer scores 1–5:** meaningful, accurate, on-topic, image text legible, image matches post, professional. Every score must be ≥ 4.
- **Infographic** is drawn from a JSON spec written alongside the post, so its text is always spelled correctly and covers the same points.

## Setup
1. `pip install -r requirements.txt`, copy `.env.example` to `.env`.
2. **Anthropic key:** console.anthropic.com.
3. **LinkedIn token:**
   - Create an app at linkedin.com/developers/apps (needs a LinkedIn Page to associate).
   - Products tab: add **Sign In with LinkedIn using OpenID Connect** and **Share on LinkedIn**.
   - Auth tab: use the OAuth 2.0 token generator with scopes `openid profile w_member_social`.
   - Tokens last ~60 days; regenerate and update the secret before expiry.
4. Edit `config.yaml` (character limits, voice, colours) and `topics.txt`.
5. Test: `python agent.py --dry-run` → check `output/<date>/`.
6. Real post: `python agent.py`.

## Daily schedule (GitHub Actions)
Push to a **private** repo, add secrets `ANTHROPIC_API_KEY` and `LINKEDIN_ACCESS_TOKEN`, and the workflow posts daily at 9:17 AM ET. Run it manually from the Actions tab anytime. `posted.json` is committed back so topics aren't repeated.

Note: automated posting via the official API is allowed; keep content genuine and watch the first few runs.
