"""Evidence routing for the AlphaForge / WealthForge paper-trading agent team.

Thesis: the agent proposes; the infrastructure records. ``EvidenceRouter.emit()``
is the single choke point through which every action's evidence flows, and the
router — not the agent — decides what gets recorded, where it goes, and who may
read it.

Consumers (the spine's Evidence -> Verification -> Accountability):
  - AuditLog  (Ch 19 compliance): append-only, HMAC-chained, tenant-partitioned.
    Immutable. This is the record the auditor, the kill-switch review, and the
    "who ordered that?" dispute all read.
  - TraceSink (Ch 14 observability): operational trace stream, full fidelity,
    short retention (ring buffer). For debugging the loop, not for proving it.
  - EvalDataset (Ch 15 evaluators): curated event types only, frozen records
    the judge scores against.

The router itself sits OUTSIDE the agent's write authority ("who watches the
watcher"): the agent receives a narrow ``emit`` capability. The ``AuditLog``
exposes no public write method at all — the router calls the private
``_append``; anything else that wants evidence recorded goes through
``emit``. An agent that could choose what the audit log contains could
choose what the auditor sees.

Tenant binding: ``emit`` takes a *verified session*, not a bare tenant-id
string. The session is whatever object the authority layer verified (in
AlphaForge, Ch 6's ``TenantSession``); evidence.py requires only that it
expose a ``tenant_id`` attribute and refuses plain strings outright. The
signature check itself belongs to the authority layer (Ch 6's
``require_tenant``) — the router binds the verified identity, it does not
re-authenticate it. One choke point per job.

Stdlib only: hashlib, hmac, json, time, threading, secrets, copy.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import secrets
import threading
import time


# ---------------------------------------------------------------------------
# Evidence taxonomy. Every event the system can emit belongs to exactly one
# of these types. Anything else is a misconfiguration, and misconfiguration
# fails closed: unknown types are recorded in the audit log, never dropped.
# ---------------------------------------------------------------------------
EVENT_TYPES = frozenset({
    "intent_record",     # strategy emitted a trading intention (Ch 3 decision plane)
    "authority_check",   # tenant token verified, scope checked, allow/deny (Ch 6)
    "tool_call",         # tool name + args digest + result summary (Ch 4 contract)
    "broker_response",   # broker_id, status, filled_qty, avg_price (Ch 10)
    "reconcile_event",   # key, prior status, resolution (Ch 10)
    "refusal",           # provider refused; category + reason (Ch 5)
    "kill_switch",       # breaker trip / reset (Ch 11)
})

# What the evaluator is allowed to see. Deliberately curated: the judge
# scores decisions and outcomes, not raw authority plumbing.
EVAL_TYPES = frozenset({
    "intent_record", "tool_call", "broker_response", "refusal", "kill_switch",
})

# What the operational trace carries. High-volume, short-lived: enough to
# reconstruct "what happened at 09:31" during an incident, then discarded.
TRACE_TYPES = frozenset({
    "tool_call", "broker_response", "reconcile_event", "kill_switch",
})

_SERIALIZATION_FAILED = "serialization_failed"


def _canonical(obj) -> str:
    """Deterministic serialization for hashing. Key order must not matter."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _session_tenant_id(session) -> str:
    """Extract the tenant id from a verified session. Bare strings are claims,
    not proofs: the caller that hands us a string is asking us to trust the
    agent's word about who it is, which is exactly the spoof the router exists
    to prevent."""
    if isinstance(session, (str, bytes)) or session is None:
        raise TypeError(
            "emit requires a verified session object (e.g. Ch 6 "
            "TenantSession), not a bare tenant_id string")
    tenant_id = getattr(session, "tenant_id", None)
    if not tenant_id:
        raise ValueError("session object exposes no usable tenant_id")
    return tenant_id


