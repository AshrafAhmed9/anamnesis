from __future__ import annotations

from unittest.mock import patch


def test_mock_llm_env_var_wins_even_if_ollama_is_reachable(monkeypatch):
    """ANAMNESIS_MOCK_LLM=1 must be an unconditional override — this is
    the flag every test and the deployed Lambda stack relies on, and it
    must not be silently superseded by get_client()'s newer
    Ollama-detection branch (anamnesis/agent/bedrock.py)."""
    import anamnesis.agent.bedrock as bedrock_module

    monkeypatch.setenv("ANAMNESIS_MOCK_LLM", "1")
    bedrock_module._default_client = None

    with patch("anamnesis.agent.local_llm.ollama_reachable", return_value=True) as mock_reachable:
        client = bedrock_module.get_client()

    assert isinstance(client, bedrock_module.BedrockClient)
    assert client._mock is True
    mock_reachable.assert_not_called()  # never even checked — the explicit flag short-circuits it

    bedrock_module._default_client = None


def test_ollama_used_when_reachable_and_mock_not_forced(monkeypatch):
    """When ANAMNESIS_MOCK_LLM isn't set and a local Ollama server answers
    its health check, get_client() should route to the real local model
    instead of Bedrock/mock — this is what local dev and the demo video
    rely on for genuine (non-mocked) reasoning without any cloud
    credential, since Bedrock is blocked on this project's AWS account."""
    import anamnesis.agent.bedrock as bedrock_module
    import anamnesis.agent.local_llm as local_llm_module

    monkeypatch.delenv("ANAMNESIS_MOCK_LLM", raising=False)
    bedrock_module._default_client = None

    with patch.object(local_llm_module, "ollama_reachable", return_value=True):
        client = bedrock_module.get_client()

    assert isinstance(client, local_llm_module.OllamaClient)

    bedrock_module._default_client = None


def test_falls_through_to_bedrock_when_ollama_unreachable(monkeypatch):
    """No local Ollama server (e.g. the deployed Lambda stack, or a dev
    machine without it running) -> falls through to BedrockClient exactly
    as before this module existed, never raises."""
    import anamnesis.agent.bedrock as bedrock_module
    import anamnesis.agent.local_llm as local_llm_module

    monkeypatch.delenv("ANAMNESIS_MOCK_LLM", raising=False)
    bedrock_module._default_client = None

    with patch.object(local_llm_module, "ollama_reachable", return_value=False):
        client = bedrock_module.get_client()

    assert isinstance(client, bedrock_module.BedrockClient)

    bedrock_module._default_client = None


def test_ollama_reachable_returns_false_fast_when_nothing_listening():
    """A real (not mocked) check against a port nothing is listening on —
    proves the health check fails cleanly (False, no exception) rather
    than hanging or raising, which matters because get_client() calls
    this unconditionally whenever mock mode isn't explicitly forced."""
    import anamnesis.agent.local_llm as local_llm_module

    with patch.object(local_llm_module, "OLLAMA_HOST", "http://localhost:1"):
        assert local_llm_module.ollama_reachable(timeout=0.5) is False
