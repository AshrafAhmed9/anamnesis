#!/usr/bin/env python3
"""Database-level survivability demo: write to Anamnesis continuously while
a CockroachDB *node* is killed outright (not just a dropped client
connection), and show writes keep landing.

This is different from — and stronger than — tests/test_memory.py's
simulated-connection-loss test, which proves the *application* retries
correctly. This proves the *cluster* itself stays available: the client
DSN lists all 3 nodes for failover, and Anamnesis's run_in_transaction
retry means a real `docker kill` on the node the connection is actually
using does not lose writes for more than a couple of retry cycles.

Which container maps to which CockroachDB node ID is NOT assumed — Docker
Compose container hostnames don't necessarily match node-join order, so
this script queries the cluster for which node_id its own connection is
using, then resolves that to a container via `cockroach node status`
addresses vs `docker ps` hostnames, and kills exactly that one. Killing an
arbitrary node the connection never touched would prove nothing.

Requires the local 3-node cluster: `docker compose -f
infra/docker-compose.multinode.yml up -d`, then `docker exec
infra-crdb-1-1 ./cockroach init --insecure` once.

Usage:
    python3 scripts/node_kill_demo.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid

os.environ.setdefault("ANAMNESIS_MOCK_LLM", "1")
# SQLAlchemy's URL object doesn't support libpq's host1:port1,host2:port2
# multi-host netloc syntax (it tries to parse everything after the first
# comma as a single int port and throws) — the working equivalent is the
# query-string form below, which SQLAlchemy passes through untouched to
# psycopg/libpq, which *does* support comma-separated host/port fallback.
os.environ.setdefault(
    "DATABASE_URL",
    "cockroachdb+psycopg://root@localhost/anamnesis_bench"
    "?sslmode=disable&host=localhost,localhost,localhost&port=26258,26259,26260",
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

from anamnesis.db.engine import get_engine  # noqa: E402
from anamnesis.memory import Anamnesis  # noqa: E402

INIT_CONTAINER = "infra-crdb-1-1"  # used to run `cockroach node status`
KILL_AFTER_WRITES = 8
TOTAL_WRITES = 30


def resolve_container_for_current_connection() -> str:
    """Find the docker container backing the node our connection is on."""
    engine = get_engine()
    with engine.connect() as conn:
        node_id = conn.execute(text("SELECT node_id FROM crdb_internal.node_build_info LIMIT 1")).scalar()

    status = subprocess.run(
        ["docker", "exec", INIT_CONTAINER, "./cockroach", "node", "status", "--insecure", "--format=csv"],
        check=True, capture_output=True, text=True,
    ).stdout
    lines = [ln.split(",") for ln in status.strip().splitlines()]
    header, rows = lines[0], lines[1:]
    addr_idx = header.index("address")
    id_idx = header.index("id")
    target_hostname = next(row[addr_idx].split(":")[0] for row in rows if row[id_idx] == str(node_id))

    ps = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}} {{.ID}}"], check=True, capture_output=True, text=True
    ).stdout
    for line in ps.strip().splitlines():
        name, short_id = line.split()
        if target_hostname.startswith(short_id):
            return name
    raise RuntimeError(f"could not resolve container for node {node_id} (hostname {target_hostname})")


def main() -> None:
    mem = Anamnesis()
    session_id = uuid.uuid4()
    killed = False
    results = []

    target_container = resolve_container_for_current_connection()
    print(f"Connection is currently served by container: {target_container}")
    print(f"Writing {TOTAL_WRITES} memories; will `docker kill {target_container}` "
          f"after write #{KILL_AFTER_WRITES}.\n")

    for i in range(1, TOTAL_WRITES + 1):
        t0 = time.monotonic()
        error = None
        try:
            mem.remember(session_id, "user", f"survivability probe #{i}")
        except Exception as exc:  # noqa: BLE001 — recording for the report, not swallowing
            error = repr(exc)
        elapsed_ms = (time.monotonic() - t0) * 1000
        results.append((i, error, elapsed_ms))
        status = "OK  " if error is None else "FAIL"
        print(f"  write {i:>2}/{TOTAL_WRITES}  {status}  {elapsed_ms:7.1f}ms" + (f"  {error}" if error else ""))

        if i == KILL_AFTER_WRITES and not killed:
            print(f"\n  >>> docker kill {target_container} <<<\n")
            subprocess.run(["docker", "kill", target_container], check=True, capture_output=True)
            killed = True

        time.sleep(0.15)

    ok = sum(1 for _, err, _ in results if err is None)
    print(f"\n{ok}/{TOTAL_WRITES} writes succeeded with {target_container} killed mid-run"
          f" (that container was actually serving the connection, confirmed via node_id lookup).")
    if ok == TOTAL_WRITES:
        print("Every write landed despite the killed node — cluster-level survivability confirmed.")
    else:
        failed = [i for i, err, _ in results if err is not None]
        print(f"Writes that failed: {failed} — see errors above.")

    print(f"\nRestart the node with: docker start {target_container}")


if __name__ == "__main__":
    main()
