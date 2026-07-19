# Judging criteria → evidence

A fast-reference map from each official judging criterion to exactly where
in this repo it's satisfied, so it doesn't rely on a judge reading
everything top to bottom. See [`README.md`](README.md) for the full story
and [`docs/architecture.png`](docs/architecture.png) for the diagram.

Every claim below was verified by actually running it against a real
CockroachDB cluster (local Docker and/or CockroachDB Cloud), not just
written and assumed correct — see each script's output in
[`docs/results/`](docs/results/). Several of these runs caught real bugs,
which got fixed, not hidden; noted inline.

## 1. Agentic Memory Design

Does CockroachDB play a meaningful, production-grade role as the agent's
memory layer — more than toy queries?

- **Schema**: `anamnesis/db/schema.sql` — `episodic_memory` (raw events,
  VECTOR(1024)), `semantic_memory` (consolidated beliefs with
  `valid_from`/`valid_to`/`superseded_by`), `memory_audit` (immutable
  write log), `ops_log` (self-observation). Not a single flat
  "memories" table.
- **Quantified vs a naive vector-store baseline**: `scripts/benchmark.py`
  — Anamnesis answers "what do you believe now" correctly **9/12** vs a
  naive vector-store's **2/12**; time-travel **10/12** vs **8/12**. Real
  numbers, saved in [`docs/results/benchmark_output.txt`](docs/results/benchmark_output.txt),
  reproducible with `python3 scripts/benchmark.py`. Uses real local
  embeddings (sentence-transformers), not a hash mock — see the script's
  docstring for exactly what's real vs a documented stand-in for a live
  LLM call.
- **More than toy scale**: `scripts/scale_test.py` loads 5,000 and 20,000
  real embeddings into `CREATE VECTOR INDEX` and measures ANN query
  latency (p99 stayed under 50ms at 20k rows on a single un-tuned local
  node). Results: [`docs/results/scale_test_output.txt`](docs/results/scale_test_output.txt).
  `EXPLAIN ANALYZE` confirms the vector index is actually used (a real
  `• vector search` plan node against `episodic_embedding_idx`, not a
  disguised full scan) — [`docs/results/explain_analyze_vector_index.txt`](docs/results/explain_analyze_vector_index.txt).
- **Two independent kinds of time-travel**, not one: bitemporal
  (`valid_from`/`valid_to`, application-level) side by side with true
  physical `AS OF SYSTEM TIME` MVCC recovery — `scripts/mvcc_timetravel_demo.py`,
  [`docs/results/mvcc_timetravel_demo_output.txt`](docs/results/mvcc_timetravel_demo_output.txt).
- **Memory events as a live stream**, not just a queryable table:
  `scripts/changefeed_demo.py` subscribes to a real `CHANGEFEED FOR
  memory_audit` and proves a live write shows up as a row-level event in
  real time — the primitive you'd wire a downstream dashboard/alert/
  second-agent to. [`docs/results/changefeed_demo_output.txt`](docs/results/changefeed_demo_output.txt).

## 2. Technical Implementation

Quality engineering, correct and safe tool usage.

- **Transactional integrity**: every belief write, its contradiction
  check, and its audit row happen in one retryable unit —
  `anamnesis/db/engine.py` (`run_in_transaction`), used by every mutating
  method in `anamnesis/memory.py`.
- **Multiple real bugs caught by actually testing, not just reading code
  and deciding it looked right**:
  - The first retry engine used a broken generator pattern that crashed
    on a real retry instead of recovering. Fixed; proven fixed by
    `tests/test_memory.py::test_survives_simulated_connection_loss_mid_write`.
  - Under true concurrent writers, "at most one active belief" could be
    violated — found by `scripts/concurrency_test.py`, which fires 10
    simultaneous conflicting writers at the same belief. Fixed with
    `SELECT ... FOR UPDATE` inside the write transaction. The test also
    honestly documents the boundary that fix *can't* close (N
    simultaneous first-time writes on a brand-new topic — a textbook
    phantom-insert case) rather than papering over it.
    [`docs/results/concurrency_test_output.txt`](docs/results/concurrency_test_output.txt).
  - `AS OF SYSTEM TIME` queries failed on a pooled connection
    (`pool_pre_ping`'s own statement pinned an implicit transaction
    timestamp) — fixed with a dedicated AUTOCOMMIT connection,
    invalidated after use.
  - GitHub Actions CI failed on its very first real run
    (`ModuleNotFoundError: No module named 'app'`) because this dev
    environment's editable install happened to leak the repo root onto
    `sys.path` via an older setuptools mechanism, while CI's fresh
    install used the modern, more precise one. Reproduced locally in a
    clean venv before fixing, not just inferred from the CI log.
  - Cloning the repo fresh and following the README's own Quickstart
    verbatim found `make test` targeting a database `make dev-db` never
    created — the kind of thing that silently works on a dev machine with
    leftover state and breaks for anyone starting clean (i.e. every
    judge). Fixed and re-verified from a truly clean database.
  - `app/lambda_handlers/ops_agent.py` called `ccloud cluster describe`
    and `ccloud backup list --cluster <id>` — neither is a real `ccloud`
    subcommand. This was undetected because it had never been run against
    an authenticated `ccloud` session before. Once `ccloud auth` was
    available, ran it for real: found the error, checked `ccloud cluster
    --help`/`ccloud cluster backup --help` for the actual subcommands
    (`cluster info`, `cluster backup list`), fixed it, and confirmed a
    full real run — real cluster metadata and a real backup record
    fetched, summarized, and written to both `ops_log` and the agent's
    own `episodic_memory` on the live cluster.
    [`docs/results/ops_agent_output.txt`](docs/results/ops_agent_output.txt).
