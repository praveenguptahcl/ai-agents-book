"""Durable runs: leases, heartbeats, fencing, checkpoints, resume-from-ledger.

A long-running agent will die at 3am. That is not a failure mode; it is the
schedule. The question is never "how do we prevent death" — it is "what does
the replacement find when it wakes up."

Three mechanisms, in dependency order:

  - LEASE: exactly one worker owns a run at a time. Ownership expires
    (TTL on a monotonic clock) unless renewed by heartbeat. A second worker
    may take over an expired lease — but never a live one.
  - FENCING: every mutation carries the lease token. A zombie worker that
    wakes up after its lease expired finds its writes REJECTED
    (``StaleFenceError``), because the replacement may already own the run.
    The fence token is the only thing standing between "failover" and
    "two writers."
  - CHECKPOINT + RESUME: the worker periodically snapshots its state,
    stamped with the evidence-log sequence it had consumed (Ch 9's audit
    log is the spine). The replacement loads the snapshot and replays only
    the entries after the checkpoint seq — it resumes from the ledger, not
    from scratch, and never re-executes what the dead worker already did.

The lease store here is in-memory — the teaching module. Production keeps
the same semantics over the WAL-backed store (cf. Ch 10/Ch 11's SQLite:
write-ahead before mutation). The fencing rule is identical either way.
"""

from __future__ import annotations

import copy
import time
import uuid


class StaleFenceError(RuntimeError):
    """A write arrived with an expired or superseded lease token."""


class LeaseConflict(RuntimeError):
    """Someone live already owns this run."""


class LeaseStore:
    """In-memory lease registry with monotonic-clock TTLs."""

    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._leases: dict[str, dict] = {}

    def acquire(self, run_id: str, owner: str, ttl_s: float) -> str:
        """Take ownership of a run. Returns the fence token.

        Fails with LeaseConflict if a live lease exists — the caller must
        wait for expiry or call take_over() deliberately.
        """
        now = self._clock()
        current = self._leases.get(run_id)
        if current is not None and current["expires_at"] > now:
            raise LeaseConflict(
                f"run {run_id!r} is owned by {current['owner']!r} "
                f"until {current['expires_at']:.1f}")
        token = uuid.uuid4().hex
        self._leases[run_id] = {
            "owner": owner, "token": token,
            "expires_at": now + ttl_s, "ttl_s": ttl_s,
        }
        return token

    def heartbeat(self, run_id: str, token: str) -> None:
        """Renew a live lease. A stale token renews nothing."""
        self._guard(run_id, token)
        lease = self._leases[run_id]
        lease["expires_at"] = self._clock() + lease["ttl_s"]

    def release(self, run_id: str, token: str) -> None:
        self._guard(run_id, token)
        del self._leases[run_id]

    def take_over(self, run_id: str, new_owner: str, ttl_s: float) -> str:
        """Seize an EXPIRED lease. The old token dies here — that is the
        fence. Taking over a live lease is LeaseConflict, not failover."""
        now = self._clock()
        current = self._leases.get(run_id)
        if current is not None and current["expires_at"] > now:
            raise LeaseConflict(
                f"run {run_id!r} is still live under {current['owner']!r}; "
                f"refusing to steal it")
        return self.acquire(run_id, new_owner, ttl_s)

    def _guard(self, run_id: str, token: str) -> dict:
        """The fence: only the current token-holder may mutate."""
        current = self._leases.get(run_id)
        if current is None:
            raise StaleFenceError(f"no lease exists for run {run_id!r}")
        if current["token"] != token:
            raise StaleFenceError(
                f"stale fence token for run {run_id!r}: owned by "
                f"{current['owner']!r}")
        if current["expires_at"] <= self._clock():
            raise StaleFenceError(
                f"lease for run {run_id!r} expired: heartbeat or take over")
        return current

    def guard(self, run_id: str, token: str) -> None:
        """Public fence check for guarded writers."""
        self._guard(run_id, token)


class CheckpointStore:
    """Where run snapshots live. Dict-backed here; production swaps this for
    the WAL-backed store (cf. Ch 10/Ch 11's SQLite discipline) without
    changing DurableRun. Shared by all workers — that is the point: the
    replacement reads what the dead worker wrote."""

    def __init__(self) -> None:
        self._store: dict[str, dict] = {}

    def put(self, run_id: str, snapshot: dict) -> None:
        self._store[run_id] = copy.deepcopy(snapshot)

    def get(self, run_id: str) -> dict | None:
        found = self._store.get(run_id)
        return copy.deepcopy(found) if found is not None else None


class DurableRun:
    """A long-running agent that survives its own death.

    Checkpoints are (state snapshot, audit-log seq) pairs. ``resume()``
    restores the snapshot and returns the evidence entries that arrived
    after the checkpoint — the replacement replays decisions it missed
    without re-executing actions the dead worker already took.
    """

    def __init__(self, run_id: str, leases: LeaseStore,
                 router, tenant_id: str,
                 checkpoints: CheckpointStore | None = None) -> None:
        self.run_id = run_id
        self._leases = leases
        self._router = router          # Ch 9 EvidenceRouter: the spine
        self._tenant_id = tenant_id
        self._token: str | None = None
        # Shared with the replacement worker: checkpoints outlive the process
        # that wrote them. Pass the same store to both DurableRun instances.
        self._checkpoints = checkpoints or CheckpointStore()

    def start(self, owner: str, ttl_s: float = 60.0) -> str:
        self._token = self._leases.acquire(self.run_id, owner, ttl_s)
        return self._token

    def heartbeat(self) -> None:
        self._leases.heartbeat(self.run_id, self._require_token())

    def guarded_write(self, fn, *args, **kwargs):
        """Run ``fn`` only if this worker still holds the fence.

        The zombie test: a worker whose lease expired gets StaleFenceError
        instead of writing a second, conflicting reality.
        """
        self._leases.guard(self.run_id, self._require_token())
        return fn(*args, **kwargs)

    def checkpoint(self, state: dict) -> int:
        """Snapshot state, stamped with the evidence-log position consumed.

        Returns the audit seq the snapshot is current through.
        """
        token = self._require_token()
        self._leases.guard(self.run_id, token)
        # "Consumed through" is the last seq seen, not the count: with zero
        # entries the worker is current through seq -1 (nothing seen yet).
        seq = len(self._router.audit) - 1
        self._checkpoints.put(self.run_id, {
            "state": copy.deepcopy(state),
            "through_seq": seq,
            "token": token,
        })
        return seq

    def resume(self, new_owner: str, ttl_s: float = 60.0
               ) -> tuple[dict, list[dict]]:
        """Take over (expired lease only) and return (state, new entries).

        ``state`` is the last checkpoint; ``new entries`` are the audit-log
        entries for this tenant with seq > checkpoint seq — the decisions
        the dead worker saw but never checkpointed. The replacement replays
        the *evidence*, not the *actions*.
        """
        self._token = self._leases.take_over(self.run_id, new_owner, ttl_s)
        cp = self._checkpoints.get(self.run_id)
        if cp is None:
            cp = {"state": {}, "through_seq": -1}
        state = copy.deepcopy(cp["state"])
        through = cp["through_seq"]
        entries = [e for e in self._router.audit.read(self._tenant_id)
                   if e["seq"] > through]
        return state, entries

    def _require_token(self) -> str:
        if self._token is None:
            raise StaleFenceError("run was never started")
        return self._token
