"""List the AI models each configured API key can use, and test the models the agent relies on.

Prints model names and pass/fail results only; keys are never printed.
"""
import json
import os
import urllib.error
import urllib.request

# Main and lower models from config.yaml are tested; keep in step with model_fallbacks.
PROBES = {
    "anthropic": ["claude-sonnet-5-5", "claude-sonnet-4-6"],
    "openai": ["gpt-6.1-sol", "gpt-6-sol"],
    "gemini": ["gemini-3.8-flash", "gemini-3.1-pro-preview"],
}


def http(method, url, headers, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={**headers, "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read() or b"{}")
        except Exception:
            payload = {}
        return e.code, payload
    except Exception as e:  # network errors
        return 0, {"error": {"message": type(e).__name__}}


def err_text(payload):
    err = payload.get("error", payload)
    if isinstance(err, dict):
        return (err.get("type") or err.get("status") or err.get("code") or "") + ": " + str(err.get("message", ""))[:160]
    return str(err)[:160]


out = []


def section(title):
    out.append(f"\n## {title}\n")


key = os.getenv("ANTHROPIC_API_KEY")
section("Claude (Anthropic)")
if not key:
    out.append("No key configured.")
else:
    h = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    s, p = http("GET", "https://api.anthropic.com/v1/models?limit=1000", h)
    out.append(f"Models listed by the key: " + (", ".join(sorted(m["id"] for m in p.get("data", []))) if s == 200 else f"listing failed ({s}) {err_text(p)}"))
    for m in PROBES["anthropic"]:
        s, p = http("POST", "https://api.anthropic.com/v1/messages", h,
                    {"model": m, "max_tokens": 16, "messages": [{"role": "user", "content": "Say OK"}]})
        out.append(f"- Test call `{m}`: " + ("WORKS" if s == 200 else f"FAILED ({s}) {err_text(p)}"))

key = os.getenv("OPENAI_API_KEY") or os.getenv("OPEN_AI_API_KEY")
section("OpenAI")
if not key:
    out.append("No key configured.")
else:
    h = {"authorization": f"Bearer {key}"}
    s, p = http("GET", "https://api.openai.com/v1/models", h)
    ids = sorted(m["id"] for m in p.get("data", [])) if s == 200 else []
    keep = [i for i in ids if i.startswith(("gpt-", "o1", "o3", "o4", "sol"))] or ids
    out.append(f"Chat models listed by the key: " + (", ".join(keep) if s == 200 else f"listing failed ({s}) {err_text(p)}"))
    for m in PROBES["openai"]:
        s, p = http("POST", "https://api.openai.com/v1/responses", h,
                    {"model": m, "input": "Say OK", "max_output_tokens": 64, "reasoning": {"effort": "low"}})
        out.append(f"- Test call `{m}`: " + ("WORKS" if s == 200 else f"FAILED ({s}) {err_text(p)}"))

key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
section("Gemini (Google)")
if not key:
    out.append("No key configured.")
else:
    h = {"x-goog-api-key": key}
    base = "https://generativelanguage.googleapis.com/v1beta"
    s, p = http("GET", f"{base}/models?pageSize=1000", h)
    ids = sorted(m["name"].split("/", 1)[-1] for m in p.get("models", [])
                 if "generateContent" in m.get("supportedGenerationMethods", [])) if s == 200 else []
    out.append(f"Models listed by the key: " + (", ".join(ids) if s == 200 else f"listing failed ({s}) {err_text(p)}"))
    for m in PROBES["gemini"]:
        s, p = http("POST", f"{base}/models/{m}:generateContent", h,
                    {"contents": [{"parts": [{"text": "Say OK"}]}]})
        out.append(f"- Test call `{m}`: " + ("WORKS" if s == 200 else f"FAILED ({s}) {err_text(p)}"))

report = "# Models available to the agent\n" + "\n".join(out) + "\n"
print(report)
summary = os.getenv("GITHUB_STEP_SUMMARY")
if summary:
    with open(summary, "a") as f:
        f.write(report)
