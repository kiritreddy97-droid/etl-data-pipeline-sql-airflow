import copy
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date, datetime
from http.server import ThreadingHTTPServer

from ledgerguard import cases, engine, ledger
from ledgerguard.adapters import SyntheticAdapter
from ledgerguard.models import Account, Dataset, Trade, D
from ledgerguard.reconcile import add_business_days
from ledgerguard.server import make_handler
from ledgerguard.store import Store


def kinds(report):
    return report["by_kind"]


class Engine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = engine.run(SyntheticAdapter().fetch("demo"))

    def test_injected_reconciliation_breaks_are_found_exactly(self):
        k = kinds(self.report)
        self.assertEqual(k["MISSING_SETTLEMENT"], 6)
        self.assertEqual(k["QTY_MISMATCH"], 3)
        self.assertEqual(k["AMOUNT_MISMATCH"], 3)
        self.assertEqual(k["SETTLEMENT_FAIL"], 2)
        self.assertEqual(k["LATE_SETTLEMENT"], 3)
        self.assertEqual(k["ORPHAN_SETTLEMENT"], 1)

    def test_injected_anomalies_are_found(self):
        accts = lambda kind: {a for x in self.report["alerts"] if x["kind"] == kind for a in x["account_ids"]}
        self.assertIn("A010", accts("SIZE_OUTLIER"))
        self.assertIn("A011", accts("VELOCITY_BURST"))
        self.assertIn("A012", accts("WASH_TRADE"))
        self.assertEqual(accts("STRUCTURING"), {"A020"})

    def test_multi_account_compliance(self):
        linked = [a for a in self.report["alerts"] if a["kind"] == "LINKED_ACCOUNTS"]
        self.assertEqual(len(linked), 1)
        self.assertEqual(linked[0]["account_ids"], ["A003", "A004", "A005"])
        self.assertEqual(kinds(self.report)["CROSS_ACCOUNT_WASH"], 1)
        self.assertEqual(kinds(self.report)["AGGREGATE_STRUCTURING"], 1)

    def test_no_noise_on_clean_data(self):
        """Every alert on the demo set traces to an injected fault."""
        noisy = {"A0%02d" % i for i in range(30, 60)}
        flagged = {a for x in self.report["alerts"] if x["category"] != "RECONCILIATION" for a in x["account_ids"]}
        self.assertFalse(flagged & noisy)

    def test_burst_does_not_pollute_size_baseline(self):
        outliers = {a for x in self.report["alerts"] if x["kind"] == "SIZE_OUTLIER" for a in x["account_ids"]}
        self.assertNotIn("A011", outliers)

    def test_case_fusion_joins_ops_and_conduct(self):
        from ledgerguard.models import Alert
        cs = cases.build([Alert(a["alert_id"], a["category"], a["kind"], a["severity"], a["message"],
                                a["account_ids"], a["refs"], a["details"]) for a in self.report["alerts"]])
        top = cs[0]
        self.assertEqual(top.categories, ["ANOMALY", "COMPLIANCE", "RECONCILIATION"])
        self.assertEqual(top.accounts, ["A003", "A004", "A005"])
        self.assertIn("traded PLTR with each other", top.narrative)
        self.assertIn("missing settlement", top.narrative)
        self.assertIn("not a finding of misconduct", top.narrative)
        # lone alerts (e.g. the whale) are not cases
        self.assertTrue(all(len(c.alert_ids) > 1 for c in cs))

    def test_dataset_digest_is_order_independent_and_sensitive(self):
        a = SyntheticAdapter().fetch("x")
        b = SyntheticAdapter().fetch("x")
        b.trades.reverse()
        self.assertEqual(a.digest(), b.digest())
        b.trades[0] = b.trades[0].__class__(**{**b.trades[0].__dict__, "qty": b.trades[0].qty + 1})
        self.assertNotEqual(a.digest(), b.digest())

    def test_deterministic_ids(self):
        again = engine.run(SyntheticAdapter().fetch("demo"))
        self.assertEqual([a["alert_id"] for a in again["alerts"]], [a["alert_id"] for a in self.report["alerts"]])

    def test_business_days(self):
        self.assertEqual(add_business_days(date(2026, 10, 9), 1), date(2026, 10, 12))  # Fri -> Mon

    def test_not_yet_due_is_not_a_break(self):
        t = Trade("T1", "A", "X", "BUY", D(1), D(10), datetime(2026, 10, 14, 10))
        r = engine.run(Dataset("t", date(2026, 10, 14), [Account("A")], [t]))
        self.assertEqual(r["alerts"], [])

    def test_shared_blank_fields_do_not_link(self):
        r = engine.run(Dataset("t", date(2026, 10, 14), [Account("A"), Account("B")]))
        self.assertEqual(r["alerts"], [])


