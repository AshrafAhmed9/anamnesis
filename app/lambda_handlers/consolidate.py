"""EventBridge-scheduled Lambda: consolidation + decay sweep + S3 report.

Runs periodically (e.g. every 30 min) to fold low-salience episodic
memory into semantic beliefs, decay stale salience, and drop a JSON
report of what happened into S3 for audit/demo purposes.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from anamnesis.memory import Anamnesis

REPORT_BUCKET = os.environ.get("ANAMNESIS_REPORT_BUCKET")


def handler(event, context):
    mem = Anamnesis()
    consolidated_ids = mem.consolidate()
    decayed_rows = mem.decay()

    report = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "consolidated_belief_ids": [str(i) for i in consolidated_ids],
        "decayed_rows": decayed_rows,
    }

    if REPORT_BUCKET:
        import boto3

        s3 = boto3.client("s3")
        key = f"consolidation-reports/{report['run_at']}.json"
        s3.put_object(Bucket=REPORT_BUCKET, Key=key, Body=json.dumps(report).encode())
        report["s3_key"] = key

    return report
