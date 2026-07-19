"""ccloud CLI ops sub-agent: the memory layer watches its own health.

Runs `ccloud cluster info` / `ccloud cluster backup list` (JSON output)
against the cluster hosting Anamnesis's own memory, summarizes the result
with the LLM, and writes the finding into ops_log — and, if noteworthy,
into the agent's own semantic memory ("I noticed X about my own
substrate").

The command names above are verified against the real `ccloud` CLI
(`ccloud auth whoami`, then running both commands against a live
cluster), not guessed from the CLI's general "noun-verb" pattern — the
first version of this file used `ccloud cluster describe` and `ccloud
backup list --cluster <id>`, neither of which exist; the real subcommands
are `cluster info` and `cluster backup list <id>`.

Requires a ccloud service account with read-only RBAC scoped to this
cluster (see infra/README.md). Runs as a scheduled Lambda alongside the
consolidation job, or invoked ad hoc for the "self-awareness" demo moment.
"""
from __future__ import annotations

import json
import subprocess
import uuid
from datetime import datetime, timezone

from anamnesis.agent.bedrock import ChatMessage, get_client
from anamnesis.db.engine import run_in_transaction
from anamnesis.db.models import OpsLog
from anamnesis.memory import Anamnesis

CLUSTER_ID_ENV = "COCKROACH_CLUSTER_ID"


def _run_ccloud(*args: str) -> dict:
    result = subprocess.run(
        ["ccloud", *args, "-o", "json"],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return json.loads(result.stdout)


def gather_cluster_facts(cluster_id: str) -> dict:
    return {
        "cluster": _run_ccloud("cluster", "info", cluster_id),
        "backups": _run_ccloud("cluster", "backup", "list", cluster_id),
    }


def summarize_and_remember(facts: dict) -> str:
    llm = get_client()
    summary = llm.chat(
        [
            ChatMessage(
                role="user",
                content=(
                    "Summarize the health of this CockroachDB cluster (which is "
                    "this agent's own memory substrate) in one sentence, noting "
                    "anything noteworthy about backups or node state:\n\n"
                    + json.dumps(facts, indent=2)[:4000]
                ),
            )
        ]
    ).strip()

    def _do(db):
        db.add(OpsLog(source="ccloud", summary=summary, raw=facts))

    run_in_transaction(_do)
    return summary


def handler(event, context):
    import os

    cluster_id = os.environ.get(CLUSTER_ID_ENV)
    if not cluster_id:
        return {"skipped": True, "reason": f"{CLUSTER_ID_ENV} not set"}

    facts = gather_cluster_facts(cluster_id)
    summary = summarize_and_remember(facts)

    mem = Anamnesis()
    session_id = uuid.uuid5(uuid.NAMESPACE_DNS, "anamnesis-ops-agent")
    mem.remember(session_id, "agent", f"[self-observation @ {datetime.now(timezone.utc).isoformat()}] {summary}")

    return {"summary": summary}


if __name__ == "__main__":
    print(handler({}, None))
