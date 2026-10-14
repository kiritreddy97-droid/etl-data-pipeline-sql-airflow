"""Normalized data model. Every broker adapter maps its API into these types."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any

SEVERITIES = ("low", "medium", "high", "critical")


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def D(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


@dataclass(frozen=True)
class Account:
    account_id: str
    tax_id: str = ""
    device_id: str = ""
    bank_account: str = ""
    address: str = ""


@dataclass(frozen=True)
class Trade:
    trade_id: str
    account_id: str
    symbol: str
    side: str  # BUY | SELL
    qty: Decimal
    price: Decimal
    ts: datetime
    venue: str = ""

    @property
    def notional(self) -> Decimal:
        return self.qty * self.price


@dataclass(frozen=True)
class Settlement:
    trade_id: str
    settle_date: date
    qty: Decimal
    amount: Decimal  # gross cash amount, unsigned
    status: str = "SETTLED"  # SETTLED | FAILED | PENDING


@dataclass(frozen=True)
class CashMovement:
    movement_id: str
    account_id: str
    kind: str  # DEPOSIT | WITHDRAWAL
    amount: Decimal
    ts: datetime


@dataclass
class Dataset:
    tenant_id: str
    as_of: date
    accounts: list[Account] = field(default_factory=list)
    trades: list[Trade] = field(default_factory=list)
    settlements: list[Settlement] = field(default_factory=list)
    cash: list[CashMovement] = field(default_factory=list)

    def digest(self) -> str:
        """SHA-256 over a canonical, order-independent encoding of the input data,
        so a finding can be tied to exactly the data that produced it."""
        h = hashlib.sha256()
        for name in ("accounts", "trades", "settlements", "cash"):
            rows = sorted(canonical(asdict(r)) for r in getattr(self, name))
            h.update(name.encode() + b"\n" + "\n".join(rows).encode() + b"\n")
        return h.hexdigest()

    @classmethod
    def from_dict(cls, d: dict) -> "Dataset":
        """Parse the JSON ingest payload. Raises ValueError/KeyError on bad input."""
        return cls(
            tenant_id=d.get("tenant_id", ""),
            as_of=date.fromisoformat(d["as_of"]),
            accounts=[Account(**a) for a in d.get("accounts", [])],
            trades=[
                Trade(
                    t["trade_id"], t["account_id"], t["symbol"], t["side"].upper(),
                    D(t["qty"]), D(t["price"]), datetime.fromisoformat(t["ts"]),
                    t.get("venue", ""),
                )
                for t in d.get("trades", [])
            ],
            settlements=[
                Settlement(
                    s["trade_id"], date.fromisoformat(s["settle_date"]),
                    D(s["qty"]), D(s["amount"]), s.get("status", "SETTLED").upper(),
                )
                for s in d.get("settlements", [])
            ],
            cash=[
                CashMovement(
                    c["movement_id"], c["account_id"], c["kind"].upper(),
                    D(c["amount"]), datetime.fromisoformat(c["ts"]),
                )
                for c in d.get("cash", [])
            ],
        )


@dataclass
class Alert:
    alert_id: str
    category: str  # RECONCILIATION | ANOMALY | COMPLIANCE
    kind: str
    severity: str
    message: str
    account_ids: list[str]
    refs: list[str]
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)
