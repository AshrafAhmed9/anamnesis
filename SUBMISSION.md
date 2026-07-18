# Judging criteria → evidence

A fast-reference map from each official judging criterion to exactly where
in this repo it's satisfied, so it doesn't rely on a judge reading
everything top to bottom. See [`README.md`](README.md) for the full story
and [`docs/architecture.png`](docs/architecture.png) for the diagram.

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
  latency (p99 stayed under 50ms at 20k rows on a single unTuned local
  node). Results: [`docs/results/scale_test_output.txt`](docs/results/scale_test_output.txt).

## 2. Technical Implementation

Quality engineering, correct and safe tool usage.

- **Transactional integrity**: every belief write, its contradiction
  check, and its audit row happen in one retryable unit —
  `anamnesis/db/engine.py:83` (`run_in_transaction`), used by every
  mutating method in `anamnesis/memory.py` (`remember` L64, `consolidate`
  L267, `decay` L345, `detect_and_resolve_contradiction` L175).
- **A bug we actually caught and fixed, not just avoided**: the first
  version of the retry engine used a broken generator pattern that
  crashed on a real retry instead of recovering — see the commit history
  and `anamnesis/db/engine.py`'s docstring. Proven fixed by
  `tests/test_memory.py:84` (`test_survives_simulated_connection_loss_mid_write`),
  which injects a simulated dropped connection and asserts the write
  still lands with a `RETRY` audit row.
- **Real database-level survivability, not just app-level retry**:
  `scripts/node_kill_demo.py` runs against a real 3-node local
  CockroachDB cluster, identifies which node the live connection is
  actually using (not a guess), `docker kill`s that exact container
  mid-write-loop, and shows **30/30 writes still landed** — one write
  paid a ~3.1s failover cost, none were lost. Output:
  [`docs/results/node_kill_demo_output.txt`](docs/results/node_kill_demo_output.txt).
- **All 4 CockroachDB tools used correctly, not just switched on** — see
  the table in `README.md`'s "CockroachDB tools used" section and
  `.claude-skills/README.md` for two skills concretely applied (one
  caught the transaction-retry bug above; one caught a hotspot-risk index,
  fixed in `migrations/versions/0002_hash_shard_audit_index.py`).
- **12 passing tests** (`tests/`), lint-clean (`ruff check .`), verified
  against a real CockroachDB Cloud cluster, not just local Docker.

## 3. Real-World Impact

- **anamnesis/** is a standalone, pip-installable library
  (`remember/recall/beliefs_asof/consolidate`) — not application code
  tangled with the demo, so it's adoptable by any agent.
- **Concrete persona**: a customer-support agent that remembers a specific
  customer's history across sessions/tickets — preferences, prior issues,
  and when something changed — rather than a generic "personal assistant"
  (see README's demo persona section).
- **Quantified gap vs. what most teams will ship** (a vector-store-only
  agent): see the benchmark numbers above — this is the difference between
  a support agent that gets a customer's current situation right 75% of
  the time vs 17% of the time.

## 4. Production Readiness

- **Security**: ccloud ops sub-agent uses a dedicated read-only RBAC
  service account, never an org admin key (`infra/README.md`). MCP Server
  wired read-only for judge/agent introspection.
- **Observability**: `memory_audit` logs every WRITE/SUPERSEDE/CONSOLIDATE/
  DECAY/RETRY in the same transaction as the change; `/memory/audit` API
  endpoint and the UI's live audit stream surface it.
- **Resilience, proven not asserted**: both the simulated-connection-loss
  test and the real node-kill demo above.
- **Scalability, proven not asserted**: the 20,000-row scale test above.
- **Honest limitations documented, not hidden**: see README's "Failure
  modes & honest limitations" — no auth (single demo user), heuristic
  contradiction detection, `ccloud` non-interactive auth mechanism
  unverified, wide-open demo CORS.

## 5. Creativity & Originality

- **Time-travel over an agent's own beliefs** (`valid_from`/`valid_to` +
  `beliefs_asof()`), not just "what's true now."
- **Contradiction detection with a supersede chain**, not silent
  overwriting — `superseded_by` links form an auditable history of the
  agent changing its mind.
- **An agent that inspects its own infrastructure**: the ccloud ops
  sub-agent checks the health of the CockroachDB cluster hosting its own
  memory and writes what it finds back into that same memory
  (`app/lambda_handlers/ops_agent.py`) — the agent is aware of the
  substrate it runs on.
- **A benchmark against the obvious alternative**, not just a claim that
  Anamnesis is better than a plain vector store — most entries will
  assert this; few will measure it.

## Reproducing everything above

```bash
# Correctness + unit tests
make dev-db && make migrate && make test

# Quantified benchmark vs naive vector store
pip install -e ".[bench]"
python3 scripts/benchmark.py

# Scale test (5k/20k rows, real embeddings, real vector index)
python3 scripts/scale_test.py --rows 20000 --queries 100

# Real node-kill survivability (needs the 3-node cluster)
docker compose -f infra/docker-compose.multinode.yml up -d
docker exec infra-crdb-1-1 ./cockroach init --insecure
python3 scripts/node_kill_demo.py
```
