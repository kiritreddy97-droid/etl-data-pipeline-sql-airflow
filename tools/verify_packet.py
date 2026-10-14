#!/usr/bin/env python3
"""Independent verifier for a LedgerGuard evidence packet. Stdlib only.

    python tools/verify_packet.py packet.json

Checks (1) the hash chain is intact, (2) every alert in the case has a matching
'finding' entry whose alert_sha256 equals the SHA-256 of the alert as delivered,
(3) lists each reviewer decision recorded for the case. Exit 0 = verified.
"""
import hashlib
import json
import sys


def canonical(o):
    return json.dumps(o, sort_keys=True, separators=(",", ":"), default=str)


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def main(path):
    pkt = json.load(open(path))
    prev = "0" * 64
    for i, e in enumerate(pkt["ledger"], 1):
        body = {k: e[k] for k in ("seq", "ts", "tenant", "type", "payload", "prev")}
        if e["seq"] != i or e["prev"] != prev or sha(canonical(body)) != e["hash"]:
            print(f"FAIL: ledger entry {i} is missing, reordered or altered")
            return 1
        prev = e["hash"]
    findings = {e["payload"]["alert_id"]: e for e in pkt["ledger"] if e["type"] == "finding"}
    for a in pkt["alerts"]:
        f = findings.get(a["alert_id"])
        if not f:
            print(f"FAIL: alert {a['alert_id']} has no ledger entry")
            return 1
        delivered = {"alert_id": a["alert_id"], "category": a["category"], "kind": a["kind"], "severity": a["severity"],
                     "message": a["message"], "account_ids": a["accounts"], "refs": a["refs"], "details": a["details"]}
        if sha(canonical(delivered)) != f["payload"]["alert_sha256"]:
            print(f"FAIL: alert {a['alert_id']} differs from what was recorded at detection time")
            return 1
    ids = {a["alert_id"] for a in pkt["alerts"]}
    print(f"OK: chain of {len(pkt['ledger'])} entries intact (head {prev[:16]}); {len(ids)} alerts match their ledger records")
    for e in pkt["ledger"]:
        if e["type"] == "decision" and e["payload"]["alert_id"] in ids:
            p = e["payload"]
            print(f"  {e['ts']}  {p['alert_id']} -> {p['status']} by {p['actor']} {p['note']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
