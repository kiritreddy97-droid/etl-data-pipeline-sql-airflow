"""Trade <-> settlement reconciliation (T+1 by default)."""
from __future__ import annotations

import hashlib
from datetime import date, timedelta
from decimal import Decimal

from .models import Alert, Dataset

AMOUNT_TOLERANCE = Decimal("0.01")


def alert_id(kind: str, *refs: str) -> str:
    return hashlib.sha1("|".join((kind, *sorted(refs))).encode()).hexdigest()[:12]


def add_business_days(d: date, n: int) -> date:
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def reconcile(ds: Dataset, settlement_cycle: int = 1) -> list[Alert]:
    alerts: list[Alert] = []
    settled = {s.trade_id: s for s in ds.settlements}
    trade_ids = {t.trade_id for t in ds.trades}

    def add(kind, sev, t, msg, **details):
        alerts.append(Alert(
            alert_id(kind, t.trade_id), "RECONCILIATION", kind, sev, msg,
            [t.account_id], [t.trade_id], details,
        ))

    for t in ds.trades:
        due = add_business_days(t.ts.date(), settlement_cycle)
        s = settled.get(t.trade_id)
        if s is None:
            if ds.as_of > due:
                add("MISSING_SETTLEMENT", "high", t,
                    f"{t.trade_id} ({t.symbol} {t.side}) was due {due} and has no settlement record",
                    due=str(due), notional=str(t.notional))
            continue
        if s.status == "FAILED":
            add("SETTLEMENT_FAIL", "high", t, f"{t.trade_id} failed to settle",
                due=str(due), notional=str(t.notional))
            continue
        if s.qty != t.qty:
            add("QTY_MISMATCH", "high", t,
                f"{t.trade_id}: traded {t.qty}, settled {s.qty}",
                traded=str(t.qty), settled=str(s.qty))
        diff = abs(s.amount - t.notional)
        if diff > AMOUNT_TOLERANCE:
            sev = "high" if diff > Decimal("100") else "medium"
            add("AMOUNT_MISMATCH", sev, t,
                f"{t.trade_id}: notional {t.notional:.2f} vs settled {s.amount:.2f} (diff {diff:.2f})",
                diff=str(diff))
        if s.settle_date > due:
            add("LATE_SETTLEMENT", "low", t,
                f"{t.trade_id} settled {s.settle_date}, expected {due}",
                days_late=(s.settle_date - due).days)

    for s in ds.settlements:
        if s.trade_id not in trade_ids:
            alerts.append(Alert(
                alert_id("ORPHAN_SETTLEMENT", s.trade_id), "RECONCILIATION",
                "ORPHAN_SETTLEMENT", "high",
                f"Settlement {s.trade_id} has no matching trade", [], [s.trade_id],
                {"amount": str(s.amount)},
            ))
    return alerts
