# etl-data-pipeline-sql-airflow

Production ETL pipeline with Apache Airflow, Python, SQL — multi-source ingestion, JOLT transformation, quality validation, and automated data warehouse loading.

---

# LedgerGuard — case-based compliance & reconciliation middleware for retail brokerages

B2B SaaS prototype for high-transaction retail investment platforms. It plugs into a brokerage's data
(API, SFTP/CSV, or JSON ingest), then reconciles, screens and reports. **Zero runtime dependencies** (Python 3.11+ stdlib + SQLite).

## What makes it different

Surveillance vendors ship *alert queues*; reconciliation vendors ship *break queues*. They are separate tools owned by
separate teams, so the riskiest activity — where an ops break and a conduct signal land on the same trades — is never
seen as one thing. LedgerGuard changes the unit of work:

1. **Case fusion** (`cases.py`). Reconciliation breaks, single-account anomalies and linked-account compliance alerts
   that share trades, cash movements or accounts are joined into one **case**, scored (cross-domain overlap doubles the
   score) and explained in plain English. The demo's 27 alerts collapse to one case: *3 accounts share a device, wash-trade
   PLTR with each other, structure deposits under the reporting threshold, and one leg failed to settle.*
2. **Verifiable evidence** (`ledger.py`, `tools/verify_packet.py`). Every ingest (bound to a SHA-256 of the exact input data),
   finding (bound to a hash of the alert) and reviewer decision (actor + note) is appended to a per-tenant hash chain.
   A case exports as an evidence packet that a regulator or auditor can verify **without our software** using a ~60-line
   stdlib script. Edits, rewritten decisions and deleted entries are all detected (see tests).
3. **Stable findings.** Alert IDs are content hashes: re-ingesting the same data never duplicates alerts or reopens ones a
   reviewer already closed.

> Market note: trade surveillance is a crowded category (e.g. Eventus, Trading Technologies, KX); "audit trail" and
> "evidence pack" are common marketing phrases. I found no product that fuses reconciliation + conduct + linked-account
> analysis for retail-broker APIs, but that is from a handful of web searches, not exhaustive diligence — validate with
> customer discovery before relying on it.

## What it detects

| Layer | Checks |
|---|---|
| Reconciliation | missing / failed / late settlement (T+1, business-day aware), quantity & amount mismatch, orphan settlements |
| Anomalies | size outliers (median/MAD, burst-robust), order bursts, self wash trades, single-account cash structuring |
| Multi-account compliance | linked accounts via shared tax ID / device / bank / address (union-find), cross-account wash trades, aggregate structuring across a cluster |

Output is *indicators for human review*, never a conclusion of misconduct.

## Run it

```bash
python -m ledgerguard demo                 # analyze synthetic data with injected faults
python -m ledgerguard demo --serve         # + API and dashboard on :8080 (prints a demo API key)
python -m ledgerguard run ./exports --tenant acme --as-of 2026-10-14   # CSV exports
python -m unittest discover -s tests       # 15 tests
curl -H "X-API-Key: $KEY" localhost:8080/v1/cases/<id>/packet > packet.json
python tools/verify_packet.py packet.json  # OK: chain of N entries intact ...
```

API (`X-API-Key`, one key per tenant, only the hash is stored): `POST /v1/ingest`, `GET /v1/cases`,
`GET /v1/cases/{id}/packet`, `GET /v1/alerts?severity=&status=`, `POST /v1/alerts/{id}/status`, `GET /v1/ledger/verify`,
`GET /v1/report.csv`, `GET /v1/audit`. A broker integration is one `BrokerAdapter.fetch()`; an Airflow DAG is in `dags/ledgerguard_daily.py`.

## Business model (hypothesis)

Per-tenant platform fee + volume tier (trades/month) + per-adapter fees; retention comes from the accumulated evidence
ledger and reviewer history, which become costly to leave. Net revenue retention follows trade-volume growth.

## Known limits (prototype)

Thresholds are illustrative defaults, not legal advice or a substitute for a firm's own supervisory procedures. The
ledger proves *integrity since recording*, not truth of the source data, and is not externally anchored (anchoring the
head hash to a third-party timestamp service is the next step). No TLS/rate-limiting/SSO in the bundled server — put it
behind a gateway. Detection is rules-based; no ML, no backtesting of rule changes yet.