- **Real database-level survivability, not just app-level retry**:
  `scripts/node_kill_demo.py` runs against a real 3-node local
  CockroachDB cluster, identifies which node the live connection is
  actually using (not a guess, verified via `node_id`), `docker kill`s
  that exact container mid-write-loop, and shows **30/30 writes still
  landed** — one write paid a ~3.1s failover cost, none were lost.
  [`docs/results/node_kill_demo_output.txt`](docs/results/node_kill_demo_output.txt).
- **All 4 CockroachDB tools used correctly, not just switched on** — see
  the table in `README.md`'s "CockroachDB tools used" section and
  `.claude-skills/README.md` for two skills concretely applied (one
  caught the transaction-retry bug above; one caught a hotspot-risk index,
  fixed in `migrations/versions/0002_hash_shard_audit_index.py`).
- **21 passing tests** (`tests/`), lint-clean (`ruff check .`), verified
  against both a real CockroachDB Cloud cluster and CI (GitHub Actions,
  spinning up a real CockroachDB service container on every push —
  [`.github/workflows/ci.yml`](.github/workflows/ci.yml)), not just local
  Docker.
- **Real packaging, not just an importable folder**: `anamnesis/` builds
  and installs as `anamnesis-crdb` on PyPI — verified with `python3 -m
  build`, `twine check`, and installing the built wheel into a clean venv
  and importing it — and has a LangChain integration
  (`anamnesis.integrations.langchain.AnamnesisChatMessageHistory`,
  targeting LangChain's *current* `BaseChatMessageHistory` API, not the
  removed `BaseMemory`).

## 3. Real-World Impact

- **anamnesis/** is a standalone, pip-installable library
  (`remember/recall/beliefs_asof/consolidate`) — not application code
  tangled with the demo, so it's adoptable by any agent, including
  LangChain-orchestrated ones (see above).
- **Concrete persona**: a customer-support agent that remembers a specific
  customer's history across sessions/tickets — preferences, prior issues,
  and when something changed — rather than a generic "personal assistant"
  (see README's demo persona section). The demo UI has a one-click "Load
  demo data" button seeding this scenario, so the differentiating features
  are visible within seconds, not after ten manually-typed messages.
- **Quantified gap vs. what most teams will ship** (a vector-store-only
  agent): see the benchmark numbers above — this is the difference between
  a support agent that gets a customer's current situation right 75% of
  the time vs 17% of the time.

## 4. Production Readiness

- **Security**: ccloud ops sub-agent uses a dedicated read-only RBAC
  service account, never an org admin key. MCP Server wired read-only for
  judge/agent introspection. The deployed Lambda stack resolves its
  database credential from **AWS Secrets Manager** at cold start, never
  as a plaintext environment variable (`infra/template.yaml`,
  `anamnesis/db/engine.py`, covered by `tests/test_secrets_manager.py`).
  The public demo API supports an optional shared-secret gate
  (`ANAMNESIS_API_TOKEN`) so an unauthenticated Bedrock-backed endpoint
  isn't left open to being farmed by the open internet.
- **Observability**: `memory_audit` logs every WRITE/SUPERSEDE/CONSOLIDATE/
  DECAY/RETRY in the same transaction as the change; a `/metrics`
  endpoint surfaces table row counts, active-belief count, an
  audit-action breakdown (including RETRY visibility), and per-route
  request counts — a real signal beyond a bare health check.
- **Resilience, proven not asserted**: the simulated-connection-loss test,
  the real node-kill demo, and the concurrency test above.
- **Scalability, proven not asserted**: the 20,000-row scale test, backed
  by `EXPLAIN ANALYZE` evidence the index is actually doing the work.
- **CI**: every push/PR runs the full suite against a real CockroachDB
  container, not a mock.
- **Honest limitations documented, not hidden**: see README's "Failure
  modes & honest limitations" — no auth (single demo user), heuristic
  contradiction detection, the phantom-insert concurrency boundary above,
  `ccloud` non-interactive auth mechanism unverified, wide-open demo CORS
  (with the optional token gate as a mitigation).

## 5. Creativity & Originality

- **Two kinds of time-travel** over an agent's own beliefs — bitemporal
  (`valid_from`/`valid_to`) and true physical MVCC (`AS OF SYSTEM TIME`)
  — not just "what's true now," and not just one flavor of "time-travel."
- **Contradiction detection with a supersede chain**, not silent
  overwriting — `superseded_by` links form an auditable history of the
  agent changing its mind, correctly serialized under real concurrent
  writers via row-level locking.
- **Memory as a live stream**: a CDC changefeed turns every memory event
  into something a downstream system can react to in real time, not just
  poll for.
- **An agent that inspects its own infrastructure**: the ccloud ops
  sub-agent checks the health of the CockroachDB cluster hosting its own
  memory and writes what it finds back into that same memory — the agent
  is aware of the substrate it runs on.
- **A benchmark against the obvious alternative**, not just a claim that
  Anamnesis is better than a plain vector store — most entries will
  assert this; few will measure it, and fewer still will stress-test it
  under concurrency and node failure and report the boundaries honestly.

## Reproducing everything above

```bash
# Correctness + unit tests (also runs in CI on every push)
make dev-db && make migrate && make test

# Quantified benchmark vs naive vector store
pip install -e ".[bench]"
make benchmark

# Scale test (5k/20k rows, real embeddings, real vector index)
make scale-test

# Concurrency test (two scenarios, one fixed bug, one honest boundary)
make concurrency-test

# MVCC time-travel demo (bitemporal + physical AS OF SYSTEM TIME)
make mvcc-demo

# CDC changefeed demo (live memory events)
make changefeed-demo

# Real node-kill survivability (3-node cluster)
make multinode-up
make node-kill-demo
```
