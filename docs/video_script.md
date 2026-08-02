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

Use this exact wording — stress-tested for reliable, repeatable triggering
(verified 3/3 identical runs; a paraphrase with less word overlap with the
original belief can miss the similarity threshold entirely with the local
demo model — see README's honest-limitations section, so don't ad-lib this
one on camera):

- Chat UI: type as the user, **"I'm vegetarian and don't eat meat."**
  Agent acknowledges; watch the right-hand "Live Memory" panel — a new
  belief card appears (briefly flashes teal).
- Type: **"Actually I am not vegetarian anymore, I eat meat now."**
  Agent replies acknowledging the update. In the memory panel: the old
  belief card now shows struck-through text with a red arrow (→) pointing
  to the new belief text, and briefly flashes red. The audit stream below
  it shows a `SUPERSEDE` row (also red) referencing the new belief's ID.
- Hover/point at the struck-through belief + arrow for a beat — this *is*
  the demo moment, make sure it's clearly on screen and not a fast cut.
- Optional: cut to terminal running the same exchange via
  `python3 -c "..."` (see anamnesis/agent/loop.py's Agent) and a
  `SELECT belief, valid_to, superseded_by FROM semantic_memory ORDER BY
  valid_from;` for the judges who want to see it isn't UI trickery.

> "The old belief isn't overwritten — it's superseded, with a full audit
> trail, atomically, in the same CockroachDB transaction. And that's a
> real Llama 3.2 model reasoning about the contradiction, not a canned
> response — Bedrock is blocked on this AWS account for now, so the demo
> runs on a free local model instead; the integration code for Bedrock
> itself is real and ready the moment access clears."

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

## Before you hit record

1. `ollama serve` running, `ollama list` shows `llama3.2` (already pulled
   as of this writing) — this is what powers real reasoning in the 0:15
   scene, no AWS/API key needed.
2. `make dev-db && make migrate` for a clean local CockroachDB, or point
   at the live AWS deployment for extra credibility on the closing shot.
3. `uvicorn app.main:app --port 8000` + `cd ui && python3 -m http.server
   5173`, open `http://localhost:5173/index.html?api=http://localhost:8000`.
4. **Do one full practice run of the 0:15 contradiction scene before
   recording for real.** The exact wording in that section is stress-
   tested and reliable, but a local 3B model's output isn't perfectly
   bit-for-bit deterministic run to run (verified: same input,
   temperature=0, occasionally still produces a slightly different
   paraphrase) — a dry run confirms it's behaving before the take that
   counts, and costs under a minute.

## Recording checklist
- [ ] Practice run of the 0:15 contradiction scene done, worked correctly
- [ ] AWS deployment live before recording the 2:25 shot
- [ ] `docs/results/*.txt` outputs match what's shown on screen (no staged fakes)
- [ ] Captions/subtitles not required but consider burning in the key numbers
      (30/30, 9/12 vs 2/12) as on-screen text for skimmers
- [ ] Export at <3:00 total, upload to YouTube/Vimeo as **Public** (not Unlisted)
- [ ] Paste the final URL into docs/devpost-submission-draft.md
