# Anamnesis — Agentic Memory as a Distributed SQL Problem
### CockroachDB × AWS Hackathon Build Plan (deadline: Aug 19, 2026 IST)

> **One-liner:** An AI agent whose memory is a first-class database citizen — episodic +
> semantic memory with time-travel (`AS OF SYSTEM TIME`), LLM-assisted consolidation and
> forgetting, contradiction detection, and full auditability — built on CockroachDB
> vector indexing + MCP Server, running on AWS Lambda.

**Thesis (say this in the video, the README, and the description):**
Everyone bolts a vector store onto an agent and calls it memory. Real memory is
*transactional, temporal, and self-correcting* — which makes it a database problem,
not an embeddings problem. CockroachDB is the only place where the agent's beliefs,
their history, and their embeddings live in one consistent system.

---

## Why this wins (mapped to the 5 judging criteria)

| Criterion | Anamnesis answer |
|---|---|
| **Agentic Memory Design** | Memory IS the product. Episodic + semantic tables, validity intervals, transactional updates, embeddings in the same DB — "more than toy queries" by construction. |
| **Technical Implementation** | 2 required tools used meaningfully: Distributed Vector Indexing (semantic recall) + MCP Server (agent introspects its own memory). Clean schema, migrations, tests. |
| **Real-World Impact** | Demo persona: a personal ops/research assistant that survives weeks of sessions. The generalizable artifact: a reusable memory layer any agent can adopt. |
| **Production Readiness** | Audit log of every memory write, RBAC-style access separation, graceful LLM-failure fallback, observable (metrics endpoint), documented failure modes. Your existing skillset — this criterion is where you beat other entrants. |
| **Creativity & Originality** | Time-travel over beliefs, decay/forgetting, contradiction resolution — three features nearly no entry will have. |

---

## Architecture

```
User ──► Agent API (FastAPI on Lambda via adapter, or Lambda handlers)
              │
              ▼
        Agent Loop (LLM = Groq/Claude, NOT Bedrock — $0 rule)
              │  writes/reads memory via SQL
              ▼
   ┌─────────────────────────────────────────────┐
   │           CockroachDB Basic (free)           │
   │                                              │
   │  episodic_memory   raw events, timestamped   │
   │  semantic_memory   consolidated beliefs,     │
   │                    valid_from / valid_to     │
   │  memory_audit      every write, who/why      │
   │  + VECTOR column + distributed vector index  │
   └─────────────────────────────────────────────┘
              ▲                       ▲
              │                       │
   Consolidation job          MCP Server (read-only)
   (scheduled Lambda:         → agent answers "what do
   summarize, decay,             I know and when did I
   detect contradictions)        learn it" via MCP
              
   S3: artifact store (conversation exports, consolidation reports)
```

**Required-tool compliance:**
- CockroachDB tools (need 2): **Distributed Vector Indexing** ✅ + **MCP Server** ✅
  (Agent Skills repo optional third if easy — mention in submission if used)
- AWS (need 1): **Lambda** ✅ (agent execution + scheduled consolidation) + **S3** ✅ (artifacts)
- LLM: existing Groq/Claude subscription → total cost ₹0

---

## The Schema (the heart — get this right first)

