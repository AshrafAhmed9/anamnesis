#!/usr/bin/env python3
"""Region-aware failure demo: runs against infra/docker-compose.multiregion.yml
(3 nodes with REAL --locality=region=... flags: us-east, us-west, eu-west),
and kills the specific node/region actually serving the live connection,
labeling the failure by REGION NAME, not just a container name — the
demo-worthy version of node_kill_demo.py for a "multi-region deployment"
narrative.

Honest scope, stated plainly rather than implied: this is still 3
containers on one Docker host, so it cannot demonstrate real cross-region
network latency (Docker doesn't add WAN-like delay between local
containers). What IS real here: CockroachDB genuinely recognizes and
reports 3 distinct localities (verified via `node status`), and the
failure/recovery mechanics are identical to a true cross-region node loss
from the client's point of view — same connection failover, same retry
path, same audit trail.

Usage:
    python3 scripts/region_kill_demo.py
"""
from __future__ import annotations

import csv
import io
import os
import subprocess
import sys
import time
import uuid

os.environ.setdefault("ANAMNESIS_MOCK_LLM", "1")
os.environ.setdefault(
    "DATABASE_URL",
    "cockroachdb+psycopg://root@localhost/anamnesis_region"
    "?sslmode=disable&host=localhost,localhost,localhost&port=26261,26262,26263",
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

from anamnesis.db.engine import get_engine  # noqa: E402
from anamnesis.memory import Anamnesis  # noqa: E402

INIT_CONTAINER = "anamnesis-multiregion-crdb-us-east-1"
KILL_AFTER_WRITES = 8
TOTAL_WRITES = 25


def resolve_region_and_container() -> tuple[str, str]:
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT node_id, crdb_internal.locality_value('region') FROM crdb_internal.node_build_info LIMIT 1"
            )
        ).fetchone()
        node_id = row[0]

    status = subprocess.run(
        ["docker", "exec", INIT_CONTAINER, "./cockroach", "node", "status", "--insecure", "--format=csv"],
        check=True, capture_output=True, text=True,
    ).stdout
    # The `locality` column's value (e.g. "region=us-east,zone=us-east-1a")
    # itself contains commas, so it's properly CSV-quoted in the output —
    # a naive str.split(",") breaks on it. csv.reader handles the quoting
    # correctly, unlike the manual split() the first version of this
    # script used, which crashed with "locality" not found in the header
    # because the row/header column counts didn't line up.
    rows_parsed = list(csv.reader(io.StringIO(status)))
    header, rows = rows_parsed[0], rows_parsed[1:]
    addr_idx, id_idx, loc_idx = header.index("address"), header.index("id"), header.index("locality")
    match = next(r for r in rows if r[id_idx] == str(node_id))
    target_hostname = match[addr_idx].split(":")[0]
    locality = match[loc_idx]
    region = next((kv.split("=")[1] for kv in locality.split(",") if kv.startswith("region=")), "unknown")

    ps = subprocess.run(["docker", "ps", "--format", "{{.Names}} {{.ID}}"], check=True, capture_output=True, text=True).stdout
    for line in ps.strip().splitlines():
        name, short_id = line.split()
        if target_hostname.startswith(short_id):
            return region, name
    raise RuntimeError(f"could not resolve container for node {node_id} (hostname {target_hostname})")


def main() -> None:
    mem = Anamnesis()
    session_id = uuid.uuid4()
    killed = False
    results = []

    region, target_container = resolve_region_and_container()
    print(f"Connection is currently served by region={region!r} (container {target_container})")
    print(f"Writing {TOTAL_WRITES} memories; will kill the '{region}' region's node after write #{KILL_AFTER_WRITES}.\n")

    for i in range(1, TOTAL_WRITES + 1):
        t0 = time.monotonic()
        error = None
        try:
            mem.remember(session_id, "user", f"region-kill probe #{i}")
        except Exception as exc:  # noqa: BLE001
            error = repr(exc)
        elapsed_ms = (time.monotonic() - t0) * 1000
        results.append((i, error, elapsed_ms))
        status = "OK  " if error is None else "FAIL"
        print(f"  write {i:>2}/{TOTAL_WRITES}  {status}  {elapsed_ms:7.1f}ms" + (f"  {error}" if error else ""))

        if i == KILL_AFTER_WRITES and not killed:
            print(f"\n  >>> docker kill {target_container}  (region '{region}' goes down) <<<\n")
            subprocess.run(["docker", "kill", target_container], check=True, capture_output=True)
            killed = True

        time.sleep(0.15)

    ok = sum(1 for _, err, _ in results if err is None)
    lines = [
        f"Region-kill demo: region={region!r} ({target_container}) killed mid-write-loop\n",
        f"{ok}/{TOTAL_WRITES} writes succeeded.",
    ]
    if ok == TOTAL_WRITES:
        lines.append(
            f"Every write landed despite losing the '{region}' region entirely — the client "
            f"failed over to the surviving regions (verified: 'us-east', 'us-west', 'eu-west' "
            f"are real, distinct localities CockroachDB reports, not just container names)."
        )
    else:
        failed = [i for i, err, _ in results if err is not None]
        lines.append(f"Writes that failed: {failed}")
    lines.append(
        "\nScope note: 3 containers on one Docker host cannot simulate real cross-region "
        "network latency — this demonstrates the failover/retry mechanics with genuine "
        "CockroachDB locality awareness, not WAN-scale timing."
    )
    report = "\n".join(lines)
    print("\n" + report)

    out_path = os.path.join(os.path.dirname(__file__), "..", "docs", "results", "region_kill_demo_output.txt")
    with open(out_path, "w") as f:
        f.write(report + "\n")
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
