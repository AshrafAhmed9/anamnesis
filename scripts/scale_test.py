#!/usr/bin/env python3
"""Scale test: load thousands of real embeddings into CockroachDB's
distributed vector index and measure ANN query latency — the hackathon's
own judging criteria calls out "more than toy queries," so this measures
what happens well past toy scale, not just correctness on a handful of
rows (see scripts/benchmark.py for the correctness comparison).

Uses real sentence-transformers embeddings (see scripts/benchmark.py's
docstring for why: a hash-based mock has no semantic structure and the
point here is measuring a real ANN index), batch-encoded and bulk-inserted
for throughput, then queries go through the same `<->` ANN operator
anamnesis/memory.py uses in production.

Usage:
    python3 scripts/scale_test.py [--rows 5000] [--queries 50]
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import time
import uuid
from datetime import datetime, timezone

os.environ.setdefault("ANAMNESIS_MOCK_LLM", "1")
os.environ.setdefault(
    "DATABASE_URL", "cockroachdb+psycopg://root@localhost:26257/anamnesis_scale?sslmode=disable"
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

from anamnesis.db.engine import get_engine, run_in_transaction  # noqa: E402

TOPICS = [
    "diet and food preferences", "travel plans", "work projects", "family updates",
    "hobbies and interests", "health and fitness", "financial goals", "home renovation",
    "book recommendations", "movie opinions", "technology purchases", "pet care",
    "relationship updates", "career changes", "vacation memories", "daily routines",
    "weather complaints", "sports commentary", "cooking experiments", "music taste",
]
TEMPLATES = [
    "I mentioned that {t} has been on my mind lately.",
    "Talking about {t}, I think things are going well.",
    "My thoughts on {t}: it's been a mixed experience.",
    "Quick update regarding {t} — nothing major changed.",
    "I wanted to note something about {t} for later.",
    "Reflecting on {t}, I realize I should plan more.",
]


def generate_sentences(n: int) -> list[str]:
    rng = random.Random(42)
    return [
        rng.choice(TEMPLATES).format(t=rng.choice(TOPICS)) + f" (entry {i})"
        for i in range(n)
    ]


def percentile(values: list[float], p: float) -> float:
    s = sorted(values)
    idx = min(int(len(s) * p), len(s) - 1)
    return s[idx]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=5000)
    parser.add_argument("--queries", type=int, default=50)
    parser.add_argument("--batch-size", type=int, default=250)
    args = parser.parse_args()

    from sentence_transformers import SentenceTransformer

    print("Loading embedding model...")
    model = SentenceTransformer("all-MiniLM-L6-v2")

    print(f"Generating {args.rows} synthetic episodic memories...")
    sentences = generate_sentences(args.rows)

    print("Encoding embeddings (batched)...")
    t0 = time.monotonic()
    raw_vecs = model.encode(sentences, batch_size=128, show_progress_bar=False)
    encode_elapsed = time.monotonic() - t0
    print(f"  encoded {args.rows} sentences in {encode_elapsed:.1f}s "
          f"({args.rows / encode_elapsed:.0f}/s)")

    engine = get_engine()
    session_id = uuid.uuid4()

    print(f"Bulk inserting in batches of {args.batch_size}...")
    t0 = time.monotonic()
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM episodic_memory"))
    for batch_start in range(0, args.rows, args.batch_size):
        batch = sentences[batch_start:batch_start + args.batch_size]
        batch_vecs = raw_vecs[batch_start:batch_start + args.batch_size]
        rows = [
            {
                "id": str(uuid.uuid4()),
                "session_id": str(session_id),
                "role": "user",
                "content": content,
                "embedding": "[" + ",".join(repr(float(v)) for v in vec.tolist() + [0.0] * (1024 - len(vec))) + "]",
            }
            for content, vec in zip(batch, batch_vecs)
        ]
        def _do(db, rows=rows):
            db.execute(
                text(
                    """
                    INSERT INTO episodic_memory (id, session_id, role, content, embedding, salience, created_at)
                    VALUES (:id, :session_id, :role, :content, :embedding, 0.5, now())
                    """
                ),
                rows,
            )

        # Bulk-loading a vector index at speed contends on internal
        # partition metadata (a real SerializationFailure under load, not
        # a bug) — the same run_in_transaction retry primitive the
        # production write path uses handles it here too.
        run_in_transaction(_do)
    insert_elapsed = time.monotonic() - t0
    print(f"  inserted {args.rows} rows in {insert_elapsed:.1f}s "
          f"({args.rows / insert_elapsed:.0f} rows/s)")

    print(f"\nRunning {args.queries} ANN queries (k=5) against the {args.rows}-row vector index...")
    query_sentences = generate_sentences(args.queries)
    query_vecs = model.encode(query_sentences, batch_size=32, show_progress_bar=False)

    latencies_ms = []
    with engine.connect() as conn:
        for vec in query_vecs:
            padded = "[" + ",".join(repr(float(v)) for v in vec.tolist() + [0.0] * (1024 - len(vec))) + "]"
            t0 = time.monotonic()
            conn.execute(
                text(
                    "SELECT id, content FROM episodic_memory ORDER BY embedding <-> :qv LIMIT 5"
                ),
                {"qv": padded},
            ).fetchall()
            latencies_ms.append((time.monotonic() - t0) * 1000)

    p50 = percentile(latencies_ms, 0.50)
    p95 = percentile(latencies_ms, 0.95)
    p99 = percentile(latencies_ms, 0.99)
    mx = max(latencies_ms)

    report = (
        f"Scale test: {args.rows} rows in episodic_memory, {args.queries} ANN queries (k=5)\n"
        f"Run at: {datetime.now(timezone.utc).isoformat()}\n\n"
        f"Embedding throughput:  {args.rows / encode_elapsed:.0f} sentences/s "
        f"(sentence-transformers all-MiniLM-L6-v2, CPU)\n"
        f"Insert throughput:     {args.rows / insert_elapsed:.0f} rows/s "
        f"(batches of {args.batch_size}, real CockroachDB transactions)\n\n"
        f"ANN query latency over {args.rows} rows (CREATE VECTOR INDEX, C-SPANN):\n"
        f"  p50: {p50:.1f}ms\n"
        f"  p95: {p95:.1f}ms\n"
        f"  p99: {p99:.1f}ms\n"
        f"  max: {mx:.1f}ms\n"
    )
    print("\n" + report)

    out_path = os.path.join(os.path.dirname(__file__), "..", "docs", "results", "scale_test_output.txt")
    with open(out_path, "w") as f:
        f.write(report)
    print(f"Saved to {out_path}")


if __name__ == "__main__":
    main()
