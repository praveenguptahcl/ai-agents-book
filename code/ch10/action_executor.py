"""Idempotent order execution for the AlphaForge / WealthForge paper-trading agent.

This module owns exactly one job: turn a *validated* order proposal into
exactly-one external effect at the broker. It never decides *what* to trade
(that was the decision plane's job in Part III); it guarantees that
submitting the same order twice — because of retries, crashes, timeouts,
or operator impatience — can never create two fills.

The mechanisms that make this true:

1. **Idempotency keys.** Every order carries an ``idempotency_key`` derived
   deterministically from the validated proposal (never a fresh UUID per
   attempt — that would defeat the whole scheme). The broker deduplicates
   on this key: a second submit with the same key returns the *existing*
   order instead of creating a new one.
2. **Write-ahead ledger.** The executor records its intent in a local ledger
   *before* calling the broker. If the process dies mid-submit, the ledger
   still knows the order was attempted, and ``reconcile()`` can resolve the
   ambiguity by asking the broker what it actually did.
3. **Open-state tracking.** Real brokers do not fill synchronously: they
   *accept* first (``new``/``accepted``) and fill later. The ledger models
   this as the ``open`` state, driven to terminal by ``await_fill()``
   (poll-based) or the scheduled ``reconcile()`` sweep.
4. **Settle window.** A missing broker record is not proof of abandonment —
   the lookup may be racing a just-sent submit or hitting a lagging read
   replica. ``reconcile()`` only marks a key ``abandoned`` after
   ``settle_seconds`` have passed since the ledger row was written.

Broker protocol (injected callable, so tests use a fake and production
wraps the real paper-broker SDK with ``wrap_broker``):

    broker(order, timeout) -> dict
        Submit ``order``. Returns a dict with at least:
        {"status": "filled"|"partial"|"rejected",   # terminal
                   "accepted"|"new"|"open",          # non-terminal: accepted, not filled
         "broker_id": str, "filled_qty": float,
         "avg_price": float, "reason": str}
        Raises BrokerTimeout / BrokerError when the outcome is unknown.

    broker.lookup(idempotency_key) -> dict | None
        Return the broker's record for a previously submitted key,
        or None if the broker has no record of it *yet*.

The injected callable is an **anti-corruption layer**: it must translate
raw transport failures (connection resets, socket timeouts) into
``BrokerTimeout``/``BrokerError`` before they reach the executor — on
*both* network paths, submit and lookup. ``wrap_broker()`` returns a
``BrokerAdapter`` that does exactly this for a naive broker object.
Anything else that escapes is treated as a programming bug and propagates —
the executor never mistakes an unexpected exception for a timeout.

Stdlib only: sqlite3, time, datetime.
"""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone


class BrokerTimeout(Exception):
    """The submit call timed out. Outcome unknown: the broker may or may not
    have received and filled the order. It is never safe to assume either."""


class BrokerError(Exception):
    """Transient broker-side failure (5xx, connection reset, ...). Like a
    timeout, the outcome is unknown — the request may already be applied."""


class BrokerAdapter:
    """Anti-corruption layer for the broker boundary, in class form.

    The first version of this was a function decorator wrapping the submit
    callable — and it was *wrong*: a decorator returns a bare function,
    which silently strips every other attribute the protocol needs. The
    first time a decorated broker went to reconcile, ``broker.lookup(key)``
    crashed with ``AttributeError``. The broker is not a function; it is a
    *protocol* (submit + lookup), and the adapter must implement the whole
    protocol.

    The adapter wraps a raw broker object and applies the same exception
    translation to both network paths: raw ``TimeoutError`` becomes
    ``BrokerTimeout`` (outcome unknown, safe to retry with the same key);
    raw ``ConnectionError``/``OSError`` becomes ``BrokerError``. Protocol
    exceptions pass through untouched, and anything else — including a
    missing ``lookup`` on the wrapped object — propagates as the
    programming bug it is. The executor's
    ``except (BrokerTimeout, BrokerError)`` clause is only correct because
    this adapter guarantees the universe of inputs on every path that
    touches the network.
    """

    def __init__(self, raw):
        self._raw = raw

    def __call__(self, order: dict, timeout: float) -> dict:
        try:
            return self._raw(order, timeout)
        except (BrokerTimeout, BrokerError):
            raise
        except TimeoutError as exc:
            raise BrokerTimeout(
                f"transport timeout after {timeout}s: {exc}"
            ) from exc
        except (ConnectionError, OSError) as exc:
            raise BrokerError(f"transport failure: {exc}") from exc

    def lookup(self, key: str) -> dict | None:
        """Lookup is a network call too — it gets the same translation as
        submit. Without this, a reset socket during the end-of-day sweep
        would arrive at the executor wearing the wrong exception."""
        try:
            return self._raw.lookup(key)
        except (BrokerTimeout, BrokerError):
            raise
        except TimeoutError as exc:
            raise BrokerTimeout(f"transport timeout on lookup: {exc}") from exc
        except (ConnectionError, OSError) as exc:
            raise BrokerError(f"transport failure on lookup: {exc}") from exc


