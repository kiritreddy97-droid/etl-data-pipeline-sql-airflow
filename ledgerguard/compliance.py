"""Multi-account compliance: link accounts that look like one beneficial owner,
then re-run the single-account tests across the whole cluster."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from itertools import groupby

from .anomalies import structuring, wash_pairs
from .models import Alert, Dataset
from .reconcile import alert_id

LINK_FIELDS = ("tax_id", "device_id", "bank_account", "address")


def link_accounts(ds: Dataset) -> list[tuple[list[str], list[str]]]:
    """Union-find over shared identifiers. Returns [(account_ids, shared_fields)]."""
    parent = {a.account_id: a.account_id for a in ds.accounts}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    shared: dict[str, set[str]] = defaultdict(set)
    for f in LINK_FIELDS:
        seen: dict[str, str] = {}
        for a in ds.accounts:
            v = getattr(a, f).strip().lower()
            if not v:
                continue
            if v in seen:
                ra, rb = find(seen[v]), find(a.account_id)
                parent[ra] = rb
                shared[a.account_id].add(f)
                shared[seen[v]].add(f)
            else:
                seen[v] = a.account_id
    groups: dict[str, list[str]] = defaultdict(list)
    for acct in parent:
        groups[find(acct)].append(acct)
    out = []
    for members in groups.values():
        if len(members) > 1:
            fields = sorted(set().union(*(shared[m] for m in members)))
            out.append((sorted(members), fields))
    return out


def check(ds: Dataset) -> list[Alert]:
    alerts: list[Alert] = []
    for members, fields in link_accounts(ds):
        mset = set(members)
        key = "+".join(members)
        alerts.append(Alert(
            alert_id("LINKED_ACCOUNTS", key), "COMPLIANCE", "LINKED_ACCOUNTS", "medium",
            f"{len(members)} accounts share {', '.join(fields)}: {', '.join(members)}",
            members, members, {"shared_fields": fields},
        ))

        trades = sorted((t for t in ds.trades if t.account_id in mset), key=lambda t: t.symbol)
        for sym, grp in groupby(trades, key=lambda t: t.symbol):
            for a, b in wash_pairs(list(grp)):
                if a.account_id == b.account_id:
                    continue  # covered by single-account wash detection
                alerts.append(Alert(
                    alert_id("CROSS_ACCOUNT_WASH", a.trade_id, b.trade_id), "COMPLIANCE",
                    "CROSS_ACCOUNT_WASH", "critical",
                    f"{sym} traded between linked accounts {a.account_id} and {b.account_id} at ~{a.price}",
                    sorted({a.account_id, b.account_id}), [a.trade_id, b.trade_id], {"symbol": sym},
                ))

        moves = [m for m in ds.cash if m.account_id in mset]
        for grp in structuring(moves, timedelta(days=1)):
            accts = sorted({m.account_id for m in grp})
            if len(accts) < 2:
                continue  # single-account structuring already flagged
            total = sum(m.amount for m in grp)
            alerts.append(Alert(
                alert_id("AGGREGATE_STRUCTURING", *(m.movement_id for m in grp)), "COMPLIANCE",
                "AGGREGATE_STRUCTURING", "critical",
                f"Linked accounts deposited {total:,} in sub-threshold amounts within 24h",
                accts, [m.movement_id for m in grp], {"total": str(total)},
            ))
    return alerts
