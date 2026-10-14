"""Stdlib HTTP API + dashboard. Auth: `X-API-Key` header, one key per tenant."""
from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import cases, engine, ledger
from .models import Dataset
from .store import Store

MAX_BODY = 50 * 1024 * 1024
DASHBOARD = Path(__file__).with_name("dashboard.html")


def make_handler(store: Store):
    class H(BaseHTTPRequestHandler):
        def _send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else (body if isinstance(body, str) else json.dumps(body, default=str)).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def _tenant(self):
            t = store.tenant_for_key(self.headers.get("X-API-Key", ""))
            if not t:
                self._send(401, {"error": "invalid or missing X-API-Key"})
            return t

        def do_GET(self):
            u = urlparse(self.path)
            if u.path == "/":
                return self._send(200, DASHBOARD.read_bytes(), "text/html; charset=utf-8")
            if u.path == "/healthz":
                return self._send(200, {"ok": True})
            tenant = self._tenant()
            if not tenant:
                return
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if u.path == "/v1/summary":
                return self._send(200, store.summary(tenant))
            if u.path == "/v1/alerts":
                return self._send(200, store.alerts(tenant, q.get("severity"), q.get("status")))
            if u.path == "/v1/cases":
                return self._send(200, [c.to_dict() for c in cases.build(store.as_alerts(tenant))])
            m = re.fullmatch(r"/v1/cases/([0-9a-f]{12})/packet", u.path)
            if m:
                pkt = store.case_packet(tenant, m.group(1))
                return self._send(200 if pkt else 404, pkt or {"error": "no such case"})
            if u.path == "/v1/ledger/verify":
                ok, msg = ledger.verify(store.ledger_entries(tenant))
                return self._send(200, {"ok": ok, "detail": msg})
            if u.path == "/v1/audit":
                return self._send(200, store.audit_log(tenant))
            if u.path == "/v1/report.csv":
                rep = {"alerts": [{**a, "account_ids": a["accounts"]} for a in store.alerts(tenant)]}
                return self._send(200, engine.to_csv(rep), "text/csv")
            self._send(404, {"error": "not found"})

        def do_POST(self):
            tenant = self._tenant()
            if not tenant:
                return
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                return self._send(413, {"error": "payload too large"})
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except json.JSONDecodeError:
                return self._send(400, {"error": "invalid JSON"})
            path = urlparse(self.path).path
            if path == "/v1/ingest":
                try:
                    ds = Dataset.from_dict({**body, "tenant_id": tenant})  # tenant comes from the key, never the body
                except (KeyError, ValueError, TypeError) as e:
                    return self._send(400, {"error": f"bad dataset: {e}"})
                report = engine.run(ds)
                run_id = store.save_report(tenant, report)
                return self._send(200, {"run_id": run_id, "alerts": len(report["alerts"]),
                                        "by_severity": report["by_severity"]})
            m = re.fullmatch(r"/v1/alerts/([0-9a-f]{12})/status", path)
            if m:
                try:
                    ok = store.set_status(tenant, m.group(1), str(body.get("status")), note=str(body.get("note", "")))
                except ValueError as e:
                    return self._send(400, {"error": str(e)})
                return self._send(200 if ok else 404, {"updated": ok})
            self._send(404, {"error": "not found"})

        def log_message(self, *a):
            pass

    return H


def serve(store: Store, host="127.0.0.1", port=8080):
    srv = ThreadingHTTPServer((host, port), make_handler(store))
    srv.serve_forever()
