"""Thin wrapper around Amazon Bedrock for chat completion + embeddings.

Falls back to a deterministic local mock when AWS credentials/region are
not configured (ANAMNESIS_MOCK_LLM=1, or boto3 fails to init) so the rest
of the system is fully testable without live cloud access.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass

EMBEDDING_DIM = 1024
CHAT_MODEL_ID = os.environ.get("BEDROCK_CHAT_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0")
EMBED_MODEL_ID = os.environ.get("BEDROCK_EMBED_MODEL_ID", "amazon.titan-embed-text-v2:0")


def _mock_enabled() -> bool:
    return os.environ.get("ANAMNESIS_MOCK_LLM", "").lower() in ("1", "true", "yes")


# Used by every structured/classification LLM call in anamnesis/memory.py
# and anamnesis/agent/loop.py (belief extraction, contradiction
# confirmation) — these send an instruction embedded in a user-role
# message with no system prompt. Claude via Bedrock follows that reliably
# on its own, but was found (running the real contradiction-detection
# demo repeatedly against local_llm.OllamaClient's much smaller model)
# to sometimes ignore the instruction entirely and answer the *content* of
# the message conversationally instead of extracting/classifying it —
# e.g. asked to extract a belief from "I am not vegetarian anymore, I eat
# meat now", it replied "I'm not aware of any information about your
# dietary preferences" as if chatting, rather than returning the belief
# text. Passing this as an explicit system prompt fixed it completely and
# didn't change Claude/mock behavior (verified against both), so it's used
# unconditionally rather than only for the local-model path.
STRUCTURED_TASK_SYSTEM_PROMPT = (
    "You are a precise information-extraction function, not a conversational "
    "assistant. Follow the instructions in the message exactly and output "
    "only what is requested, nothing else."
)


@dataclass
class ChatMessage:
    role: str  # "user" | "assistant" | "system"
    content: str


class BedrockClient:
    """Lazy-initialized Bedrock Runtime client with a mock fallback."""

    def __init__(self) -> None:
        self._client = None
        self._mock = _mock_enabled()
        if not self._mock:
            try:
                import boto3

                self._client = boto3.client(
                    "bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1")
                )
            except Exception:
                self._mock = True

    def embed(self, text: str) -> list[float]:
        if self._mock:
            return _mock_embedding(text)

        body = json.dumps({"inputText": text})
        resp = self._client.invoke_model(modelId=EMBED_MODEL_ID, body=body)
        payload = json.loads(resp["body"].read())
        return payload["embedding"]

    def chat(self, messages: list[ChatMessage], system: str | None = None, max_tokens: int = 1024) -> str:
        if self._mock:
            return _mock_chat(messages, system)

        body = json.dumps(
            {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": max_tokens,
                "system": system or "",
                "messages": [{"role": m.role, "content": m.content} for m in messages],
            }
        )
        resp = self._client.invoke_model(modelId=CHAT_MODEL_ID, body=body)
        payload = json.loads(resp["body"].read())
        return payload["content"][0]["text"]


def _mock_embedding(text: str) -> list[float]:
    """Deterministic pseudo-embedding derived from a text hash. This has
    NO real semantic structure — two related sentences ("I'm vegetarian" /
    "I eat meat now") land at an essentially random distance from each
    other, not a small one — verified while building scripts/benchmark.py
    and scripts/mvcc_timetravel_demo.py, both of which needed a real local
    embedding model (sentence-transformers) instead of this mock for
    anything that depends on actual similarity (contradiction detection,
    recall quality). This mock is only good enough to exercise the
    database/transaction code paths (storage, retry, audit) in tests and
    local dev without a live model or AWS credentials — never trust it for
    a demo or measurement of recall/contradiction quality.
    """
    digest = hashlib.sha256(text.encode()).digest()
    seed = int.from_bytes(digest[:8], "big")
    vec = []
    x = seed or 1
    for _ in range(EMBEDDING_DIM):
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        vec.append((x / 0x7FFFFFFF) * 2 - 1)
    norm = sum(v * v for v in vec) ** 0.5 or 1.0
    return [v / norm for v in vec]


def _mock_chat(messages: list[ChatMessage], system: str | None) -> str:
    """Deterministic stand-in for local/offline dev and CI.

    Recognizes the two structured judgment prompts used elsewhere in the
    codebase (belief extraction, contradiction confirmation) and answers
    them conservatively (NONE / NO) so mock mode doesn't spuriously
    "discover" a belief or contradiction in every message — the mock has no
    actual language understanding, so guessing YES would be misleading, not
    just imprecise. All other prompts get a generic echo.
    """
    last = messages[-1].content if messages else ""
    if "respond with exactly: NONE" in last:
        return "NONE"
    # "YES or NO" (not the old exact "Answer with exactly one word: YES or
    # NO" phrase) so this still matches memory.py's contradiction-
    # confirmation prompt after it was reworded to ask for chain-of-thought
    # reasoning ending in a YES/NO line — that rewording was needed to fix
    # a real accuracy problem with local_llm.OllamaClient's small model,
    # unrelated to mock mode, but the mock's pattern match has to track it
    # or this silently stops returning its safe "NO" default and falls
    # through to the generic echo instead (caught by re-running
    # tests/test_llm_client_selection.py-style checks after the reword).
    if "YES or NO" in last:
        return "NO"
    return f"[mock-llm] acknowledged: {last[:200]}"


_default_client = None


def get_client():
    """Client selection order:

    1. ANAMNESIS_MOCK_LLM=1 (explicit) -> BedrockClient's own hash/keyword
       mock. Unchanged from before this function grew a second real
       backend — every existing test and the deployed Lambda stack that
       sets this stays on exactly the same code path as always.
    2. Local Ollama server reachable (and mock not explicitly requested)
       -> local_llm.OllamaClient: a genuinely real LLM (Llama 3.2) and a
       genuinely real embedding model, not a mock, running for free with
       no cloud credential. This is what local dev and the demo video use
       by default, since it makes contradiction detection and recall
       actually semantically correct instead of a canned placeholder
       string — Bedrock is blocked on this project's AWS account (see
       README's honest-limitations section), so this is the real-model
       alternative for anything that isn't the deployed Lambda stack
       (which has no Ollama server to reach, and correctly skips straight
       to option 3).
    3. Otherwise -> BedrockClient, which itself falls back to the mock if
       boto3 can't initialize or ANAMNESIS_MOCK_LLM ends up (indirectly)
       relevant. This is the deployed-stack / CI-without-Ollama path.
    """
    global _default_client
    if _default_client is None:
        if not _mock_enabled():
            from . import local_llm

            if local_llm.ollama_reachable():
                _default_client = local_llm.OllamaClient()
        if _default_client is None:
            _default_client = BedrockClient()
    return _default_client
