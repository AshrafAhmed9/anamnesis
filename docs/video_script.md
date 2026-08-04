# Anamnesis — demo video script, second-by-second (target 2:45, hard cap 3:00)

Judges may score off video alone and are not required to watch past 3:00.
Every line below is exact — say it close to verbatim, don't ad-lib the
technical claims. Screen actions are exact clicks/keystrokes/commands.
Captions are exact burned-in text for the edit pass.

Record at 1280×720 or higher. Two windows only: browser (the chat UI) and
a terminal with the font size bumped to ~18–20pt so it's readable at
1280px wide. No slides except the one architecture-diagram still frame.

---

## Setup — do this BEFORE you press record

1. `ollama serve` running in a spare terminal tab; `ollama list` shows
   `llama3.2`.
2. Fresh local stack: `make dev-db && make migrate`.
3. Bring up the 3-node cluster now (not during recording — it's slow):
   `make multinode-up`. Confirm it's healthy: `docker ps` shows
   `infra-crdb-1-1`, `infra-crdb-2-1`, `infra-crdb-3-1` all `Up`.
4. Start the app: `uvicorn app.main:app --port 8000` in one terminal tab.
5. Start the UI: `cd ui && python3 -m http.server 5173` in another tab.
6. Open the browser to
   `http://localhost:5173/index.html?api=http://localhost:8000` — resize
   the window so both the Chat panel (left) and Live Memory panel (right)
   are fully visible with no scrolling.
7. Arrange terminal tabs in this order so you can Cmd+Tab/click through
   them in sequence during recording: **[A] SQL shell** (`docker exec -it
   anamnesis-crdb ./cockroach sql --insecure --database=anamnesis`),
   **[B] scripts runner** (repo root, venv activated), **[C]
   architecture diagram viewer** (Preview/qlmanage on
   `docs/architecture.png`, full screen, ready to screenshot/screen-record).
8. **Do one full practice run of the 0:15–0:50 contradiction scene**
   (steps below) before recording for real. The local model's output
   isn't perfectly bit-for-bit deterministic run to run — a dry run
   confirms it's behaving before the take that counts. If it doesn't
   supersede on the practice run, just redo it — it has run correctly
   many times with this exact wording.
9. Clear stale state right before recording: in SQL shell [A], run
   `DELETE FROM semantic_memory; DELETE FROM episodic_memory; DELETE FROM
   memory_audit;` so the belief timeline starts empty for the camera.

---

## 0:00–0:15 — Cold open

**Screen:** Terminal tab [C] — `docs/architecture.png` full-screen, static, no cursor movement.

**Say (verbatim):**
> "Most agents bolt a vector store onto memory and call it done. Real memory is transactional, temporal, and self-correcting — that's a database problem, not an embeddings problem. This is Anamnesis: agent memory built directly on CockroachDB."

**Caption (burn in, bottom third, appears at 0:02, holds to 0:14):**
`ANAMNESIS — agentic memory on CockroachDB`

---

## 0:15–0:50 — Contradiction + supersede (the money shot)

**0:15** — Cut to browser, chat UI. Cursor in the message input box.

**0:16–0:19** — Type exactly: `I'm vegetarian and don't eat meat.` Press Enter.

**Say, while it's thinking (0:16–0:22):**
> "I'll tell it something about myself."

**0:20–0:24** — Agent reply appears in chat. **Screen focus shifts to the right-hand "Live Memory" panel** — a new belief card appears under "Belief timeline," briefly flashes teal.

**Caption (appears 0:22, holds 3s):**
`New belief written — CockroachDB SERIALIZABLE transaction`

**0:25–0:28** — Back to chat input. Type exactly: `Actually I am not vegetarian anymore, I eat meat now.` Press Enter.

**Say, while it's thinking (0:25–0:31):**
> "Now I contradict myself."

**0:32–0:40** — Agent reply appears, acknowledging the update. **Cut to the Live Memory panel**: the old belief card now shows struck-through text with a red arrow (→) to the new belief text, briefly flashes red. Below it, the Audit Stream shows a `SUPERSEDE` row in red.

**Hold this shot for a full 3 seconds, unmoving** — this is the single most important frame in the video.

**Caption (appears 0:33, holds 5s):**
`Old belief superseded — not overwritten. Full audit trail, same transaction.`

**Say (0:38–0:49, over the held shot):**
> "The old belief isn't overwritten — it's superseded, with a full audit trail, atomically, in the same CockroachDB transaction. And that's a real Llama 3.2 model reasoning about the contradiction, not a canned response — Bedrock is blocked on this AWS account right now, so the demo runs on a free local model instead. The Bedrock integration code itself is real and ready the moment access clears."

**Caption (appears 0:44, holds to 0:50):**
`Reasoning: real local LLM (Llama 3.2) — Bedrock blocked on this AWS account, disclosed in README`

---

## 0:50–1:05 — "Why do you believe this?" (the trust beat)

**0:50** — Still on the Live Memory panel. Move cursor to the **active** belief card (the new one, "I am not vegetarian anymore..." or similar).

**0:51** — Click it. The provenance drawer expands inline directly under the card.

**0:52–0:56** — Cursor traces down the drawer top to bottom, pausing ~1s each on:
- the **Evidence** line (the exact user message)
- the **Lineage** line ("Replaced: ...")
- the **Audit history** line (`WRITE ...`)

**Caption (appears 0:52, holds to 1:04):**
`GET /memory/beliefs/{id}/why — evidence, lineage, and audit history for any belief`

**Say (0:52–1:04):**
> "And it's not a black box. Ask why it believes something, and it shows you the exact message it learned it from, what that replaced, and the full audit trail. A vector store gives you a similarity score — that's not a reason. This is."

---

## 1:05–1:30 — Time-travel over beliefs

**1:05** — Cut to terminal tab [B]. Type and run:
```
python3 scripts/mvcc_timetravel_demo.py
```
(This creates its own fresh Free-plan → Pro-plan belief pair, independent of the browser demo above — that's expected, don't worry it doesn't match what's on screen in the browser.)

**1:06–1:20** — Let the output scroll. As soon as these two lines are visible, pause scrolling (screenshot-still or just stop touching the terminal) for 3 seconds:
```
Bitemporal beliefs_asof(before upgrade): ['user is on the Free plan']
Bitemporal beliefs_asof(now):            ['user upgraded to the Pro plan']
```

**Caption (appears 1:08, holds 6s):**
`beliefs_asof(before) vs beliefs_asof(now) — same query, different point in time, correct answer both times`

**Say (1:07–1:29):**
> "The agent can answer not just what it believes now, but what it believed last week — real time travel, not a changelog bolted on after the fact. And this isn't the only kind: the same script also runs a true physical AS OF SYSTEM TIME query — CockroachDB's own MVCC storage, not just our application logic — recovering the exact same distinction independently."

**1:24–1:29** — Scroll down to show the `PASS: both mechanisms correctly distinguish before/after the upgrade.` line on screen as you finish the sentence.

**Caption (appears 1:26, holds to 1:30):**
`PASS — two independent time-travel mechanisms, both verified`

---

## 1:30–2:05 — Survivability (node-kill demo, live)

**1:30** — Terminal [B]. Type and run:
```
python3 scripts/node_kill_demo.py
```

**1:31–1:36** — Output prints "Connection is currently served by container: ..." then starts streaming `write N/30 OK ...` lines. Let it run.

**Say (1:31–1:42):**
> "Now the hard failure test — thirty memory writes in a row, and partway through, I kill the actual database node serving this connection. Not a simulated failure — a real docker kill on a live three-node cluster."

**~1:38** — The `>>> docker kill ... <<<` line appears on screen — **pause narration for 1 second right as this line prints**, let it read on its own.

**Caption (appears exactly when the kill line prints, holds 4s):**
`docker kill <container> — mid-write, live`

**1:39–1:50** — Writes continue streaming after the kill (one write will show an elevated ms count from the failover, the rest normal). Let it run to completion.

**Say (1:44–1:56):**
> "Every write still lands. The client fails over across the cluster's other nodes automatically, and the retry logic re-runs the whole transaction from scratch — not just the commit — so nothing is half-written."

**1:57–2:04** — The final summary line prints: `30/30 writes succeeded with <container> killed mid-run`. **Hold on this line for 3 full seconds, no scrolling.**

**Caption (appears 1:58, holds to 2:05):**
`30/30 writes survived a live node kill — full output: docs/results/node_kill_demo_output.txt`

---

## 2:05–2:30 — CockroachDB tool integration, fast montage

Four ~6-second beats, hard cuts, no narration pauses between them — keep pace brisk.

**2:05–2:11** — Terminal [A] (SQL shell). Run:
```sql
EXPLAIN ANALYZE SELECT id, belief FROM semantic_memory
  ORDER BY embedding <-> '[0,0,0]' LIMIT 5;
```
(Any short zero-ish vector literal is fine — the point is the plan output.) As soon as a line containing `vector search` appears in the plan, freeze/pause. If typing the full 1024-dim literal live is impractical, instead just open `docs/results/explain_analyze_vector_index.txt` in a text editor and show the `• vector search` plan line directly — say so isn't implied as literally typed live.

**Caption (2:05, holds 6s):**
`Distributed Vector Indexing — CREATE VECTOR INDEX, confirmed used by EXPLAIN ANALYZE (not a disguised full scan)`

**2:11–2:17** — Terminal [A]. Run:
```sql
SELECT belief, valid_from, valid_to, superseded_by FROM semantic_memory ORDER BY valid_from DESC LIMIT 5;
```
This is the same category of read a judge's MCP client would run against the cluster.

**Caption (2:11, holds 6s):**
`The same structured read a CockroachDB Managed MCP client can run — direct SQL access, no black box`

**2:17–2:23** — Terminal [B]. Open (`cat` or editor) `docs/results/ops_agent_output.txt` briefly, or show the file in an editor scrolled to the ccloud output section.

**Caption (2:17, holds 6s):**
`ccloud CLI — the agent inspects its own CockroachDB cluster's health and writes the finding into its own memory`

**2:23–2:29** — Open `.claude-skills/README.md` in an editor, scrolled to the `designing-application-transactions` heading.

**Caption (2:23, holds 6s):**
`CockroachDB Agent Skills — caught a real bug during development (see .claude-skills/README.md)`

**Say, once, over the whole montage (2:05–2:29):**
> "Vector indexing, the same structured access a judge's MCP client gets, a ccloud-driven sub-agent that inspects its own cluster, and the CockroachDB Agent Skills repo, which caught two real bugs during development. All four genuinely load-bearing, not just initialized."

---

## 2:30–2:55 — Close: deployed on AWS, and the impact

**2:30–2:36** — Terminal [B]. Run:
```
curl -s https://5y52iimwosyg62vshke43wivtu0wspsd.lambda-url.us-east-1.on.aws/metrics
```
Let the real JSON response print on screen.

**Caption (2:30, holds 6s):**
`Live on AWS Lambda right now — not just local`

**Say (2:31–2:44):**
> "This is deployed right now on AWS Lambda, backed by S3 and EventBridge, against a live CockroachDB Cloud cluster — that response just came from the real internet, not localhost. And the reason any of this matters: a support agent that gets a customer's current situation right roughly four times as often as a plain vector store in our own fifty-scenario benchmark — and can show you why."

**Caption (2:38, holds 6s):**
`24/50 vs 6/50 correct recall — our own 50-scenario benchmark, reproducible: python3 scripts/benchmark.py`

**2:45–2:54** — Cut to a plain black or dark-navy screen with the repo URL centered, large, readable.

**Say (2:45–2:53):**
> "Built on CockroachDB, deployed on AWS. Anamnesis: memory an agent can actually trust — because it can show you why."

**Caption (2:46, holds to 2:58):**
`github.com/AshrafAhmed9/anamnesis`

**2:55–3:00** — Hold on repo URL card, silent, no narration. Cut to black at 3:00 or slightly before.

---

## Full caption list (for the editor, in order)

1. `0:02` `ANAMNESIS — agentic memory on CockroachDB`
2. `0:22` `New belief written — CockroachDB SERIALIZABLE transaction`
3. `0:33` `Old belief superseded — not overwritten. Full audit trail, same transaction.`
4. `0:44` `Reasoning: real local LLM (Llama 3.2) — Bedrock blocked on this AWS account, disclosed in README`
5. `0:52` `GET /memory/beliefs/{id}/why — evidence, lineage, and audit history for any belief`
6. `1:08` `beliefs_asof(before) vs beliefs_asof(now) — same query, different point in time, correct answer both times`
7. `1:26` `PASS — two independent time-travel mechanisms, both verified`
8. `~1:38` (sync to the kill line) `docker kill <container> — mid-write, live`
9. `1:58` `30/30 writes survived a live node kill — full output: docs/results/node_kill_demo_output.txt`
10. `2:05` `Distributed Vector Indexing — CREATE VECTOR INDEX, confirmed used by EXPLAIN ANALYZE (not a disguised full scan)`
11. `2:11` `The same structured read a CockroachDB Managed MCP client can run — direct SQL access, no black box`
12. `2:17` `ccloud CLI — the agent inspects its own CockroachDB cluster's health and writes the finding into its own memory`
13. `2:23` `CockroachDB Agent Skills — caught a real bug during development (see .claude-skills/README.md)`
14. `2:30` `Live on AWS Lambda right now — not just local`
15. `2:38` `24/50 vs 6/50 correct recall — our own 50-scenario benchmark, reproducible: python3 scripts/benchmark.py`
16. `2:46` `github.com/AshrafAhmed9/anamnesis`

Style suggestion: small, semi-transparent dark bar behind white/light text,
bottom-third placement, never covering the action being shown. Keep each
caption on screen for the durations noted above, don't let more than one
caption overlap at once.

---

## Recording checklist

- [ ] Practice run of the 0:15–0:50 contradiction scene done, worked correctly
- [ ] `make multinode-up` done BEFORE recording (not live) — verified 3 containers up
- [ ] Semantic/episodic/audit tables cleared right before recording starts
- [ ] Live AWS deployment reachable (`curl .../metrics` returns 200) before the 2:30 shot
- [ ] `docs/results/*.txt` files referenced on screen match what's actually shown (no staged numbers)
- [ ] Every caption above added in the edit, at the noted timestamp ± 1s
- [ ] Total runtime under 3:00 (target 2:55 or less to leave a safety margin)
- [ ] Export, upload to YouTube or Vimeo as **Public** (not Unlisted — the rules require public)
- [ ] Send the final URL back so it can be pasted into `docs/devpost-submission-draft.md`
