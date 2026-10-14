"""Broker adapters. Subclass BrokerAdapter and map a brokerage API to Dataset."""
from __future__ import annotations

import csv
import random
from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from .models import Account, CashMovement, Dataset, Settlement, Trade, D
from .anomalies import wash_pairs
from .reconcile import add_business_days


class BrokerAdapter(ABC):
    @abstractmethod
    def fetch(self, tenant_id: str, as_of: date) -> Dataset: ...


class CsvAdapter(BrokerAdapter):
    """Reads accounts.csv, trades.csv, settlements.csv, cash.csv from a directory."""

    def __init__(self, directory: str | Path):
        self.dir = Path(directory)

    def _rows(self, name):
        p = self.dir / name
        if not p.exists():
            return []
        with p.open(newline="") as f:
            return list(csv.DictReader(f))

    def fetch(self, tenant_id: str, as_of: date) -> Dataset:
        return Dataset(
            tenant_id, as_of,
            accounts=[Account(**r) for r in self._rows("accounts.csv")],
            trades=[Trade(r["trade_id"], r["account_id"], r["symbol"], r["side"].upper(),
                          D(r["qty"]), D(r["price"]), datetime.fromisoformat(r["ts"]),
                          r.get("venue", "")) for r in self._rows("trades.csv")],
            settlements=[Settlement(r["trade_id"], date.fromisoformat(r["settle_date"]),
                                    D(r["qty"]), D(r["amount"]), r.get("status", "SETTLED").upper())
                         for r in self._rows("settlements.csv")],
            cash=[CashMovement(r["movement_id"], r["account_id"], r["kind"].upper(),
                               D(r["amount"]), datetime.fromisoformat(r["ts"]))
                  for r in self._rows("cash.csv")],
        )


class SyntheticAdapter(BrokerAdapter):
    """Deterministic demo/test data with known, injected problems."""

    SYMBOLS = ["AAPL", "MSFT", "TSLA", "NVDA", "AMD", "SPY", "QQQ", "PLTR", "SOFI", "COIN"]

    def __init__(self, seed: int = 7, n_accounts: int = 60, days: int = 5):
        self.seed, self.n_accounts, self.days = seed, n_accounts, days

    def fetch(self, tenant_id: str = "demo", as_of: date | None = None) -> Dataset:
        rnd = random.Random(self.seed)
        start = date(2026, 9, 28)  # a Monday
        as_of = as_of or add_business_days(start, self.days + 2)
        accounts = [Account(f"A{i:03d}", tax_id=f"TX{i:05d}", device_id=f"DV{i:05d}",
                            bank_account=f"BK{i:05d}", address=f"{i} Main St") for i in range(self.n_accounts)]
        # Three accounts that are really one person.
        for i in (3, 4, 5):
            accounts[i] = Account(accounts[i].account_id, accounts[i].tax_id, "DV-SHARED",
                                  accounts[i].bank_account, accounts[i].address)
        trades: list[Trade] = []
        n = 0

        def mk(acct, sym, side, qty, price, ts):
            nonlocal n
            n += 1
            t = Trade(f"T{n:06d}", acct, sym, side, D(qty), D(price).quantize(Decimal("0.01")), ts, "XNAS")
            trades.append(t)
            return t

        base = {s: rnd.uniform(20, 400) for s in self.SYMBOLS}
        typical = {a.account_id: rnd.randint(2, 20) * 5 for a in accounts}  # each account has a stable size
        for d in range(self.days):
            day = start + timedelta(days=d)
            for _ in range(250):
                ts = datetime.combine(day, datetime.min.time()) + timedelta(seconds=rnd.randint(34200, 57600))
                a = accounts[rnd.randrange(self.n_accounts)].account_id
                sym = rnd.choice(self.SYMBOLS)
                mk(a, sym, rnd.choice(["BUY", "SELL"]), max(1, round(typical[a] * rnd.uniform(0.6, 1.4))),
                   base[sym] * rnd.uniform(0.98, 1.02), ts)

        # Background flow must be clean: drop any trade that randomly mirrors an earlier one.
        drop = set()
        for key in {(t.account_id, t.symbol) for t in trades}:
            grp = [t for t in trades if (t.account_id, t.symbol) == key]
            drop |= {b.trade_id for _, b in wash_pairs(grp)}
        trades[:] = [t for t in trades if t.trade_id not in drop]

        # Anomalies.
        t0 = datetime.combine(start + timedelta(days=1), datetime.min.time()) + timedelta(hours=11)
        mk("A010", "TSLA", "BUY", 90000, base["TSLA"], t0)                       # whale
        for k in range(14):                                                       # burst
            mk("A011", "AMD", "BUY", 5, base["AMD"], t0 + timedelta(seconds=k * 3))
        mk("A012", "NVDA", "BUY", 100, base["NVDA"], t0)                          # self wash
        mk("A012", "NVDA", "SELL", 100, base["NVDA"] * 1.001, t0 + timedelta(minutes=2))
        mk("A003", "PLTR", "BUY", 500, base["PLTR"], t0 + timedelta(hours=1))     # cross-account wash
        mk("A004", "PLTR", "SELL", 500, base["PLTR"] * 1.001, t0 + timedelta(hours=1, minutes=3))

        # Settlements: everything settles cleanly T+1, then we break some.
        settlements = {t.trade_id: Settlement(t.trade_id, add_business_days(t.ts.date(), 1), t.qty, t.notional)
                       for t in trades}
        ids = [t.trade_id for t in trades[:250]]  # early trades, so they're past due
        for tid in ids[0:5]:
            del settlements[tid]
        wash_leg = next(t.trade_id for t in trades if t.account_id == "A003" and t.symbol == "PLTR" and t.qty == 500)
        del settlements[wash_leg]  # ops break on a conduct-risk trade
        for tid in ids[5:8]:
            s = settlements[tid]
            settlements[tid] = Settlement(tid, s.settle_date, s.qty - 5, s.amount)
        for tid in ids[8:11]:
            s = settlements[tid]
            settlements[tid] = Settlement(tid, s.settle_date, s.qty, s.amount + Decimal("250.00"))
        for tid in ids[11:13]:
            s = settlements[tid]
            settlements[tid] = Settlement(tid, s.settle_date, s.qty, s.amount, "FAILED")
        for tid in ids[13:16]:
            s = settlements[tid]
            settlements[tid] = Settlement(tid, add_business_days(s.settle_date, 2), s.qty, s.amount)
        settlements["T999999"] = Settlement("T999999", start, D(10), D("1234.50"))  # orphan

        # Cash flow: normal deposits plus structuring.
        cash: list[CashMovement] = []
        for i in range(40):
            cash.append(CashMovement(f"C{i:04d}", accounts[rnd.randrange(self.n_accounts)].account_id,
                                     "DEPOSIT", D(rnd.randint(100, 4000)),
                                     datetime.combine(start, datetime.min.time()) + timedelta(hours=rnd.randint(1, 100))))
        m0 = datetime.combine(start, datetime.min.time()) + timedelta(hours=9)
        for k, amt in enumerate(("9500", "9800", "9200")):                        # single account
            cash.append(CashMovement(f"CS{k}", "A020", "DEPOSIT", D(amt), m0 + timedelta(hours=k * 20)))
        for k, acct in enumerate(("A003", "A004", "A005")):                       # across linked accounts
            cash.append(CashMovement(f"CL{k}", acct, "DEPOSIT", D("9600"), m0 + timedelta(days=2, hours=k)))
        return Dataset(tenant_id, as_of, accounts, trades, list(settlements.values()), cash)