```sql
CREATE TABLE episodic_memory (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID NOT NULL,
  content TEXT NOT NULL,
  embedding VECTOR(768),
  salience FLOAT NOT NULL DEFAULT 0.5,     -- decays over time
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE semantic_memory (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  belief TEXT NOT NULL,                     -- "user prefers X"
  embedding VECTOR(768),
  confidence FLOAT NOT NULL,
  valid_from TIMESTAMPTZ NOT NULL DEFAULT now(),
  valid_to TIMESTAMPTZ,                     -- NULL = currently believed
  superseded_by UUID,                       -- contradiction chain
  source_episodes UUID[]                    -- provenance
);

CREATE TABLE memory_audit (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  action STRING NOT NULL,                   -- WRITE / CONSOLIDATE / DECAY / SUPERSEDE
  memory_id UUID,
  reason TEXT,
  at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Vector index on both embedding columns. Retrieval = vector similarity **filtered by
`valid_to IS NULL`** — the agent only recalls currently-held beliefs, but can
time-travel with `AS OF SYSTEM TIME` / validity intervals for "what did I believe
last Tuesday."

---

## The 4 demo moments (build the project around these — this IS the video)

1. **Persistence:** talk to agent, kill everything, return "next day" → it remembers
   with provenance ("you told me this on July 24, session 3").
2. **Contradiction:** tell it "I'm vegetarian" → later "grab me chicken tikka" → agent
   notices, asks, supersedes the old belief. Show the `superseded_by` chain in the DB.
3. **Time-travel:** "what did you believe about my diet as of last week?" → old belief
   returned via validity intervals. No other entry will have this.
4. **Forgetting:** run the consolidation Lambda live → low-salience episodics merge
   into one semantic summary, audit rows appear. Show DB before/after.

---

## Build Phases (~4 weeks part-time, DSA stays untouched in the mornings)

### Phase 0 — Accounts + skeleton (1 evening)
- CockroachDB Basic cluster, AWS account + $1 billing alarm, repo with MIT license
  (license visible in About section — submission requirement).
- Connect via psycopg2 / SQLAlchemy (Cockroach is Postgres-wire — your exact stack).

### Phase 1 — Memory core, local (week 1)
- Schema + migrations (Alembic — you know it).
- Write path: message → embed (free embedding model, e.g. Groq/HF) → episodic row.
- Read path: vector search top-k episodic + current semantic beliefs → prompt context.
- Basic agent loop with your existing LLM sub. CLI is fine at this stage.
- **Tests from day one** (pytest) — feeds Production Readiness.

### Phase 2 — The differentiators (week 2)
- Consolidation job: cluster related episodics → LLM summarizes → semantic row,
  sources linked, audit logged. Salience decay + threshold deletion.
- Contradiction detection: new belief vs existing (vector sim + LLM check) →
  supersede with `valid_to` + `superseded_by`.
- Time-travel query endpoint.

### Phase 3 — AWS + MCP (week 3)
- Port agent + consolidation to Lambda (consolidation on an EventBridge schedule).
- S3 for conversation exports / consolidation reports.
- Wire the CockroachDB MCP Server (config snippet from Cloud Console): a "memory
  introspection" mode where the agent (or judge!) queries memory via MCP read-only.
  Judges can literally inspect the memory layer themselves — great judging UX.

### Phase 4 — Frontend + polish (week 4)
- Simple React UI (you have the skillset): chat pane + **live memory panel** showing
  beliefs, validity, contradictions, audit stream. The memory panel is the star.
- Architecture diagram (do the optional item — free points).
- README: thesis, setup, the 4 demo moments, failure modes documented honestly
  (your README style is already exactly what this criterion wants).
- **3-min video:** 20s thesis → the 4 demo moments → 20s architecture. Script it,
  record twice, done. Public on YouTube.
- Deploy demo URL (required): Lambda function URL or lightweight host.

---

## Scope guards (violating these = the project eats your DSA time)

- **No auth system.** Single demo user. (Mention multi-tenancy as documented future work.)
- **No fancy UI.** One page, two panels. Function over beauty.
- **No Bedrock/SageMaker.** Costs money, not required.
- **No graph memory / knowledge graphs.** Validity intervals + supersede chain is enough.
- **One embedding model, one LLM.** Zero model comparisons.
- **If a week slips:** cut Phase 4 UI to bare minimum, never cut Phase 2 — the
  differentiators are the entry.

## Timebox
- Fixed budget: ~2 hrs/evening + weekends. DSA mornings are untouchable.
- Hard stop on polish Aug 16; submit Aug 17 (buffer before the Aug 19 IST deadline).

## Submission checklist (from official rules)
- [ ] Public repo, MIT license visible in About
- [ ] README: setup, deps, run instructions
- [ ] Functional demo URL
- [ ] <3-min public YouTube video showing the memory layer at work
- [ ] Text description of features
- [ ] Declare tools: CockroachDB Vector Indexing + MCP Server; AWS Lambda + S3
- [ ] Optional: architecture diagram (do it), tool feedback (do it — 5 min, goodwill)
