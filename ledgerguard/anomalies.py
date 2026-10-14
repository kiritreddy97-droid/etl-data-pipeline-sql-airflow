"""Single-account transaction anomaly detection."""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from itertools import groupby

from .models import Alert, CashMovement, Dataset, Trade
from .reconcile import alert_id

REPORTING_THRESHOLD = Decimal("10000")  # CTR-style cash reporting threshold
WASH_WINDOW = timedelta(minutes=10)
WASH_PRICE_TOL = Decimal("0.005")
WASH_QTY_TOL = Decimal("0.05")


def wash_pairs(trades: list[Trade]):
    """Opposite-side trades in one symbol at ~same price/qty within a short window."""
    trades = sorted(trades, key=lambda t: t.ts)
    for i, a in enumerate(trades):
        for b in trades[i + 1:]:
            if b.ts - a.ts > WASH_WINDOW:
                break
            if a.side == b.side or a.symbol != b.symbol:
                continue
            if abs(a.price - b.price) / a.price > WASH_PRICE_TOL:
                continue
            if abs(a.qty - b.qty) / max(a.qty, b.qty) > WASH_QTY_TOL:
                continue
            yield a, b


def structuring(moves: list[CashMovement], window: timedelta, min_count=3):
    """Windows of >=min_count deposits each just below the reporting threshold."""
    low = REPORTING_THRESHOLD * Decimal("0.8")
    dep = sorted((m for m in moves if m.kind == "DEPOSIT" and low <= m.amount < REPORTING_THRESHOLD),
                 key=lambda m: m.ts)
    i = 0
    while i < len(dep):
        j = i
        while j + 1 < len(dep) and dep[j + 1].ts - dep[i].ts <= window:
            j += 1
        if j - i + 1 >= min_count:
            yield dep[i:j + 1]
            i = j + 1
        else:
            i += 1


def detect(ds: Dataset, z_threshold=6.0, burst_size=10, burst_secs=60) -> list[Alert]:
    alerts: list[Alert] = []
    by_acct: dict[str, list[Trade]] = defaultdict(list)
    for t in ds.trades:
        by_acct[t.account_id].append(t)

    for acct, trades in by_acct.items():
        trades.sort(key=lambda t: t.ts)

        # 2. Velocity bursts.
        in_burst: set[str] = set()
        best, lo = (0, 0), 0
        for hi in range(len(trades)):
            while (trades[hi].ts - trades[lo].ts).total_seconds() > burst_secs:
                lo += 1
            if hi - lo + 1 > best[1] - best[0] + 1:
                best = (lo, hi)
        n = best[1] - best[0] + 1
        if n >= burst_size:
            burst = trades[best[0]:best[1] + 1]
            in_burst = {t.trade_id for t in burst}
            alerts.append(Alert(
                alert_id("VELOCITY_BURST", acct, burst[0].trade_id), "ANOMALY", "VELOCITY_BURST", "medium",
                f"{acct}: {n} trades within {burst_secs}s", [acct], [t.trade_id for t in burst], {"count": n},
            ))

        # 1. Position-size outliers (robust z-score: median/MAD).
        base = [t for t in trades if t.trade_id not in in_burst]  # a burst must not drag the baseline down
        if len(base) >= 8:
            vals = [float(t.notional) for t in base]
            med = statistics.median(vals)
            mad = statistics.median(abs(v - med) for v in vals)
            for t, v in zip(base, vals):
                score = 0.6745 * (v - med) / mad if mad else (float("inf") if v > 10 * med else 0.0)
                if score > z_threshold:
                    alerts.append(Alert(
                        alert_id("SIZE_OUTLIER", t.trade_id), "ANOMALY", "SIZE_OUTLIER", "medium",
                        f"{acct}: {t.trade_id} notional {v:,.0f} vs median {med:,.0f}",
                        [acct], [t.trade_id], {"median": med, "notional": v},
                    ))

        # 3. Self-matched (wash) trades.
        for sym, grp in groupby(sorted(trades, key=lambda t: t.symbol), key=lambda t: t.symbol):
            for a, b in wash_pairs(list(grp)):
                alerts.append(Alert(
                    alert_id("WASH_TRADE", a.trade_id, b.trade_id), "ANOMALY", "WASH_TRADE", "high",
                    f"{acct}: {sym} bought and sold at ~{a.price} within {WASH_WINDOW}",
                    [acct], [a.trade_id, b.trade_id], {"symbol": sym},
                ))

    # 4. Cash structuring per account.
    cash_by_acct: dict[str, list[CashMovement]] = defaultdict(list)
    for m in ds.cash:
        cash_by_acct[m.account_id].append(m)
    for acct, moves in cash_by_acct.items():
        for grp in structuring(moves, timedelta(days=3)):
            total = sum(m.amount for m in grp)
            alerts.append(Alert(
                alert_id("STRUCTURING", *(m.movement_id for m in grp)), "ANOMALY", "STRUCTURING", "high",
                f"{acct}: {len(grp)} deposits just under {REPORTING_THRESHOLD:,} totalling {total:,}",
                [acct], [m.movement_id for m in grp], {"total": str(total)},
            ))
    return alerts
