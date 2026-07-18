# CockroachDB Agent Skills used in this project

This project installed and used real skills from the official, open-source
[CockroachDB Agent Skills Repo](https://github.com/cockroachlabs/cockroachdb-skills)
(`cockroachlabs/cockroachdb-skills`, Apache-2.0), via:

```bash
npx skills add cockroachlabs/cockroachdb-skills
```

which populates `.agents/skills/` in this repo (35 skills, symlinked for
Claude Code). Two skills were concretely applied, not just installed:

## `designing-application-transactions`

Applied while hardening the retry engine in `anamnesis/db/engine.py` and
`anamnesis/memory.py`. The skill's first rule — "transactions must include
only the minimal set of SQL operations; do not place remote API calls
inside a CockroachDB transaction, since a retried transaction would
otherwise re-issue them" — caught a real bug in the original
implementation: `detect_and_resolve_contradiction()` and `consolidate()`
both called the Bedrock LLM *inside* the retryable transaction body. That
meant a retry would re-issue the (slow, costly, non-deterministic) LLM
call, not just redo the database write. Both methods were restructured so
the LLM call happens once, before the transaction opens, and only
deterministic reads/writes are retried — with a fresh in-transaction
re-check that a candidate belief wasn't superseded by something else in
the gap, since the pre-read can now be stale by the time the write
transaction runs.

## `cockroachdb-sql`

Applied to review the schema in `anamnesis/db/schema.sql` against the
skill's `04-optimization.md` rules. It flagged `memory_audit_at_idx`, a
plain B-tree index on `memory_audit(at DESC)`, as a hotspot risk: `at` is
monotonically increasing, so every audit write would land on the same
range. Fixed with a hash-sharded index (`USING HASH WITH (bucket_count =
8)`) — see `migrations/versions/0002_hash_shard_audit_index.py` — which
was verified via `SHOW INDEXES FROM memory_audit` on both the local dev
cluster and the live CockroachDB Cloud cluster to confirm the shard column
is actually present.

## Tool feedback (submission's optional item)

- The `cockroachdb-sql` skill's optimization rules were directly actionable
  and caught a real design flaw we'd have shipped otherwise (the hotspot
  index above).
- One rough edge unrelated to the skills themselves: a fresh CockroachDB
  Cloud cluster has `feature.vector_index.enabled` off by default, and
  `CREATE VECTOR INDEX` fails with a generic `FeatureNotSupported` error
  rather than pointing at the setting to flip. We'd suggest either
  defaulting it on for new clusters or having the error message name the
  cluster setting directly.
- `SET CLUSTER SETTING` cannot run inside a driver's default transactional
  connection (`psycopg`/SQLAlchemy wrap statements in an implicit
  transaction) — it needs `isolation_level="AUTOCOMMIT"` explicitly. Worth
  a callout in the vector-indexing quickstart for anyone driving setup
  from application code rather than the `cockroach sql` shell.