def wrap_broker(raw) -> BrokerAdapter:
    """Convenience constructor: adapt a raw broker object at the boundary.

    ``wrap_broker(sdk_client)`` returns a ``BrokerAdapter`` implementing the
    full broker protocol (submit + lookup) with transport failures mapped to
    the ``BrokerTimeout``/``BrokerError`` taxonomy. Wrap once, at the
    boundary, and the executor's narrow ``except`` clause stays honest on
    every path that touches the network.
    """
    return BrokerAdapter(raw)


TERMINAL = frozenset({"filled", "partial", "rejected", "abandoned"})
PENDING = frozenset({"submitted", "timeout", "open"})
# Broker-side non-terminal statuses: accepted, but not yet filled.
OPEN_STATUSES = frozenset({"accepted", "new", "open"})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Ledger:
    """Write-ahead record of every execution attempt, keyed by idempotency key.

    The ledger is the executor's memory across crashes and retries. It is
    written *before* the broker is called and updated as outcomes arrive, so
    no order can ever be in a state the operator cannot inspect.

    ``clock`` is an injectable callable returning an aware datetime, so
    tests can drive the settle window with a fake clock instead of sleeps.
    """

    def __init__(self, path: str = ":memory:", clock=None):
        self._clock = clock or _utcnow
        self.conn = sqlite3.connect(path, check_same_thread=False, timeout=30.0)
        # WAL mode: the trading thread may be submitting while a scheduler
        # thread runs reconcile(). WAL lets readers proceed during a write
        # instead of failing with "database is locked". (No-op for
        # :memory: databases, which never journal to disk — harmless there.)
        # The 30s busy timeout is cheap insurance: under write contention
        # SQLite waits instead of failing instantly. For heavy parallel
        # writers, serialize behind an explicit threading.Lock.
        # NOTE: check_same_thread=False lifts the interpreter guard, not the
        # need for discipline. Keep a single writer (or serialize writers
        # with a lock) in production; concurrent writes from two threads can
        # still interleave at the SQL level.
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS executions (
                   idempotency_key TEXT PRIMARY KEY,
                   symbol         TEXT,
                   side           TEXT,
                   qty            REAL,
                   order_type     TEXT,
                   status         TEXT,     -- submitted|open|filled|partial|rejected|timeout|abandoned
                   broker_id      TEXT,
                   filled_qty     REAL,
                   avg_price      REAL,
                   reason         TEXT,
                   reconcile_error TEXT,    -- last per-order sweep failure, if any
                   attempts       INTEGER,
                   updated_at     TEXT
               )"""
        )
        self.conn.commit()

    def get(self, key: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM executions WHERE idempotency_key = ?", (key,)
        ).fetchone()
        return dict(row) if row else None

    def row_age_seconds(self, key: str) -> float:
        """How long since this row was last written. Drives the settle window:
        a young row with no broker record is *racing*, not abandoned."""
        row = self.get(key)
        written = datetime.fromisoformat(row["updated_at"])
        return (self._clock() - written).total_seconds()

    def record_attempt(self, key: str, order: dict, attempts: int) -> None:
        """Upsert the intent row. Called BEFORE the broker is touched."""
        self.conn.execute(
            """INSERT INTO executions
                   (idempotency_key, symbol, side, qty, order_type,
                    status, attempts, updated_at)
               VALUES (?, ?, ?, ?, ?, 'submitted', ?, ?)
               ON CONFLICT(idempotency_key) DO UPDATE SET
                   status='submitted', attempts=excluded.attempts,
                   updated_at=excluded.updated_at""",
            (
                key,
                order.get("symbol"),
                order.get("side"),
                order.get("qty"),
                order.get("order_type"),
                attempts,
                self._clock().isoformat(),
            ),
        )
        self.conn.commit()

    def mark_timeout(self, key: str, attempts: int, reason: str) -> None:
        self.conn.execute(
            """UPDATE executions
               SET status='timeout', attempts=?, reason=?, updated_at=?
               WHERE idempotency_key=?""",
            (attempts, reason, self._clock().isoformat(), key),
        )
        self.conn.commit()

    def record_terminal(self, key: str, response: dict, attempts: int) -> dict:
        """Adopt a definitive broker outcome as the ledger's terminal state."""
        status = response.get("status")
        if status not in ("filled", "partial", "rejected"):
            raise ValueError(f"broker returned non-terminal status: {status!r}")
        if not response.get("broker_id"):
            raise ValueError("broker response missing broker_id")
        self.conn.execute(
            """UPDATE executions
               SET status=?, broker_id=?, filled_qty=?, avg_price=?,
                   reason=?, reconcile_error=NULL, attempts=?, updated_at=?
               WHERE idempotency_key=?""",
            (
                status,
                response["broker_id"],
                response.get("filled_qty", 0.0),
                response.get("avg_price"),
                response.get("reason", ""),
                attempts,
                self._clock().isoformat(),
                key,
            ),
        )
        self.conn.commit()
        return self.get(key)

    def mark_open(self, key: str, response: dict, attempts: int) -> dict:
        """The broker accepted the order but has not filled it yet. Record
        the broker id and wait in ``open`` — await_fill() or the reconcile
        sweep will drive it to terminal."""
        if not response.get("broker_id"):
            raise ValueError("broker accepted the order but returned no broker_id")
        self.conn.execute(
            """UPDATE executions
               SET status='open', broker_id=?, filled_qty=0.0,
                   reason=?, reconcile_error=NULL, attempts=?, updated_at=?
               WHERE idempotency_key=?""",
            (
                response["broker_id"],
                response.get("reason", "accepted by broker; fill pending"),
                attempts,
                self._clock().isoformat(),
                key,
            ),
        )
        self.conn.commit()
        return self.get(key)

    def apply_broker_response(self, key: str, response: dict, attempts: int) -> dict:
        """Route any broker response — terminal or acceptance — to the right
        ledger transition. Unknown statuses are a bug, raised loudly."""
        status = response.get("status")
        if status in ("filled", "partial", "rejected"):
            return self.record_terminal(key, response, attempts)
        if status in OPEN_STATUSES:
            return self.mark_open(key, response, attempts)
        raise ValueError(f"broker returned unknown status: {status!r}")

    def mark_abandoned(self, key: str, reason: str) -> dict:
        """The broker has no record of this key *after the settle window*:
        it never received the order, so resubmitting with the same key is
        safe."""
        self.conn.execute(
            "UPDATE executions SET status='abandoned', reason=?, "
            "reconcile_error=NULL, updated_at=? "
            "WHERE idempotency_key=?",
            (reason, self._clock().isoformat(), key),
        )
        self.conn.commit()
        return self.get(key)

    def mark_reconcile_error(self, key: str, error: str) -> dict:
        """One sweep failed to reach the broker for this key. The row keeps
        its status (still pending) and carries the error for the operator;
        the next sweep retries it."""
        self.conn.execute(
            "UPDATE executions SET reconcile_error=?, updated_at=? "
            "WHERE idempotency_key=?",
            (error, self._clock().isoformat(), key),
        )
        self.conn.commit()
        return self.get(key)

    def pending_keys(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT idempotency_key FROM executions "
            "WHERE status IN ('submitted','timeout','open')"
        ).fetchall()
        return [r["idempotency_key"] for r in rows]


