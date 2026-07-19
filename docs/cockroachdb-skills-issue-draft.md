Draft GitHub issue for cockroachlabs/cockroachdb-skills.
NOT POSTED — needs your go-ahead (posts publicly under your GitHub identity).
To post: `gh issue create --repo cockroachlabs/cockroachdb-skills --title "..." --body-file this-file-minus-this-header`

---

**Title:** Vector index quickstart: `feature.vector_index.enabled` gotcha + AS OF SYSTEM TIME driver note

**Body:**

Found these while building an agentic-memory project on CockroachDB for the CockroachDB × AWS Hackathon, using the `cockroachdb-sql` and `designing-application-transactions` skills from this repo. Both are small, concrete, and reproducible — sharing in case they're useful feedback for the skills content or docs.

**1. `feature.vector_index.enabled` is off by default on a fresh cluster**

`CREATE VECTOR INDEX` on a brand-new cluster (both CockroachDB Cloud Basic and a local `cockroach start-single-node`) fails with:

```
psycopg.errors.FeatureNotSupported: vector indexes are not enabled;
enable with the feature.vector_index.enabled cluster setting
```

The error message itself does point at the fix, so this isn't a dead end — but the `cockroachdb-sql` skill's vector-index guidance didn't call this out ahead of time, so it cost a debugging cycle to discover only after the `CREATE VECTOR INDEX` statement failed. Suggest either defaulting it on for new clusters, or having the vector-indexing skill/quickstart docs mention the setting explicitly before the `CREATE VECTOR INDEX` example.

Fix: `SET CLUSTER SETTING feature.vector_index.enabled = true;`

**2. `SET CLUSTER SETTING` needs an explicit AUTOCOMMIT connection when driving setup from application code**

Running `SET CLUSTER SETTING ...` through a SQLAlchemy/psycopg connection (the default transactional isolation level) fails:

```
psycopg.errors.SerializationFailure: SET CLUSTER SETTING cannot be used
inside a multi-statement transaction
```

Obvious once you know it, but non-obvious coming from application code rather than the `cockroach sql` shell (which handles this transparently). Worth a one-line callout in any guidance aimed at driving cluster setup from an app/ORM rather than the shell — e.g. `engine = create_engine(url, isolation_level="AUTOCOMMIT")` for SQLAlchemy.

**3. (Related, same root cause) `AS OF SYSTEM TIME` + connection pooling**

Separately — not sure if in scope for this repo's skills, flagging in case: a pooled connection whose first statement is an implicit ping (e.g. SQLAlchemy's `pool_pre_ping`) can pin an implicit transaction timestamp that then conflicts with an explicit `AS OF SYSTEM TIME` on the next statement over that same connection (`FeatureNotSupported: inconsistent AS OF SYSTEM TIME timestamp`). Fixed the same way — a dedicated AUTOCOMMIT connection for AS-OF-SYSTEM-TIME queries, invalidated after use rather than returned to the pool. Might be worth a note in any application-transaction guidance that touches historical/AS-OF-SYSTEM-TIME reads from a pooled ORM connection.

Happy to open a PR against the skill content directly if that's more useful than an issue — let me know which you'd prefer.