class AuditLog:
    """Append-only, HMAC-chained, tamper-evident evidence store.

    Each entry commits to the hash of the previous entry, keyed with an
    infrastructure-held HMAC secret. Altering any field of any entry without
    the key breaks the chain from that point forward, and ``verify_chain()``
    reports the first broken sequence number. There is no update, no delete,
    and no public append: the ONLY writer is ``EvidenceRouter``, which calls
    the private ``_append``. (Python cannot make this physically impossible,
    so the test suite pins the absence of any public write path — the
    discipline is architectural, enforced by the narrowest possible API
    surface.)

    Threat model, stated honestly: the HMAC stops every actor who does not
    hold the key — the insider without infrastructure access, the bug, the
    "oops" nobody can explain. It does NOT stop the key holder or the
    infrastructure itself: with the key, the whole chain can be recomputed
    from genesis. Key custody is therefore a first-class design decision,
    not a deployment detail.

    Concurrency: ``_append`` serializes on a lock. Two strategies emitting at
    the same instant must not interleave seq/prev_hash computation, or one
    entry's link is orphaned and the chain is permanently broken.

    Hash chains detect *edits*, not *tail deletion*: silently dropping the
    last N entries leaves a perfectly valid chain. ``checkpoint()`` returns
    the head hash so the infrastructure can anchor it to external WORM
    (write-once) storage; a truncated log then fails the anchor comparison.

    Entries carry two clocks: ``ts`` (wall clock, for humans and auditors)
    and ``mono`` (``time.monotonic()``, for ordering). Wall clock lies — NTP
    steps, leap seconds — so forensic ordering is computed from ``mono``.

    Entries carry ``tenant_id``; reads are tenant-scoped and return *absence*
    for other tenants' entries (Ch 6's convention: an error would itself leak
    that the key exists for someone else).
    """

    GENESIS = "0" * 64

    def __init__(self, secret: bytes, clock=None):
        if not isinstance(secret, (bytes, bytearray)) or len(secret) < 16:
            raise ValueError(
                "AuditLog requires an HMAC secret of at least 16 bytes, "
                "injected from the infrastructure (env/secret manager), "
                "never from source")
        self._secret = bytes(secret)
        self._clock = clock or time.time
        self._lock = threading.Lock()
        self._entries: list[dict] = []

    # -- the single write path; router-only by convention ------------------
    def _hash_entry(self, seq: int, ts: float, mono: float, tenant_id: str,
                    event_type: str, payload: dict, prev_hash: str) -> str:
        body = _canonical({
            "seq": seq, "ts": ts, "mono": mono, "tenant_id": tenant_id,
            "event_type": event_type, "payload": payload,
            "prev_hash": prev_hash,
        })
        return hmac.new(self._secret, body.encode("utf-8"),
                        hashlib.sha256).hexdigest()

    def _append(self, session, event_type: str, payload: dict,
                flagged: bool = False) -> dict:
        tenant_id = _session_tenant_id(session)
        with self._lock:  # the serialization choke point: seq, prev_hash,
                          # and append are one atomic step
            seq = len(self._entries)
            prev = (self._entries[-1]["entry_hash"] if self._entries
                    else self.GENESIS)
            ts = self._clock()
            mono = time.monotonic()
            record = dict(payload or {})
            try:
                entry_hash = self._hash_entry(
                    seq, ts, mono, tenant_id, event_type, record, prev)
            except Exception:
                # A payload that cannot be serialized is still evidence — of
                # its own failure. Never silently drop it.
                record = {_SERIALIZATION_FAILED: True,
                          "raw_repr": repr(payload)}
                entry_hash = self._hash_entry(
                    seq, ts, mono, tenant_id, event_type, record, prev)
                flagged = True
            entry = {
                "seq": seq,
                "ts": ts,
                "mono": mono,
                "tenant_id": tenant_id,
                "event_type": event_type,
                "payload": record,
                "flagged": flagged,   # True when the router failed an event closed
                "prev_hash": prev,
                "entry_hash": entry_hash,
            }
            self._entries.append(entry)
            return dict(entry)

    # -- reads ---------------------------------------------------------------
    def read(self, tenant_id: str) -> list[dict]:
        """Tenant-scoped read. Other tenants' entries are absent, not errors."""
        with self._lock:
            return [dict(e) for e in self._entries
                    if e["tenant_id"] == tenant_id]

    def checkpoint(self) -> str:
        """Head hash for anchoring to external WORM storage.

        The infrastructure writes (seq, head_hash) to append-only storage on
        a schedule. A log whose tail was deleted still verifies locally —
        the anchor comparison is what catches truncation.
        """
        with self._lock:
            if not self._entries:
                return self.GENESIS
            return self._entries[-1]["entry_hash"]

    def __len__(self):
        with self._lock:
            return len(self._entries)

    def verify_chain(self) -> tuple[bool, int | None]:
        """Returns (True, None) if intact, else (False, first_bad_seq).

        Detects edits and re-attribution. Does NOT detect tail truncation —
        pair with checkpoint() anchoring for that.
        """
        with self._lock:
            entries = list(self._entries)
        prev = self.GENESIS
        for e in entries:
            if e["prev_hash"] != prev:
                return False, e["seq"]
            recomputed = self._hash_entry(
                e["seq"], e["ts"], e["mono"], e["tenant_id"],
                e["event_type"], e["payload"], e["prev_hash"])
            if not hmac.compare_digest(recomputed, e["entry_hash"]):
                return False, e["seq"]
            prev = e["entry_hash"]
        return True, None


