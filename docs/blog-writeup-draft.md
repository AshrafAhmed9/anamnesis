# Draft blog writeup — Anamnesis
Not published. Draft for a dev.to / personal-site post, linkable from the Devpost submission.
Publishing needs your account — this is ready to paste once you pick a platform.

---

## Title
Agentic memory is a database problem, not an embeddings problem

## Subtitle
What I learned building a memory layer for AI agents on CockroachDB — including the bugs I found by actually testing under concurrency and failure, not just by writing code that looked right.

---

## Draft body

Every agent framework ships a "memory" feature that's really just a vector store with a friendly name: embed the conversation, retrieve the top-k nearest neighbors, stuff them in the prompt. It works for demos. It falls apart the moment you ask it a question that isn't "find similar text" — like *"what did you believe about my diet last week?"* or *"is this the current answer, or one I already corrected you on?"*

I built [Anamnesis](https://github.com/AshrafAhmed9/anamnesis) for the CockroachDB × AWS Hackathon to test a specific claim: that real agent memory needs a database's guarantees — transactions, validity intervals, isolation — not just a nearest-neighbor index. Here's what I actually found building and stress-testing it.

### The measurement, not just the claim

Instead of asserting Anamnesis beats a naive vector store, I built the naive baseline and measured both against 12 scenarios where a belief changes ("I'm vegetarian" → "actually I eat meat now"). The naive baseline got the *current* answer right 2/12 times — because nearest-neighbor search has no concept of "this statement is stale." Anamnesis got it right 9/12, using the same embeddings, same LLM judge, same conditions. The full methodology (including the honest lower-bound caveat — I used a rule-based contradiction judge, not a live LLM, since AWS Bedrock access was gated behind a new-account verification hold for most of the build) is in the repo.

### Concurrency found a real bug

I assumed "at most one active belief per topic" was already correct, since each write happens in a CockroachDB SERIALIZABLE transaction. Then I wrote a test that fires 10 concurrent writers at the same belief — and watched all 10 "succeed" with 10 different beliefs simultaneously active. The bug: I'd moved the LLM call outside the transaction (correctly — you don't want a retry re-issuing an API call), but that meant the "is this a contradiction" check read a stale snapshot that never saw sibling writers' concurrent inserts.

The fix was `SELECT ... FOR UPDATE` inside the write transaction, re-scanning for *all* currently-active conflicting beliefs, not just the one candidate read before the transaction opened. That closed the realistic case (multiple writers correcting an *existing* belief). It didn't close the harder case — N simultaneous *first* writes on a brand-new topic, a textbook phantom-insert/write-skew scenario that `FOR UPDATE` structurally can't prevent, since there's nothing to lock yet. I documented that boundary rather than pretending it away.

### Killing a real database node, on camera

The easy version of a "resilience" demo is asserting your code retries on failure. I wanted to see it happen: a real local 3-node CockroachDB cluster, a script that identifies which specific container is serving the live connection (not a guess — verified via `node_id`), then `docker kill`s it mid-write-loop. 30/30 writes survived. One write paid a ~3.1 second failover cost as the connection detected the dead node and failed over. Nothing was lost.

### What this adds up to

None of this is exotic engineering. It's the standard toolkit — transactions, isolation levels, validity intervals, retry logic — applied to a problem (agent memory) that the industry has mostly been solving with vector search alone. The interesting part wasn't writing the code; it was that testing it for real (concurrency, failure injection, a naive baseline for comparison) surfaced three genuine bugs I wouldn't have found by just reading the code and deciding it looked right.

Repo, video, and full writeup: [github.com/AshrafAhmed9/anamnesis](https://github.com/AshrafAhmed9/anamnesis)

---

## Suggested platforms
- dev.to (large AI/database audience, good for hackathon visibility)
- Your own site if you have one
- Cross-post to Hashnode/Medium if you want reach beyond dev.to

## Suggested tags (dev.to style)
`#cockroachdb` `#ai` `#databases` `#hackathon` `#python`
