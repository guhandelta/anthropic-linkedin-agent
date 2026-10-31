"""Safely verify Anthropic → OpenAI and Anthropic → OpenAI → Gemini fallback.

Failures are simulated for preceding providers; each target provider makes one
real JSON API request. No Telegram or LinkedIn operation is performed.
"""

from pathlib import Path
import sys
from unittest.mock import patch

from anthropic import BadRequestError
from httpx import Request, Response

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agent  # noqa: E402


def simulated_anthropic_billing_error() -> BadRequestError:
    """Match the HTTP 400 exception seen in the failed GitHub Actions run."""
    response = Response(400, request=Request("POST", "https://api.anthropic.com/v1/messages"))
    return BadRequestError(
        "Simulated Anthropic credit balance too low",
        response=response,
        body={"error": {"type": "invalid_request_error",
                        "message": "Your credit balance is too low to access the Anthropic API."}},
    )


def main() -> None:
    if not agent.openai_client:
        raise SystemExit("OPENAI_API_KEY (or OPEN_AI_API_KEY) is missing; cannot test OpenAI fallback.")
    if not agent.gemini_client:
        raise SystemExit("GOOGLE_API_KEY (or GEMINI_API_KEY) is missing; cannot test Gemini fallback.")

    agent.CURRENT_TELEGRAM_REVIEWER = None
    agent.CURRENT_TRACKER_ID = None

    agent.ACTIVE_LLM_PROVIDER = "anthropic"
    agent.DISABLED_PROVIDERS.clear()
    with patch.object(agent, "call_anthropic_json", side_effect=simulated_anthropic_billing_error()):
        response = agent.call_json(
            'Return only JSON with the key "ok" set to true.',
            'Confirm the fallback provider is responding.',
            max_tokens=100,
        )

    if agent.ACTIVE_LLM_PROVIDER != "openai" or response.get("ok") is not True:
        raise SystemExit("Fallback check failed: OpenAI did not return the expected response.")
    print("Fallback check 1/2 passed: Anthropic → OpenAI returned valid JSON.")

    agent.ACTIVE_LLM_PROVIDER = "anthropic"
    agent.DISABLED_PROVIDERS.clear()
    with (patch.object(agent, "call_anthropic_json", side_effect=simulated_anthropic_billing_error()),
          patch.object(agent, "call_openai_json", side_effect=RuntimeError("Simulated OpenAI outage"))):
        response = agent.call_json(
            'Return only JSON with the key "ok" set to true.',
            'Confirm the second fallback provider is responding.',
            max_tokens=100,
        )

    if agent.ACTIVE_LLM_PROVIDER != "gemini" or response.get("ok") is not True:
        raise SystemExit("Fallback check failed: Gemini did not return the expected response.")
    print("Fallback check 2/2 passed: Anthropic → OpenAI → Gemini returned valid JSON.")


if __name__ == "__main__":
    main()
