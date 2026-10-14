"""Run every check and produce one report."""
from __future__ import annotations

import csv
import io
from collections import Counter

from . import anomalies, compliance, reconcile
from .models import SEVERITIES, Alert, Dataset


def run(ds: Dataset) -> dict:
    alerts: list[Alert] = [*reconcile.reconcile(ds), *anomalies.detect(ds), *compliance.check(ds)]
    alerts.sort(key=lambda a: (-SEVERITIES.index(a.severity), a.category, a.kind, a.alert_id))
    return {
        "tenant_id": ds.tenant_id,
        "as_of": ds.as_of.isoformat(),
        "dataset_sha256": ds.digest(),
        "counts": {"accounts": len(ds.accounts), "trades": len(ds.trades),
                   "settlements": len(ds.settlements), "cash": len(ds.cash)},
        "by_severity": dict(Counter(a.severity for a in alerts)),
        "by_kind": dict(Counter(a.kind for a in alerts)),
        "alerts": [a.to_dict() for a in alerts],
    }


def to_csv(report: dict) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["alert_id", "category", "kind", "severity", "accounts", "refs", "message"])
    for a in report["alerts"]:
        w.writerow([a["alert_id"], a["category"], a["kind"], a["severity"],
                    ";".join(a["account_ids"]), ";".join(a["refs"]), a["message"]])
    return out.getvalue()
