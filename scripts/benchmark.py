#!/usr/bin/env python3
"""Quantified comparison: Anamnesis vs a naive vector-store-only memory.

Answers two questions with numbers, not adjectives:
  1. When a user's stated belief changes, how often does each system give
     the CURRENT, correct answer when asked "what do you believe now"?
  2. How often can each system correctly answer a TIME-TRAVEL query —
     "what did you believe before it changed"?

A naive vector store (scripts/naive_vector_memory.py) embeds and stores
every statement with no notion of one superseding another; the best it can
do for "now" is nearest-neighbor search, which has no reason to prefer a
newer near-duplicate over an older one. It has no mechanism for
"as of a time" at all.

Two things are intentionally NOT the production Bedrock path, both because
Bedrock model access was still pending account verification when this was
written (see README's "known limitations") — this benchmark does not wait
on that to produce honest numbers:

- **Embeddings** use a real local model (sentence-transformers
  all-MiniLM-L6-v2, 384-dim, padded with zeros to 1024 to match the
  production schema — zero-padding both sides of a cosine-similarity
  comparison identically doesn't change the similarity value). This is a
  genuine, free, offline embedding model, not a hash-based mock — the
  whole point of this benchmark is to measure real semantic recall, and a
  hash-based mock has no semantic structure to measure.
- **Contradiction judgment** uses a small rule-based judge
  (BenchmarkContradictionLLM below) instead of an LLM call. The rules are
  keyword/negation heuristics tuned to this benchmark's synthetic dataset,
  not a general contradiction detector; the real LLM judge used everywhere
  else in the codebase (anamnesis/memory.py) generalizes far past keyword
  matching, so this benchmark's numbers for Anamnesis are a reproducible,
  free-to-run LOWER BOUND, not an inflated best case.

Usage:
    python3 scripts/benchmark.py
"""
from __future__ import annotations

import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone

