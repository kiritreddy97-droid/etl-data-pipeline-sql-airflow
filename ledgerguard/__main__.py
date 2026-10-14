"""CLI:  python -m ledgerguard demo [--serve]   |   python -m ledgerguard run DIR TENANT"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from . import engine
from .adapters import CsvAdapter, SyntheticAdapter
from .server import serve
from .store import Store


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="ledgerguard")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo", help="analyze synthetic brokerage data")
    d.add_argument("--serve", action="store_true", help="then start the API + dashboard")
    d.add_argument("--port", type=int, default=8080)
    r = sub.add_parser("run", help="analyze a directory of CSV exports")
    r.add_argument("directory")
    r.add_argument("--tenant", default="local")
    r.add_argument("--as-of", default=date.today().isoformat())
    r.add_argument("--out", help="write full JSON report here")
    args = p.parse_args(argv)

    if args.cmd == "demo":
        ds = SyntheticAdapter().fetch("demo")
    else:
        ds = CsvAdapter(args.directory).fetch(args.tenant, date.fromisoformat(args.as_of))
    report = engine.run(ds)
    print(f"{report['counts']['trades']} trades, {report['counts']['accounts']} accounts, as of {report['as_of']}")
    print("alerts by severity:", report["by_severity"])
    for kind, n in sorted(report["by_kind"].items()):
        print(f"  {kind:<24}{n}")
    if args.cmd == "run" and args.out:
        with open(args.out, "w") as f:
            json.dump(report, f, indent=2)

    if args.cmd == "demo" and args.serve:
        store = Store()
        key = store.create_tenant("demo", "Demo Brokerage")
        store.save_report("demo", report)
        print(f"\nDashboard: http://127.0.0.1:{args.port}/\nAPI key (demo only): {key}")
        serve(store, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
