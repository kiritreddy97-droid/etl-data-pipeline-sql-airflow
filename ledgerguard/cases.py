"""Case fusion: join ops breaks and conduct-risk alerts that touch the same
trades, cash movements or linked-account cluster into one case with a narrative.

Reconciliation and surveillance normally live in different tools and teams; the
interesting risk is usually where they overlap (e.g. a wash trade between linked
accounts where one leg also failed to settle)."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .models import SEVERITIES, Alert

WEIGHT = {"low": 1, "medium": 3, "high": 8, "critical": 20}


@dataclass
class Case:
    case_id: str
    score: int
    severity: str
    categories: list[str]
    accounts: list[str]
    alert_ids: list[str]
    narrative: str

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def _narrate(alerts: list[Alert]) -> str:
    by = {}
    for a in alerts:
        by.setdefault(a.kind, []).append(a)
    parts = []
    if "LINKED_ACCOUNTS" in by:
        a = by["LINKED_ACCOUNTS"][0]
        parts.append(f"{len(a.account_ids)} accounts appear to share one owner "
                     f"(common {', '.join(a.details.get('shared_fields', []))})")
    for kind, text in (
        ("CROSS_ACCOUNT_WASH", "traded {sym} with each other at near-identical price and size"),
        ("WASH_TRADE", "bought and sold {sym} at near-identical price within minutes"),
        ("AGGREGATE_STRUCTURING", "made repeated sub-threshold cash deposits that together exceed the reporting threshold"),
        ("STRUCTURING", "made repeated deposits just under the reporting threshold"),
        ("VELOCITY_BURST", "fired an unusually fast burst of orders"),
        ("SIZE_OUTLIER", "placed a trade far outside its usual size"),
    ):
        if kind in by:
            sym = by[kind][0].details.get("symbol", "a security")
            parts.append(text.format(sym=sym))
    ops = [k for k in by if by[k][0].category == "RECONCILIATION"]
    if ops:
        parts.append("with operational breaks on the same activity (" + ", ".join(sorted(ops)).lower().replace("_", " ") + ")")
    cats = {a.category for a in alerts}
    tail = (" Conduct and operations signals coincide, so this is prioritised above either alone."
            if len(cats) > 1 else "")
    return ("; ".join(parts) or "Related alerts") + "." + tail + " Indicators only: review required, not a finding of misconduct."


def build(alerts: list[Alert]) -> list[Case]:
    n = len(alerts)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        parent[find(i)] = find(j)

    owner: dict[tuple, int] = {}
    for i, a in enumerate(alerts):
        keys = [("ref", r) for r in a.refs]
        if a.category != "RECONCILIATION":  # accounts join conduct alerts only, else one account = one giant case
            keys += [("acct", x) for x in a.account_ids]
        for k in keys:
            if k in owner:
                union(i, owner[k])
            else:
                owner[k] = i
    groups: dict[int, list[Alert]] = {}
    for i, a in enumerate(alerts):
        groups.setdefault(find(i), []).append(a)

    cases = []
    for grp in groups.values():
        if len(grp) < 2:
            continue  # lone alerts stay in the alert queue; a case is a correlation
        cats = sorted({a.category for a in grp})
        score = sum(WEIGHT[a.severity] for a in grp) * (2 if len(cats) > 1 else 1)
        sev = max((a.severity for a in grp), key=SEVERITIES.index)
        ids = sorted(a.alert_id for a in grp)
        cases.append(Case(
            hashlib.sha1("|".join(ids).encode()).hexdigest()[:12], score, sev, cats,
            sorted({x for a in grp for x in a.account_ids}), ids, _narrate(grp)))
    cases.sort(key=lambda c: (-c.score, c.case_id))
    return cases
