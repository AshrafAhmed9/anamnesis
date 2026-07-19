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
    if "Answer with exactly one word: YES or NO" in last:
        return "NO"
    return f"[mock-llm] acknowledged: {last[:200]}"


_default_client: BedrockClient | None = None


def get_client() -> BedrockClient:
    global _default_client
    if _default_client is None:
        _default_client = BedrockClient()
    return _default_client
