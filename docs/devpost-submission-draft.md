# Devpost submission draft — Anamnesis

Copy/paste ready. Fill in the ⬜ placeholders once the demo URL and video exist.

---

## Project name
Anamnesis

## Tagline
Agentic memory as a distributed SQL problem — transactional, temporal, self-correcting memory on CockroachDB + AWS Bedrock.

## Links
- **GitHub repo:** https://github.com/AshrafAhmed9/anamnesis
- **Demo URL:** https://5y52iimwosyg62vshke43wivtu0wspsd.lambda-url.us-east-1.on.aws/ (live Lambda Function URL — try `POST /demo/seed` then `POST /chat`, or `GET /metrics`)
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
- For any belief, the agent can answer **"why do you believe this?"** —
  reconstructing the exact conversation turns it was formed from (evidence),
  the belief it replaced and the one that replaced it (lineage), and its full
  audit history. A similarity score is not a reason; this is the trust and
  explainability question a vector store structurally cannot answer.
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
being true, what the agent believed at a point in time, *why* it holds a
belief and on what evidence, or guarantee an update and its audit trail
land together under a mid-write failure. Those require transactions,
validity intervals, and one consistent source of truth — which is what
CockroachDB is for.

## CockroachDB tools used (how)

- **Distributed Vector Indexing** — `CREATE VECTOR INDEX` on both
  `episodic_memory.embedding` and `semantic_memory.embedding` (1024-dim,
  Titan v2). All recall and contradiction-detection is ANN search over
  these indexes.
- **Managed MCP Server** — wired for read-only introspection; judges (or the
  agent itself) can query `semantic_memory`/`memory_audit` directly via any
  MCP client, no code required.
- **ccloud CLI (agent-ready)** — a scheduled sub-agent runs
  `ccloud cluster info` / `ccloud cluster backup list` against the cluster
  hosting its own memory, summarizes cluster health with the LLM, and
  writes the observation back into its own memory. Uses a dedicated
  least-privilege (`CLUSTER_DEVELOPER`) RBAC service account, never the
  org admin key. Verified with a real end-to-end run against the live
  cluster.
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

**Note on Bedrock at judging time:** Bedrock's `InvokeModel` is currently
blocked account-wide on the AWS account this was built with ("Operation
not allowed" — confirmed with AWS Support, case 178439660900442, as an
account-history gate on a brand-new account, not a code or config issue).
The full Claude + Titan integration is written and exercised against the
real Bedrock request/response shape (`anamnesis/agent/bedrock.py`), and
the live deployment above runs on the same deterministic mock-LLM fallback
already used honestly throughout local dev and CI
(`ANAMNESIS_MOCK_LLM=1`) — every other part of the stack (CockroachDB
transactions, retries, contradiction/supersede, time-travel, Lambda,
EventBridge, S3, Secrets Manager) is fully real and live. Flipping Bedrock
on once access clears is a one-line redeploy (`MockLlm=0`), not a rebuild.

## Architecture diagram
`docs/architecture.png` in the repo (also embedded in the README).

## Tool feedback for Cockroach Labs (optional field)
See `.claude-skills/README.md` and `infra/README.md` in the repo — includes
a real rough edge found (`feature.vector_index.enabled` is off by default on
a fresh cluster, with a generic `FeatureNotSupported` error rather than a
pointer to the setting) and a driver-level gotcha (`SET CLUSTER SETTING`
needs `AUTOCOMMIT` isolation, not the default transactional connection).
