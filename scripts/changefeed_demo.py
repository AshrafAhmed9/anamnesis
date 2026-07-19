#!/usr/bin/env python3
"""CDC changefeed demo: memory events as a live stream, not just rows in a
table. CockroachDB's `CREATE CHANGEFEED` (used here in "core"/sinkless
form — no Kafka/S3/webhook needed for the demo) turns every write to
memory_audit into a row-level event delivered over the wire in real time.

This is a genuinely different capability from "query the audit table" —
it's how you'd wire a downstream system (a dashboard, an alerting rule, a
second agent watching for SUPERSEDE events) to react to memory changes as
they happen, without polling.

`WITH no_initial_scan` is important for an honest demo: without it, a
changefeed's default behavior is to first emit every existing row (an
"initial scan" backlog) before switching to live changes — this script
uses a real `Anamnesis.remember()` write as the trigger and would
otherwise report a stale pre-existing row as if it were the live event.

Usage:
    python3 scripts/changefeed_demo.py
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from datetime import datetime, timezone

import psycopg

os.environ.setdefault("ANAMNESIS_MOCK_LLM", "1")
DATABASE_URL_PLAIN = "postgresql://root@localhost:26257/anamnesis_test?sslmode=disable"
os.environ.setdefault(
    "DATABASE_URL", "cockroachdb+psycopg://root@localhost:26257/anamnesis_test?sslmode=disable"
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from anamnesis.memory import Anamnesis  # noqa: E402


def trigger_write(episode_holder: dict) -> None:
    """Runs on a delay, in a background thread, so the changefeed
    subscription is already live before the write happens — otherwise
    there's a race where the write could land before we start listening.
    Records the real episode id `remember()` generates, since that's what
    memory_audit.memory_id will actually contain — the audit `reason`
    field is fixed text ("episodic remember"), not something a caller can
    stamp a marker into, so matching on the real id is the correct way to
    identify *this* write's event among any others, not a fragile string
    match on a field that can never contain it.
    """
    time.sleep(1.5)
    mem = Anamnesis()
    episode_holder["id"] = str(mem.remember(uuid.uuid4(), "user", "changefeed demo trigger"))


def main() -> None:
    episode_holder: dict = {}
    threading.Thread(target=trigger_write, args=(episode_holder,), daemon=True).start()

    conn = psycopg.connect(DATABASE_URL_PLAIN, autocommit=True)
    cur = conn.cursor()

    # A changefeed subscription runs forever by design, so a bounded demo
    # needs an external watchdog rather than relying on statement_timeout
    # (which isn't guaranteed to apply cleanly to a streaming statement) —
    # force-closing the connection from another thread reliably breaks the
    # `for row in cur.stream(...)` loop below with an exception we catch.
    def watchdog():
        time.sleep(15)
        try:
            conn.close()
        except Exception:
            pass

    threading.Thread(target=watchdog, daemon=True).start()

    print("Subscribing to CHANGEFEED FOR memory_audit (no_initial_scan) — waiting for the live WRITE event this run triggers...\n")

    found = None
    try:
        for row in cur.stream("EXPERIMENTAL CHANGEFEED FOR memory_audit WITH no_initial_scan"):
            table, key, value = row
            payload = json.loads(value)
            after = payload.get("after") or {}
            print(f"  [changefeed event] table={table} action={after.get('action')} memory_id={after.get('memory_id')} reason={after.get('reason')}")
            if episode_holder.get("id") and after.get("memory_id") == episode_holder["id"]:
                found = after
                break
    except Exception as exc:
        if found is None:
            print(f"  (stream ended: {exc!r})")

    try:
        conn.close()
    except Exception:
        pass

    report_lines = [
        "CDC changefeed demo: memory_audit events streamed live via CHANGEFEED\n",
        f"Run at: {datetime.now(timezone.utc).isoformat()}\n",
    ]
    if found:
        report_lines.append(
            f"PASS: received a live changefeed event for the triggered write within the deadline.\n"
            f"Event: action={found.get('action')}, reason={found.get('reason')}, at={found.get('at')}"
        )
        print("\n" + report_lines[-1])
    else:
        report_lines.append("FAIL: did not receive the expected live event within the deadline.")
        print("\n" + report_lines[-1])

    out_path = os.path.join(os.path.dirname(__file__), "..", "docs", "results", "changefeed_demo_output.txt")
    with open(out_path, "w") as f:
        f.write("\n".join(report_lines) + "\n")
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