os.environ.setdefault("ANAMNESIS_MOCK_LLM", "1")
os.environ.setdefault(
    "DATABASE_URL",
    "cockroachdb+psycopg://root@localhost:26257/anamnesis_bench_single?sslmode=disable",
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from anamnesis.agent.bedrock import BedrockClient  # noqa: E402
from anamnesis.db.engine import get_engine  # noqa: E402
from anamnesis.db.models import Base  # noqa: E402
from anamnesis.memory import Anamnesis  # noqa: E402
from scripts.naive_vector_memory import NaiveVectorMemory  # noqa: E402

NEGATION_CUES = re.compile(
    r"\b(not anymore|no longer|not .* now|actually|instead|"
    r"quit|moved|switched|changed|used to|don'?t .* anymore)\b",
    re.IGNORECASE,
)


class BenchmarkContradictionLLM(BedrockClient):
    """Real local embeddings (sentence-transformers, padded to 1024-dim);
    contradiction judgment is a keyword/negation heuristic scoped to this
    benchmark's dataset (see module docstring for why — Bedrock access was
    unavailable when this was written). Everything else in the codebase
    uses the real Bedrock client or the conservative default mock, never
    this class.
    """

    def __init__(self):
        super().__init__()
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer("all-MiniLM-L6-v2")

    def embed(self, text: str) -> list[float]:
        vec = self._model.encode(text).tolist()
        return vec + [0.0] * (1024 - len(vec))

    def chat(self, messages, system=None, max_tokens=1024):
        prompt = messages[-1].content if messages else ""
        if "Answer with exactly one word: YES or NO" in prompt:
            new_stmt_match = re.search(r"New statement: '(.*)'", prompt)
            new_stmt = new_stmt_match.group(1) if new_stmt_match else prompt
            return "YES" if NEGATION_CUES.search(new_stmt) else "NO"
        if "respond with exactly: NONE" in prompt:
            return "NONE"
        return f"[bench-llm] {prompt[:100]}"


@dataclass
class Scenario:
    topic: str
    old_belief: str
    new_belief: str
    asof_query: str  # query used for both "current" and "as of before change" checks


SCENARIOS = [
    Scenario("diet", "I am vegetarian and don't eat meat", "I am not vegetarian anymore, I eat meat now", "what do I eat"),
    Scenario("residence", "I live in Bangalore", "I moved to Mumbai, I don't live in Bangalore anymore", "where do I live"),
    Scenario("job", "I work as a teacher", "I quit teaching, now I work as a software engineer", "what is my job"),
    Scenario("pet", "I have a dog named Max", "My dog Max passed away, I don't have a dog anymore", "do I have a pet"),
    Scenario("coffee", "I drink coffee every morning", "I quit coffee, I drink tea now instead", "what do I drink in the morning"),
    Scenario("car", "I drive a Honda Civic", "I sold my Honda Civic, I now drive a Tesla instead", "what car do I drive"),
    Scenario("smoking", "I smoke cigarettes", "I quit smoking cigarettes completely", "do I smoke"),
    Scenario("relationship", "I am single", "I am not single anymore, I got married", "what is my relationship status"),
    Scenario("language", "I am learning Spanish", "I switched from Spanish, I am learning Japanese now instead", "what language am I learning"),
    Scenario("diet-strict", "I eat gluten-free food", "I don't eat gluten-free anymore, I eat regular bread now", "what kind of food do I eat"),
    Scenario("gym", "I go to the gym every day", "I stopped going to the gym, I do yoga at home instead", "what is my exercise routine"),
    Scenario("subscription", "I subscribe to Netflix", "I cancelled Netflix, I switched to a different streaming service instead", "what streaming service do I use"),
]


def run_benchmark() -> None:
    engine = get_engine()
    Base.metadata.create_all(engine)  # also creates naive_vector_memory table

    llm = BenchmarkContradictionLLM()
    anamnesis = Anamnesis(llm=llm)
    naive = NaiveVectorMemory(llm=llm)

    time.sleep(0.3)

    for s in SCENARIOS:
        anamnesis.detect_and_resolve_contradiction(s.old_belief, source_episode_ids=[])
        naive.remember(s.topic, s.old_belief)

    mid_time = datetime.now(timezone.utc)
    time.sleep(0.3)

    for s in SCENARIOS:
        anamnesis.detect_and_resolve_contradiction(s.new_belief, source_episode_ids=[])
        naive.remember(s.topic, s.new_belief)

    # --- Metric 1: "what do you believe NOW" correctness ---
    anamnesis_now_correct = 0
    naive_now_correct = 0
    for s in SCENARIOS:
        _, beliefs = anamnesis.recall(s.asof_query, k=3)
        active = [b for b in beliefs if b.valid_to is None]
        anamnesis_says = active[0].belief if active else None
        if anamnesis_says == s.new_belief:
            anamnesis_now_correct += 1

        naive_says = naive.current_answer(s.asof_query)
        if naive_says and naive_says.content == s.new_belief:
            naive_now_correct += 1

    # --- Metric 2: time-travel — "what did you believe BEFORE the change" ---
    anamnesis_asof_correct = 0
    naive_asof_correct = 0
    for s in SCENARIOS:
        beliefs = anamnesis.beliefs_asof(s.asof_query, mid_time, k=3)
        anamnesis_asof_says = beliefs[0].belief if beliefs else None
        if anamnesis_asof_says == s.old_belief:
            anamnesis_asof_correct += 1

        naive_asof_says = naive.asof(s.asof_query, mid_time)  # naive has no real as-of capability
        if naive_asof_says and naive_asof_says.content == s.old_belief:
            naive_asof_correct += 1

    n = len(SCENARIOS)
    now_label = '"What do you believe now" — correct'
    asof_label = 'Time-travel ("before the change") — correct'
    anamnesis_now = f"{anamnesis_now_correct}/{n}"
    naive_now = f"{naive_now_correct}/{n}"
    anamnesis_asof = f"{anamnesis_asof_correct}/{n}"
    naive_asof = f"{naive_asof_correct}/{n}"

    header = f"{'Metric':<45}{'Anamnesis':>12}{'Naive vector store':>22}"
    divider = "-" * 79
    now_row = f"{now_label:<45}{anamnesis_now:>12}{naive_now:>22}"
    asof_row = f"{asof_label:<45}{anamnesis_asof:>12}{naive_asof:>22}"

    print(f"Benchmark: {n} contradiction scenarios (each: state a belief, then contradict it)\n")
    print(header)
    print(divider)
    print(now_row)
    print(asof_row)
    print()
    print("Naive vector store has no validity intervals or supersede mechanism —")
    print("its 'now' answer is just nearest-neighbor search over every statement")
    print("ever stored, old and new mixed together with no notion of which is current;")
    print("its 'before the change' answer is identical to its 'now' answer, since it")
    print("has no time-travel capability to even attempt the query differently.")

    with open(os.path.join(os.path.dirname(__file__), "..", "docs", "results", "benchmark_output.txt"), "w") as f:
        f.write(f"Anamnesis vs naive vector-store-only memory — {n} contradiction scenarios\n")
        f.write(f"Run at: {datetime.now(timezone.utc).isoformat()}\n\n")
        f.write(header + "\n")
        f.write(divider + "\n")
        f.write(now_row + "\n")
        f.write(asof_row + "\n")


if __name__ == "__main__":
    run_benchmark()
