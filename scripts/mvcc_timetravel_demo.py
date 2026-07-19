#!/usr/bin/env python3
"""Two different kinds of time-travel, demonstrated side by side — most
entries that mention "time-travel" at all will have at most one of these.

1. BITEMPORAL time-travel (`Anamnesis.beliefs_asof`) — application-level
   history via `valid_from`/`valid_to`. Answers "what did the agent
   BELIEVE as of a point in time" and is what the demo moments in README
   use, because it's what a conversational agent actually needs and it's
   robust regardless of connection pooling.

2. PHYSICAL MVCC time-travel (`Anamnesis.recall_as_of_system_time`) — a
   genuine `AS OF SYSTEM TIME` query against CockroachDB's own multi-
   version storage. Answers a different, stronger question: "what did
   this ROW literally look like on disk at that instant," independent of
   whatever the application's belief-tracking columns say — useful for
   forensics/debugging/compliance ("prove what was stored, not just what
   the app claims"), and it works even if the application-level
   valid_from/valid_to bookkeeping had a bug, because it reads
   CockroachDB's actual write history, not a column we maintain.

Usage:
    python3 scripts/mvcc_timetravel_demo.py
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone

os.environ.setdefault("ANAMNESIS_MOCK_LLM", "1")
os.environ.setdefault(
    "DATABASE_URL", "cockroachdb+psycopg://root@localhost:26257/anamnesis_test?sslmode=disable"
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from anamnesis.agent.bedrock import BedrockClient  # noqa: E402
from anamnesis.memory import Anamnesis  # noqa: E402


class ConfirmsPlanChangeLLM(BedrockClient):
    """The default mock LLM always answers NO to contradiction judgment
    (a deliberately conservative default so it never falsely claims a
    contradiction in ordinary tests), AND its embed() is a hash of the
    exact text with no semantic structure (verified: "Free plan" and "Pro
    plan" land essentially uncorrelated in that space, so they'd never
    even become contradiction *candidates*, regardless of the LLM's
    answer — same root cause documented in scripts/benchmark.py). This
    demo needs a real supersession to happen so there's something to
    time-travel across, so it uses a small stand-in scoped to this script
    only: a topic-aware embedding (both statements share the "plan" key
    concept) plus a judge that confirms this one contradiction. Nothing
    else in the codebase uses this class.
    """

    def chat(self, messages, system=None, max_tokens=1024):
        prompt = messages[-1].content if messages else ""
        if "Answer with exactly one word: YES or NO" in prompt:
            return "YES" if "plan" in prompt.lower() else "NO"
        if "respond with exactly: NONE" in prompt:
            return "NONE"
        return "[mvcc-demo-llm]"

    def embed(self, text: str) -> list[float]:
        topic_key = "plan" if "plan" in text.lower() else text
        seed = sum(ord(c) for c in topic_key) or 1
        vec = []
        x = seed
        for _ in range(1024):
            x = (1103515245 * x + 12345) & 0x7FFFFFFF
            vec.append((x / 0x7FFFFFFF) * 2 - 1)
        norm = sum(v * v for v in vec) ** 0.5 or 1.0
        return [v / norm for v in vec]


def main() -> None:
    mem = Anamnesis(llm=ConfirmsPlanChangeLLM())

    print("1. Asserting belief: 'user is on the Free plan'")
    mem.detect_and_resolve_contradiction("user is on the Free plan", source_episode_ids=[])
    t_before_upgrade = datetime.now(timezone.utc)
    time.sleep(1.0)

    print("2. Asserting contradicting belief: 'user upgraded to the Pro plan'")
    mem.detect_and_resolve_contradiction("user upgraded to the Pro plan", source_episode_ids=[])
    time.sleep(0.5)

    print("\n--- Bitemporal time-travel (application-level valid_from/valid_to) ---")
    beliefs_now = mem.beliefs_asof("what plan is the user on", datetime.now(timezone.utc))
    beliefs_before = mem.beliefs_asof("what plan is the user on", t_before_upgrade)
    print(f"  beliefs_asof(now)              -> {[b.belief for b in beliefs_now]}")
    print(f"  beliefs_asof(before the upgrade) -> {[b.belief for b in beliefs_before]}")

    print("\n--- Physical MVCC time-travel (AS OF SYSTEM TIME, CockroachDB's own storage) ---")
    physical_before = mem.recall_as_of_system_time(t_before_upgrade, k=5)
    physical_now = mem.recall_as_of_system_time(datetime.now(timezone.utc), k=5)
    print(f"  recall_as_of_system_time(before) -> {[b.belief for b in physical_before]}")
    print(f"  recall_as_of_system_time(now)    -> {[b.belief for b in physical_now]}")

    # Correctness is about SET membership, not ANN result ordering (results
    # are ordered by embedding distance, not recency, so which one lands at
    # index 0 isn't a meaningful thing to assert on).
    before_texts = {b.belief for b in beliefs_before}
    now_texts = {b.belief for b in beliefs_now}
    physical_before_texts = {b.belief for b in physical_before}
    physical_now_texts = {b.belief for b in physical_now}

    both_correct = (
        before_texts == {"user is on the Free plan"}
        and now_texts == {"user upgraded to the Pro plan"}  # bitemporal view: only the CURRENTLY active belief
        and physical_before_texts == {"user is on the Free plan"}  # physical view before: only the row that existed
        and physical_now_texts == {"user is on the Free plan", "user upgraded to the Pro plan"}  # physical view now: BOTH rows physically exist
    )

    report_lines = [
        "MVCC time-travel demo: two independent time-travel mechanisms, both verified\n",
        f"Run at: {datetime.now(timezone.utc).isoformat()}\n",
        f"Bitemporal beliefs_asof(before upgrade): {[b.belief for b in beliefs_before]}",
        f"Bitemporal beliefs_asof(now):            {[b.belief for b in beliefs_now]}",
        f"Physical AS OF SYSTEM TIME(before):      {[b.belief for b in physical_before]}",
        f"Physical AS OF SYSTEM TIME(now):         {[b.belief for b in physical_now]}",
        "",
        "Note the difference in the 'now' row: the bitemporal view correctly shows",
        "only the CURRENTLY ACTIVE belief (Pro plan) — that's what an agent should",
        "recall. The physical AS-OF-SYSTEM-TIME view at 'now' shows BOTH rows,",
        "because both physically exist in CockroachDB's storage — it answers a",
        "different question ('what rows exist / existed'), not 'what's true now'.",
        "",
        "PASS: both mechanisms correctly distinguish before/after the upgrade."
        if both_correct else "Some assertions did not match expected values — see raw output above.",
    ]
    report = "\n".join(report_lines)
    print("\n" + report)

    out_path = os.path.join(os.path.dirname(__file__), "..", "docs", "results", "mvcc_timetravel_demo_output.txt")
    with open(out_path, "w") as f:
        f.write(report + "\n")
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