class ActionExecutor:
    """Runs validated orders against a broker with exactly-once semantics.

    Rules, in order of precedence:
      1. A key with a terminal ledger record is never resubmitted (cached).
      2. A key stuck in submitted/timeout/open is reconciled against the
         broker BEFORE any new submit — never resubmit on an ambiguous
         commit.
      3. Timeouts retry with the SAME idempotency key and exponential
         backoff; the broker's key dedupe is what makes the retry unable
         to duplicate.
      4. Retries exhausted leaves the order in 'timeout'; reconcile()
         resolves it later against broker truth.
      5. A broker record that is missing is only proof of abandonment
         after ``settle_seconds`` — before that, the lookup may be racing
         the submit or reading a lagging replica.

    ``broker`` must be wrapped with ``wrap_broker`` (or equivalent) so the
    executor only ever sees ``BrokerTimeout``/``BrokerError``.
    """

    def __init__(
        self,
        ledger: Ledger,
        timeout: float = 5.0,
        max_retries: int = 3,
        backoff: float = 0.5,
        settle_seconds: float = 60.0,
    ):
        self.ledger = ledger
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff
        self.settle_seconds = settle_seconds

    def execute(self, order: dict, broker) -> dict:
        """Execute one validated order. Returns the ledger record, which may
        be terminal (filled/partial/rejected), ``open`` (accepted, fill
        pending — drive it with await_fill), or still pending (timeout/
        submitted — resolve with reconcile)."""
        key = order["idempotency_key"]

        prior = self.ledger.get(key)
        if prior is not None:
            if prior["status"] in TERMINAL:
                return prior  # decided already; never resubmit
            if prior["status"] in PENDING:
                # Ambiguous from a previous run: ask the broker first.
                resolved = self.reconcile_key(key, broker)
                if resolved is None or resolved["status"] != "abandoned":
                    return resolved
                # Broker never saw it (proven, past the settle window) —
                # fall through and submit with the same key.

        attempts = 0
        while True:
            attempts += 1
            self.ledger.record_attempt(key, order, attempts)
            try:
                response = broker(order, self.timeout)
            except (BrokerTimeout, BrokerError) as exc:
                self.ledger.mark_timeout(key, attempts, f"{type(exc).__name__}: {exc}")
                if attempts > self.max_retries:
                    # Give up retrying; the order stays 'timeout' until
                    # reconcile() resolves the ambiguity. Never guess.
                    return self.ledger.get(key)
                if self.backoff:
                    time.sleep(self.backoff * 2 ** (attempts - 1))
                continue  # retry with the SAME key — no duplicate possible
            # Terminal fills/rejections land here; acceptances land in 'open'.
            return self.ledger.apply_broker_response(key, response, attempts)

    def reconcile_key(self, key: str, broker) -> dict | None:
        """Resolve one ambiguous key against broker truth. The broker wins —
        but a *missing* broker record only wins after the settle window.
        May raise transport errors; ``reconcile()`` traps those per key."""
        row = self.ledger.get(key)
        if row is None:
            return None
        record = broker.lookup(key)
        if record is None:
            if self.ledger.row_age_seconds(key) < self.settle_seconds:
                # Too early to prove abandonment: the submit may still be in
                # flight, or this read may have hit a lagging replica.
                # Leave the row pending; a later sweep will decide.
                return row
            return self.ledger.mark_abandoned(
                key,
                "broker has no record of this key after the settle window; "
                "safe to resubmit",
            )
        return self.ledger.apply_broker_response(key, record, row.get("attempts", 0))

    def reconcile(self, broker) -> list[dict]:
        """Resolve every non-terminal execution. The end-of-day sweep:
        no order may remain in an unknown state.

        One broker hiccup must not kill the sweep: transport failures are
        trapped per key, recorded on the row, and retried by the next sweep.
        """
        results = []
        for k in self.ledger.pending_keys():
            try:
                results.append(self.reconcile_key(k, broker))
            except (BrokerTimeout, BrokerError, OSError) as exc:
                results.append(
                    self.ledger.mark_reconcile_error(
                        k, f"{type(exc).__name__}: {exc}"
                    )
                )
        return results

    def await_fill(
        self,
        key: str,
        broker,
        poll_interval: float = 1.0,
        max_wait: float = 30.0,
    ) -> dict | None:
        """Poll-based transition: ``open`` -> terminal.

        Repeatedly reconciles the key until the broker reports a terminal
        status or ``max_wait`` elapses. A poll failure is recorded on the
        row and returned (not raised) so the caller can retry; an
        unexpired ``open`` row is simply returned as-is for the scheduled
        sweep to keep driving.

        Production note: replace this poll loop with the broker's websocket
        order-update stream. The state machine is identical — only the
        trigger changes from poll to push — and reconcile() remains the
        backstop either way.
        """
        deadline = time.monotonic() + max_wait
        record = self.ledger.get(key)
        while record is not None and record["status"] == "open":
            if time.monotonic() >= deadline:
                return record
            if poll_interval > 0:
                time.sleep(poll_interval)
            try:
                record = self.reconcile_key(key, broker)
            except (BrokerTimeout, BrokerError, OSError) as exc:
                return self.ledger.mark_reconcile_error(
                    key, f"{type(exc).__name__}: {exc}"
                )
        return record
