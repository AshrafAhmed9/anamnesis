# Devpost submission draft — Anamnesis

Copy/paste ready. Fill in the ⬜ placeholders once the demo URL and video exist.

---

## Project name
Anamnesis

## Tagline
Agentic memory as a distributed SQL problem — transactional, temporal, self-correcting memory on CockroachDB + AWS Bedrock.

## Links
- **GitHub repo:** https://github.com/AshrafAhmed9/anamnesis
- **Demo URL:** ⬜ (Lambda Function URL after `sam deploy`)
- **Video:** ⬜ (YouTube/Vimeo link, public, ≤3 min)

## Text description

Everyone bolts a vector store onto an agent and calls it memory. Real memory is
transactional, temporal, and self-correcting — which makes it a database
problem, not an embeddings problem. Anamnesis puts an agent's beliefs, their
history, and their embeddings in one consistent, distributed SQL system:
CockroachDB.

**What it does:**
- Stores raw conversation events (episodic memory) and consolidated beliefs
  (semantic memory) separately, each with vector embeddings for recall.
- Beliefs carry `valid_from`/`valid_to` validity intervals, so the agent can
  answer not just "what do you believe now" but "what did you believe last
  week" — real time-travel over its own beliefs.
- When a new statement contradicts an existing belief, the agent detects it
  (vector similarity + LLM judgment), supersedes the old belief instead of
  silently overwriting it, and keeps a full `superseded_by` audit chain.
- A scheduled job folds low-salience episodic chatter into durable semantic
  beliefs and decays what's no longer relevant — memory that forgets on
  purpose, not just accumulates forever.
- Every write — episode, belief, supersede, consolidation, decay, retry — is
  logged to an immutable audit table in the *same* CockroachDB SERIALIZABLE
  transaction as the change it records, so memory state and its audit trail
  can never diverge.
- Writes survive both contention (SQLSTATE 40001) and a lost/killed
  connection mid-write: the whole unit of work is retried from scratch, not
  just the commit — covered by an automated test that simulates a dropped
  connection and proves the write still lands.
- A ccloud CLI-driven sub-agent periodically inspects the health of its own
  CockroachDB cluster and writes what it finds back into its own memory —
  the agent is aware of the infrastructure its memory runs on.

**Why this matters:** a vector store can tell you "these 5 memories are
similar." It can't tell you which of them is still true, when it stopped
being true, what the agent believed at a point in time, or guarantee an
update and its audit trail land together under a mid-write failure. Those
require transactions, validity intervals, and one consistent source of
truth — which is what CockroachDB is for.

## CockroachDB tools used (how)

- **Distributed Vector Indexing** — `CREATE VECTOR INDEX` on both
  `episodic_memory.embedding` and `semantic_memory.embedding` (1024-dim,
  Titan v2). All recall and contradiction-detection is ANN search over
  these indexes.
- **Managed MCP Server** — wired for read-only introspection; judges (or the
  agent itself) can query `semantic_memory`/`memory_audit` directly via any
  MCP client, no code required.
- **ccloud CLI (agent-ready)** — a scheduled sub-agent runs
  `ccloud cluster describe` / `ccloud backup list` against the cluster
  hosting its own memory, summarizes cluster health with the LLM, and
  writes the observation back into its own memory. Uses a dedicated
  read-only RBAC service account, never the org admin key.
- **Agent Skills Repo** — installed the real, open-source
  `cockroachlabs/cockroachdb-skills` and concretely applied two skills
  during development: `designing-application-transactions` caught a real
  bug (an LLM call living inside a retryable transaction, meaning a retry
  would re-issue the LLM call); `cockroachdb-sql` flagged a hotspot-risk
  index on a monotonically increasing timestamp column, which got
  hash-sharded. Full writeup: `.claude-skills/README.md` in the repo.

## AWS services used (how)

- **Amazon Bedrock** — Claude for reasoning, contradiction judgment, and
  consolidation summarization; Amazon Titan Text Embeddings v2 for all
  embeddings.
- **AWS Lambda** — the chat API (Function URL), the scheduled consolidation
  job, and the scheduled ops sub-agent all run as Lambda functions
  (arm64/Graviton).
- **Amazon EventBridge** — schedules the consolidation Lambda (every 30
  min) and the ops-agent Lambda (hourly).
- **Amazon S3** — stores consolidation reports and conversation exports.

## Architecture diagram
`docs/architecture.png` in the repo (also embedded in the README).

## Tool feedback for Cockroach Labs (optional field)
See `.claude-skills/README.md` and `infra/README.md` in the repo — includes
a real rough edge found (`feature.vector_index.enabled` is off by default on
a fresh cluster, with a generic `FeatureNotSupported` error rather than a
pointer to the setting) and a driver-level gotcha (`SET CLUSTER SETTING`
needs `AUTOCOMMIT` isolation, not the default transactional connection).
