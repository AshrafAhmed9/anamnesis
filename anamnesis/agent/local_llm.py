"""A genuinely real (not mocked) LLM backend that needs neither AWS Bedrock
nor any paid API key: a local Ollama server for chat, and sentence-
transformers for embeddings — both already used and validated elsewhere in
this repo (scripts/benchmark.py, scripts/scale_test.py) as the "real
semantic behavior" fallback for exactly the reason this class exists again
here: Bedrock access is blocked on this AWS account (see README's honest-
limitations section and AWS Support case 178439660900442).

This is NOT a mock. `chat()` calls a real language model (Llama 3.2, run
via Ollama) and `embed()` calls a real sentence embedding model — both
produce genuinely meaningful output, unlike anamnesis/agent/bedrock.py's
`_mock_chat`/`_mock_embedding`, which are deliberately non-semantic
placeholders only good enough to exercise storage/transaction code paths.

Used automatically by `get_client()` in bedrock.py when a local Ollama
server is reachable and ANAMNESIS_MOCK_LLM is not explicitly set — i.e.
for local dev and the demo video, not for the deployed Lambda stack
(which has no Ollama server to reach, and correctly falls through to
Bedrock or the explicit mock instead). Never bundled into the Lambda
deployment package: sentence-transformers pulls in torch, which is far
too large for a Lambda zip and is not listed in requirements.txt (only
in pyproject.toml's optional `bench` group), so importing this module
outside a machine that has it installed raises ImportError — by design,
not an oversight.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from .bedrock import EMBEDDING_DIM, ChatMessage

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_CHAT_MODEL = os.environ.get("OLLAMA_CHAT_MODEL", "llama3.2")
_EMBED_MODEL_NAME = "all-MiniLM-L6-v2"  # 384-dim; zero-padded to EMBEDDING_DIM below


def ollama_reachable(timeout: float = 0.5) -> bool:
    """Cheap health check so get_client() can decide whether to route here
    at all, rather than failing mid-request the first time a demo message
    comes in."""
    try:
        urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=timeout)
        return True
    except Exception:  # noqa: BLE001 — any failure (connection refused, DNS,
        # timeout, ...) just means "not reachable"; get_client() falls
        # through to Bedrock/mock either way, so the specific exception
        # type is never actionable here.
        return False


class OllamaClient:
    """Drop-in replacement for BedrockClient's two-method interface
    (embed/chat), backed by a real local model instead of AWS."""

    def __init__(self) -> None:
        self._embed_model = None  # lazy: sentence-transformers + its model
        # weights are a multi-hundred-MB import/load cost we don't want to
        # pay unless embed() is actually called.

    def embed(self, text: str) -> list[float]:
        if self._embed_model is None:
            from sentence_transformers import SentenceTransformer

            self._embed_model = SentenceTransformer(_EMBED_MODEL_NAME)
        vec = self._embed_model.encode(text).tolist()
        # Zero-padding 384 -> EMBEDDING_DIM preserves cosine similarity
        # exactly (verified: padding both vectors in a comparison with the
        # same number of zeros scales neither the dot product nor either
        # norm's non-zero component), so ANN search and contradiction
        # detection behave identically to a native EMBEDDING_DIM-length
        # embedding — this is the same approach scripts/benchmark.py uses.
        return vec + [0.0] * (EMBEDDING_DIM - len(vec))

    def chat(self, messages: list[ChatMessage], system: str | None = None, max_tokens: int = 1024) -> str:
        payload = {
            "model": OLLAMA_CHAT_MODEL,
            "messages": (
                ([{"role": "system", "content": system}] if system else [])
                + [{"role": m.role, "content": m.content} for m in messages]
            ),
            "stream": False,
            # temperature=0: found by actually running the contradiction
            # demo repeatedly, not by inspection. Ollama's default sampling
            # made belief-extraction paraphrase the same input differently
            # between runs (e.g. "I am no longer vegetarian." vs "He or she
            # does not eat meat." for the identical user message) — and
            # that wording drift was sometimes enough to push the new
            # belief's embedding past CONTRADICTION_SIM_THRESHOLD, so the
            # supersede detection silently didn't fire on some runs of the
            # exact same conversation. Deterministic decoding removes that
            # source of demo flakiness; it does not fix the general
            # phrasing-sensitivity limitation itself (a sufficiently
            # different paraphrase can still miss), which stays honestly
            # documented in README rather than hidden by this change.
            "options": {"num_predict": max_tokens, "temperature": 0},
        }
        req = urllib.request.Request(
            f"{OLLAMA_HOST}/api/chat",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read())
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Ollama chat request failed ({exc}) — is `ollama serve` running "
                f"and has `ollama pull {OLLAMA_CHAT_MODEL}` been run?"
            ) from exc
        return body["message"]["content"]