class TraceSink:
    """Operational trace: full-fidelity, short-retention ring buffer.

    Keeps the last ``capacity`` events for live debugging ("reconstruct
    09:31"). Old events are discarded by design — the audit log is the
    durable record; this is the scratch pad. Tenant-scoped reads, same
    absence convention as the audit log.
    """

    def __init__(self, capacity: int = 10_000):
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self._capacity = capacity
        self._events: list[dict] = []

    def _record(self, session, event_type: str, payload: dict) -> None:
        self._events.append({
            "ts": time.time(), "tenant_id": _session_tenant_id(session),
            "event_type": event_type, "payload": dict(payload),
        })
        del self._events[:-self._capacity]

    def read(self, tenant_id: str) -> list[dict]:
        return [dict(e) for e in self._events if e["tenant_id"] == tenant_id]

    def __len__(self):
        return len(self._events)


class EvalDataset:
    """Curated, frozen records for the evaluator (Ch 15).

    Only EVAL_TYPES are admitted; each record is a snapshot the judge scores.
    Frozen with copy.deepcopy, so native types (datetimes, UUIDs, sets)
    survive intact and later mutation of the caller's payload cannot rewrite
    what the judge saw.
    """

    def __init__(self):
        self._records: list[dict] = []

    def _record(self, session, event_type: str, payload: dict) -> None:
        if event_type not in EVAL_TYPES:
            return  # not judgeable; the audit log still has it
        self._records.append({
            "tenant_id": _session_tenant_id(session),
            "event_type": event_type,
            "payload": copy.deepcopy(payload),  # frozen; native types kept
        })

    def records(self, tenant_id: str) -> list[dict]:
        return [dict(r) for r in self._records if r["tenant_id"] == tenant_id]

    def __len__(self):
        return len(self._records)


class EvidenceRouter:
    """The single choke point for evidence. The agent proposes; this records.

    ``emit(session, event_type, payload)`` is the only capability the agent
    holds. ``session`` is a *verified* session object (Ch 6's TenantSession),
    never a bare tenant-id string: the tenant recorded on every entry comes
    from the proof, not from the caller's word. Routing per event type:

      audit log : EVERYTHING (including unknown types — never dropped)
      trace     : TRACE_TYPES (operational, short retention)
      eval set  : EVAL_TYPES (curated for the judge)

    Unknown event types fail closed: they land in the audit log *flagged*,
    so the misconfiguration is itself evidence, and they are never silently
    dropped. A routing table that names a non-taxonomy type is rejected at
    construction — fail fast on config, fail closed at runtime.

    ``secret`` is the audit log's HMAC key. Pass one from the secret manager
    in production; the dev default (a fresh random key per process) means a
    restarted process cannot verify its own old logs — which is exactly the
    behavior that forces the key into real custody.
    """

    def __init__(self, audit_log: AuditLog | None = None,
                 trace: TraceSink | None = None,
                 eval_dataset: EvalDataset | None = None,
                 trace_capacity: int = 10_000,
                 secret: bytes | None = None):
        self.audit = audit_log or AuditLog(secret or secrets.token_bytes(32))
        self.trace = trace or TraceSink(capacity=trace_capacity)
        self.evalset = eval_dataset or EvalDataset()

    def emit(self, session, event_type: str, payload: dict) -> dict:
        _session_tenant_id(session)  # fail fast: strings are not sessions
        payload = dict(payload or {})
        if event_type not in EVENT_TYPES:
            # Fail closed: unknown evidence is still evidence. Flag it so the
            # misconfiguration shows up in the very log it tried to bypass.
            return self.audit._append(
                session, event_type, payload, flagged=True)
        entry = self.audit._append(session, event_type, payload)
        if event_type in TRACE_TYPES:
            self.trace._record(session, event_type, payload)
        if event_type in EVAL_TYPES:
            self.evalset._record(session, event_type, payload)
        return entry

    def verify(self) -> tuple[bool, int | None]:
        """Delegate to the audit log's chain verification."""
        return self.audit.verify_chain()
