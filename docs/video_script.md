# Anamnesis — demo video script (target: 2:45, hard cap 3:00)

Judges are not required to watch past 3:00 and may score from video alone —
every second has to earn its place. Lead with the memory layer, not the
chatbot UI, since Agentic Memory Design is the first tie-break criterion.

Record at 1280x720+ with the terminal font size bumped up. Two windows only:
browser (chat UI) and terminal (SQL shell / script output). No slides.

---

## 0:00–0:15 — Cold open: the thesis (voiceover over the architecture diagram)

> "Most agents bolt a vector store onto memory and call it done. Real memory
> is transactional, temporal, and self-correcting — that's a database
> problem, not an embeddings problem. This is Anamnesis: agent memory built
> directly on CockroachDB."

Show: `docs/architecture.png` full-screen for these 15s.

## 0:15–0:50 — Contradiction + supersede, live (the money shot)

- Chat UI: type as the user, "I'm vegetarian." Agent acknowledges.
- Type: "Book me a table and get me the chicken tikka."
- Agent flags the contradiction, asks for clarification.
- Cut to terminal: `SELECT id, content, valid_from, valid_to, superseded_by
  FROM semantic_memory ORDER BY valid_from;` — show the old belief now has
  `valid_to` set and `superseded_by` pointing at the new row, both written
  in one SERIALIZABLE transaction with an audit row alongside.

> "The old belief isn't overwritten — it's superseded, with a full audit
> trail, atomically."

## 0:50–1:20 — Time-travel over beliefs

- Terminal: run `scripts/mvcc_timetravel_demo.py` (or paste the two
  queries live) showing `beliefs_asof(before)` vs `beliefs_asof(now)`
  returning different, correct answers — Free plan then Pro plan.
- One line contrasting it with `AS OF SYSTEM TIME` showing both physical
  rows still existing in storage, to make clear these are two different,
  deliberate mechanisms, not one accidental one.

> "The agent can answer not just what it believes now, but what it believed
> last week — real time travel, not a changelog bolted on after the fact."

## 1:20–2:00 — Survivability (node-kill demo, live)

- Terminal: run `make node-kill-demo` (or replay the recorded output at
  1.5x if the live run is too slow for pacing) — show writes streaming,
  the `docker kill` line, and writes continuing to land immediately after.
- End on the "30/30 writes succeeded" summary line on screen.

> "Kill the node serving the connection mid-write — the cluster and the
> client both route around it. Every write lands. This is what makes
> memory a database problem: a vector store alone doesn't give you this."

## 2:00–2:25 — CockroachDB tool integration, fast montage

- 5s: `CREATE VECTOR INDEX` in the migration file (vector indexing)
- 5s: MCP client query against `semantic_memory` (managed MCP server)
- 5s: `ccloud cluster info` output feeding the ops-agent's own memory
  (ccloud CLI)
- 5s: `.claude-skills/README.md` — the two real skill-driven fixes
  (Agent Skills repo)

> "Four CockroachDB agent tools, all genuinely load-bearing, not just
> initialized."

## 2:25–2:45 — Close: what it's deployed on, and impact

- Show the live AWS Lambda Function URL responding in the browser (proves
  "deployed on AWS," not just local).
- One sentence on the persona/impact: a customer-support agent that
  correctly recalls plan changes and preferences across sessions instead
  of re-asking — 9/12 vs 2/12 correct recall in our own benchmark.

> "Built on CockroachDB, deployed on AWS Lambda and Bedrock. Anamnesis:
> memory an agent can actually trust."

Cut to black on the repo URL.

---

## Recording checklist
- [ ] AWS deployment live before recording the 2:25 shot
- [ ] `docs/results/*.txt` outputs match what's shown on screen (no staged fakes)
- [ ] Captions/subtitles not required but consider burning in the key numbers
      (30/30, 9/12 vs 2/12) as on-screen text for skimmers
- [ ] Export at <3:00 total, upload to YouTube/Vimeo as **Public** (not Unlisted)
- [ ] Paste the final URL into docs/devpost-submission-draft.md
