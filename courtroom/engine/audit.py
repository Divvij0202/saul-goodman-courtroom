"""Tamper-evident audit trail: h_n = SHA256(h_{n-1} || canonical_json(event_n)).

Owner: Engineer 6 (Simulation Engine & API).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable

from courtroom.contracts import TrialEvent

GENESIS = "0" * 64


def canonical(event: TrialEvent) -> str:
    payload = event.model_dump(mode="json", exclude={"prev_hash", "hash"})
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def chain(event: TrialEvent, prev_hash: str) -> TrialEvent:
    digest = hashlib.sha256((prev_hash + canonical(event)).encode("ascii")).hexdigest()
    return event.model_copy(update={"prev_hash": prev_hash, "hash": digest})


def verify_chain(events: Iterable[TrialEvent]) -> bool:
    prev = GENESIS
    for ev in events:
        if ev.prev_hash != prev or chain(ev, prev).hash != ev.hash:
            return False
        prev = ev.hash
    return True
