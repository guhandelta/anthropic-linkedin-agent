import agent


def test_claude_client_has_request_timeout():
    timeout = agent.anthropic_client.timeout
    assert timeout == agent.LLM_TIMEOUT_S and 0 < timeout <= 600


def test_openai_client_has_request_timeout():
    # The OpenAI client is only created when a key is configured; check the setting it was built with.
    if agent.openai_client is None:
        return
    assert agent.openai_client.timeout == agent.LLM_TIMEOUT_S and 0 < agent.openai_client.timeout <= 600
