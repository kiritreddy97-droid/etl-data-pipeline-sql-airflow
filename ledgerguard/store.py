"""SQLite persistence: tenants (API-key auth), runs, alerts with a review workflow."""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
from datetime import datetime, timezone

from . import ledger
from .models import Alert, canonical

STATUSES = ("open", "acknowledged", "resolved", "false_positive")

SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants(id TEXT PRIMARY KEY, name TEXT, key_hash TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT, ts TEXT, summary TEXT);
CREATE TABLE IF NOT EXISTS alerts(
  tenant_id TEXT, alert_id TEXT, run_id INTEGER, category TEXT, kind TEXT, severity TEXT,
  message TEXT, accounts TEXT, refs TEXT, details TEXT, status TEXT DEFAULT 'open',
  first_seen TEXT, last_seen TEXT, PRIMARY KEY(tenant_id, alert_id));
CREATE TABLE IF NOT EXISTS ledger(tenant_id TEXT, seq INTEGER, ts TEXT, type TEXT, payload TEXT, prev TEXT, hash TEXT, PRIMARY KEY(tenant_id, seq));
CREATE TABLE IF NOT EXISTS audit_log(id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT, ts TEXT, actor TEXT, action TEXT, detail TEXT);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str = ":memory:"):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self.db.executescript(SCHEMA)

    def _append(self, tenant_id: str, type_: str, payload: dict, ts: str) -> None:
        """Caller must hold self.lock inside a transaction."""
        r = self.db.execute("SELECT seq,hash FROM ledger WHERE tenant_id=? ORDER BY seq DESC LIMIT 1", (tenant_id,)).fetchone()
        e = {"seq": (r["seq"] + 1) if r else 1, "ts": ts, "tenant": tenant_id, "type": type_,
             "payload": json.loads(json.dumps(payload, default=str)), "prev": r["hash"] if r else ledger.GENESIS}
        e["hash"] = ledger.entry_hash(e)
        self.db.execute("INSERT INTO ledger VALUES(?,?,?,?,?,?,?)",
                        (tenant_id, e["seq"], ts, type_, json.dumps(e["payload"], sort_keys=True), e["prev"], e["hash"]))

    def ledger_entries(self, tenant_id: str) -> list[dict]:
        return [{"seq": r["seq"], "ts": r["ts"], "tenant": tenant_id, "type": r["type"],
                 "payload": json.loads(r["payload"]), "prev": r["prev"], "hash": r["hash"]}
                for r in self.db.execute("SELECT * FROM ledger WHERE tenant_id=? ORDER BY seq", (tenant_id,))]

    def create_tenant(self, tenant_id: str, name: str) -> str:
        key = "lg_" + secrets.token_urlsafe(24)
        with self.lock, self.db:
            self.db.execute("INSERT INTO tenants VALUES(?,?,?)", (tenant_id, name, hashlib.sha256(key.encode()).hexdigest()))
        return key  # shown once; only the hash is stored

    def tenant_for_key(self, key: str) -> str | None:
        r = self.db.execute("SELECT id FROM tenants WHERE key_hash=?", (hashlib.sha256(key.encode()).hexdigest(),)).fetchone()
        return r["id"] if r else None

    def save_report(self, tenant_id: str, report: dict) -> int:
        """Alert ids are content hashes, so re-ingesting the same data updates
        last_seen rather than duplicating alerts or reopening reviewed ones."""
        now = _now()
        summary = {k: report[k] for k in ("as_of", "counts", "by_severity", "by_kind")}
        with self.lock, self.db:
            run_id = self.db.execute("INSERT INTO runs(tenant_id,ts,summary) VALUES(?,?,?)",
                                     (tenant_id, now, json.dumps(summary))).lastrowid
            known = {r[0] for r in self.db.execute("SELECT alert_id FROM alerts WHERE tenant_id=?", (tenant_id,))}
            self._append(tenant_id, "ingest", {"run_id": run_id, "as_of": report["as_of"],
                         "dataset_sha256": report["dataset_sha256"], "counts": report["counts"]}, now)
            for a in report["alerts"]:
                if a["alert_id"] not in known:
                    self._append(tenant_id, "finding", {"run_id": run_id, "alert_id": a["alert_id"], "kind": a["kind"],
                                 "severity": a["severity"], "refs": a["refs"], "accounts": a["account_ids"],
                                 "alert_sha256": hashlib.sha256(canonical(a).encode()).hexdigest()}, now)
                self.db.execute(
                    """INSERT INTO alerts(tenant_id,alert_id,run_id,category,kind,severity,message,accounts,refs,details,first_seen,last_seen)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(tenant_id,alert_id) DO UPDATE SET last_seen=excluded.last_seen, run_id=excluded.run_id""",
                    (tenant_id, a["alert_id"], run_id, a["category"], a["kind"], a["severity"], a["message"],
                     json.dumps(a["account_ids"]), json.dumps(a["refs"]), json.dumps(a["details"], default=str), now, now))
            self.db.execute("INSERT INTO audit_log(tenant_id,ts,actor,action,detail) VALUES(?,?,?,?,?)",
                            (tenant_id, now, "api", "ingest", f"run {run_id}: {len(report['alerts'])} alerts"))
        return run_id

    def alerts(self, tenant_id: str, severity: str | None = None, status: str | None = None) -> list[dict]:
        q, args = "SELECT * FROM alerts WHERE tenant_id=?", [tenant_id]
        for col, val in (("severity", severity), ("status", status)):
            if val:
                q += f" AND {col}=?"
                args.append(val)
        q += " ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, first_seen"
        out = []
        for r in self.db.execute(q, args):
            d = dict(r)
            for f in ("accounts", "refs", "details"):
                d[f] = json.loads(d[f])
            out.append(d)
        return out

    def set_status(self, tenant_id: str, alert_id: str, status: str, actor: str = "api", note: str = "") -> bool:
        if status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}")
        with self.lock, self.db:
            n = self.db.execute("UPDATE alerts SET status=? WHERE tenant_id=? AND alert_id=?",
                                (status, tenant_id, alert_id)).rowcount
            if n:
                self._append(tenant_id, "decision", {"alert_id": alert_id, "status": status, "actor": actor, "note": note[:500]}, _now())
                self.db.execute("INSERT INTO audit_log(tenant_id,ts,actor,action,detail) VALUES(?,?,?,?,?)",
                                (tenant_id, _now(), actor, "status", f"{alert_id} -> {status}"))
        return bool(n)

    def summary(self, tenant_id: str) -> dict:
        sev = {r[0]: r[1] for r in self.db.execute(
            "SELECT severity,COUNT(*) FROM alerts WHERE tenant_id=? AND status='open' GROUP BY severity", (tenant_id,))}
        kinds = {r[0]: r[1] for r in self.db.execute(
            "SELECT kind,COUNT(*) FROM alerts WHERE tenant_id=? AND status='open' GROUP BY kind", (tenant_id,))}
        run = self.db.execute("SELECT * FROM runs WHERE tenant_id=? ORDER BY id DESC LIMIT 1", (tenant_id,)).fetchone()
        return {"open_by_severity": sev, "open_by_kind": kinds,
                "last_run": {"ts": run["ts"], **json.loads(run["summary"])} if run else None}

    def audit_log(self, tenant_id: str, limit: int = 100) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT ts,actor,action,detail FROM audit_log WHERE tenant_id=? ORDER BY id DESC LIMIT ?", (tenant_id, limit))]

    def as_alerts(self, tenant_id: str) -> list[Alert]:
        return [Alert(r["alert_id"], r["category"], r["kind"], r["severity"], r["message"],
                      r["accounts"], r["refs"], r["details"]) for r in self.alerts(tenant_id)]

    def case_packet(self, tenant_id: str, case_id: str) -> dict | None:
        from . import cases
        case = next((c for c in cases.build(self.as_alerts(tenant_id)) if c.case_id == case_id), None)
        if not case:
            return None
        ids = set(case.alert_ids)
        return {"packet_version": 1, "case": case.to_dict(),
                "alerts": [a for a in self.alerts(tenant_id) if a["alert_id"] in ids],
                "ledger": self.ledger_entries(tenant_id),
                "verify_with": "python tools/verify_packet.py packet.json"}
