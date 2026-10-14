"""Hash-chained, append-only evidence ledger.

Entry hash = SHA-256 over canonical JSON of {seq, ts, tenant, type, payload, prev}.
`prev` is the previous entry's hash ("0"*64 for the first). Altering, deleting or
reordering any entry breaks every later hash. tools/verify_packet.py re-implements
verify() with the stdlib only, so an auditor can check a packet independently.
"""
from __future__ import annotations

import hashlib

from .models import canonical

GENESIS = "0" * 64
FIELDS = ("seq", "ts", "tenant", "type", "payload", "prev")


def entry_hash(e: dict) -> str:
    return hashlib.sha256(canonical({k: e[k] for k in FIELDS}).encode()).hexdigest()


def verify(entries: list[dict]) -> tuple[bool, str]:
    prev = GENESIS
    for i, e in enumerate(entries):
        if e["seq"] != i + 1:
            return False, f"entry {i + 1}: sequence gap or reorder (found seq {e['seq']})"
        if e["prev"] != prev:
            return False, f"entry {e['seq']}: prev-hash does not match previous entry"
        if entry_hash(e) != e["hash"]:
            return False, f"entry {e['seq']}: content was altered"
        prev = e["hash"]
    return True, f"{len(entries)} entries, head {prev[:16]}"
