# CockroachDB Agent Skills used in this project

This project's development workflow used skills from the
[CockroachDB Agent Skills Repo](https://github.com/cockroachdb/agent-skills)
(open source) during schema design and query tuning — specifically the
schema-design and vector-indexing skills, loaded into Claude Code while
authoring `anamnesis/db/schema.sql` and the ANN queries in
`anamnesis/memory.py`.

To reproduce: clone the skills repo and point your MCP-compatible client
(Claude Code, Cursor, etc.) at it per its README, then work in this repo as
normal — the skills activate automatically on CockroachDB-related prompts
(e.g. "design a vector index for embedding recall").

**Tool feedback (submission's optional item):** the schema-design skill's
guidance on `CREATE VECTOR INDEX` usage was accurate and saved a debugging
cycle; we did hit one real rough edge worth flagging to Cockroach Labs —
`feature.vector_index.enabled` is off by default on a fresh cluster and the
skill/docs we found didn't call that out, which produced a
`FeatureNotSupported` error on first migration. We'd suggest surfacing that
cluster setting requirement (or defaulting it on) directly in the vector
index quickstart docs.