class Api(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.key = self.store.create_tenant("t1", "T1")
        self.other = self.store.create_tenant("t2", "T2")
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.store))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_port}"

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def call(self, path, key=None, body=None):
        req = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode(),
                                     headers={"X-API-Key": key or self.key})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read() or b"null") if "csv" not in path else r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def payload(self):
        ds = SyntheticAdapter().fetch("ignored")
        return {
            "as_of": ds.as_of.isoformat(),
            "accounts": [a.__dict__ for a in ds.accounts],
            "trades": [{**t.__dict__, "ts": t.ts.isoformat(), "qty": str(t.qty), "price": str(t.price)} for t in ds.trades],
            "settlements": [{**s.__dict__, "settle_date": s.settle_date.isoformat(), "qty": str(s.qty), "amount": str(s.amount)} for s in ds.settlements],
            "cash": [{**c.__dict__, "ts": c.ts.isoformat(), "amount": str(c.amount)} for c in ds.cash],
        }

    def test_auth_required(self):
        self.assertEqual(self.call("/v1/summary", key="nope")[0], 401)

    def test_ingest_review_and_tenant_isolation(self):
        code, res = self.call("/v1/ingest", body=self.payload())
        self.assertEqual(code, 200)
        self.assertGreater(res["alerts"], 20)
        _, alerts = self.call("/v1/alerts?severity=critical")
        self.assertTrue(alerts and all(a["severity"] == "critical" for a in alerts))
        aid = alerts[0]["alert_id"]
        self.assertEqual(self.call(f"/v1/alerts/{aid}/status", body={"status": "resolved"})[0], 200)
        self.assertEqual(self.call(f"/v1/alerts/{aid}/status", body={"status": "bogus"})[0], 400)
        # Re-ingest: no duplicates, resolved alert stays resolved.
        self.call("/v1/ingest", body=self.payload())
        _, again = self.call("/v1/alerts")
        self.assertEqual(len(again), res["alerts"])
        self.assertEqual(next(a for a in again if a["alert_id"] == aid)["status"], "resolved")
        # Other tenant sees nothing, and cannot touch tenant 1's alert.
        self.assertEqual(self.call("/v1/alerts", key=self.other)[1], [])
        self.assertEqual(self.call(f"/v1/alerts/{aid}/status", key=self.other, body={"status": "open"})[0], 404)
        self.assertIn("alert_id", self.call("/v1/report.csv")[1])
        actions = [e["action"] for e in self.call("/v1/audit")[1]]
        self.assertIn("status", actions)

    def test_evidence_packet_verifies_and_detects_tampering(self):
        self.call("/v1/ingest", body=self.payload())
        _, cs = self.call("/v1/cases")
        cid = cs[0]["case_id"]
        aid = cs[0]["alert_ids"][0]
        self.call(f"/v1/alerts/{aid}/status", body={"status": "acknowledged", "note": "escalated to BSA officer"})
        self.assertTrue(self.call("/v1/ledger/verify")[1]["ok"])
        _, pkt = self.call(f"/v1/cases/{cid}/packet")
        tool = os.path.join(os.path.dirname(__file__), "..", "tools", "verify_packet.py")

        def verify(p):
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
                json.dump(p, f)
            r = subprocess.run([sys.executable, "-I", tool, f.name], capture_output=True, text=True)
            os.unlink(f.name)
            return r.returncode, r.stdout

        code, out = verify(pkt)
        self.assertEqual(code, 0, out)
        self.assertIn("escalated to BSA officer", out)
        # 1. edit a recorded alert message
        bad = copy.deepcopy(pkt); bad["alerts"][0]["message"] += " (edited)"
        self.assertEqual(verify(bad)[0], 1)
        # 2. quietly rewrite a ledger decision
        bad = copy.deepcopy(pkt)
        next(e for e in bad["ledger"] if e["type"] == "decision")["payload"]["status"] = "false_positive"
        self.assertEqual(verify(bad)[0], 1)
        # 3. delete an entry
        bad = copy.deepcopy(pkt); del bad["ledger"][2]
        self.assertEqual(verify(bad)[0], 1)
        self.assertFalse(ledger.verify(bad["ledger"])[0])
        # tenants cannot read each other's cases
        self.assertEqual(self.call(f"/v1/cases/{cid}/packet", key=self.other)[0], 404)

    def test_bad_payload(self):
        self.assertEqual(self.call("/v1/ingest", body={"as_of": "nope"})[0], 400)


if __name__ == "__main__":
    unittest.main()
