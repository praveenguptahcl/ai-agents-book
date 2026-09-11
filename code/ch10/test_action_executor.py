"""Tests for ch10's ActionExecutor against a fake Alpaca-style paper broker.

The fake lives here, not in the executor: the executor only ever sees the
broker protocol (submit callable + lookup). Unlike the first draft's fake,
this broker behaves like a real one: it ACCEPTS first (status "accepted",
non-terminal) and fills later — the fill is observed through lookup(), not
the submit response. Scenarios:

  1. Normal batch: 5 orders accepted, then polled to filled via await_fill.
  2. Timeout on order 3: accepted server-side but the response is lost;
     retry with the SAME key must produce exactly one order, no duplicate.
  3. Ambiguous commit: retries exhausted, order stuck in 'timeout';
     reconcile() finds the acceptance (-> 'open'), await_fill() -> filled.
  4. Settle window: a missing broker record is not proof of abandonment
     until settle_seconds have passed (fake clock, no sleeps).
  5. Sweep resilience: one key's lookup raising ConnectionError does not
     kill the sweep; the error is recorded per-order.
  6. Anti-corruption layer: BrokerAdapter translates raw transport errors
     into BrokerTimeout/BrokerError on BOTH the submit and lookup paths —
     including a forced reconciliation through the wrapped adapter.
  7. Terminal keys are never resubmitted; partials stay terminal.
"""

from datetime import datetime, timedelta, timezone

import pytest

from action_executor import (
    ActionExecutor,
    BrokerAdapter,
    BrokerError,
    BrokerTimeout,
    Ledger,
    wrap_broker,
)


class FakeAlpacaPaperBroker:
    """In-memory stand-in for Alpaca's paper trading API.

    Realistic behavior: submit ACCEPTS the order (non-terminal); the fill
    appears on a later lookup(), after ``lookups_before_terminal[key]``
    lookups. Server-side dedupe on the client order id (our
    idempotency_key) holds throughout: a second submit with a known key
    returns the existing order — it never creates a second fill. That
    dedupe is what makes executor retries safe.
    """

    def __init__(self):
        self.orders: dict[str, dict] = {}
        self.timeouts: set[str] = set()      # keys whose submit "loses" its response
        self.lookup_errors: dict[str, Exception] = {}  # key -> error raised by lookup()
        self.lookups_before_terminal: dict[str, int] = {}
        self.terminal_status: dict[str, str] = {}      # key -> filled|partial|rejected
        self.partial_frac: dict[str, float] = {}
        self.submit_count: dict[str, int] = {}
        self._seq = 0

    def __call__(self, order: dict, timeout: float) -> dict:
        key = order["idempotency_key"]
        self.submit_count[key] = self.submit_count.get(key, 0) + 1

        # Server-side idempotency: known key -> return existing, no duplicate.
        if key in self.orders:
            return dict(self.orders[key])

        self._seq += 1
        if order.get("qty", 0) <= 0:
            record = {
                "status": "rejected",
                "broker_id": f"fake-{self._seq:04d}",
                "filled_qty": 0.0,
                "avg_price": None,
                "reason": "qty must be positive",
            }
        else:
            # Accepted, not filled: the honest shape of a real broker response.
            record = {
                "status": "accepted",
                "broker_id": f"fake-{self._seq:04d}",
                "filled_qty": 0.0,
                "avg_price": None,
                "reason": "accepted by paper broker",
                "qty": order["qty"],
            }
            self.lookups_before_terminal.setdefault(key, 2)
            self.terminal_status.setdefault(key, "filled")
        self.orders[key] = record

        # Ambiguous commit: accepted server-side, but the caller never learns
        # about it — the response is "lost".
        if key in self.timeouts:
            self.timeouts.discard(key)
            raise BrokerTimeout(f"submit timed out for {key}")
        return dict(record)

    def lookup(self, key: str) -> dict | None:
        if key in self.lookup_errors:
            raise self.lookup_errors[key]
        record = self.orders.get(key)
        if record is None:
            return None
        if record["status"] in ("accepted", "new", "open"):
            remaining = self.lookups_before_terminal.get(key, 0)
            if remaining > 0:
                self.lookups_before_terminal[key] = remaining - 1
                remaining -= 1
            if remaining == 0:
                term = self.terminal_status.get(key, "filled")
                qty = record.get("qty", 0.0)
                frac = self.partial_frac.get(key, 1.0) if term == "partial" else 1.0
                record = {
                    "status": term,
                    "broker_id": record["broker_id"],
                    "filled_qty": 0.0 if term == "rejected" else qty * frac,
                    "avg_price": None if term == "rejected" else 100.0,
                    "reason": {"filled": "ok", "partial": "partial fill",
                               "rejected": "rejected at broker"}[term],
                }
                self.orders[key] = record
        return dict(record)


class FakeClock:
    """Injectable clock: drive the settle window without sleeping."""

    def __init__(self):
        self.t = datetime(2026, 9, 11, 9, 30, tzinfo=timezone.utc)

    def __call__(self):
        return self.t

    def advance(self, seconds: float):
        self.t += timedelta(seconds=seconds)


def make_order(i: int, symbol: str = "AMD", qty: float = 10.0) -> dict:
    side = "buy" if i % 2 == 0 else "sell"
    return {
        "idempotency_key": f"alphaforge-2026-09-11-{i:03d}",
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "order_type": "market",
    }


def make_executor(clock=None, **kw) -> ActionExecutor:
    kw.setdefault("backoff", 0.0)  # no sleeping in tests
    kw.setdefault("settle_seconds", 0.0)  # immediate abandon unless a test says otherwise
    ledger = Ledger(clock=clock) if clock is not None else Ledger()
    return ActionExecutor(ledger, **kw)


def await_all(ex: ActionExecutor, broker, keys) -> list[dict]:
    return [ex.await_fill(k, broker, poll_interval=0) for k in keys]


# 1. Normal batch: accepted first, polled to filled ---------------------------

def test_batch_of_five_accepted_then_filled():
    broker = FakeAlpacaPaperBroker()
    ex = make_executor()
    keys = [f"alphaforge-2026-09-11-{i:03d}" for i in range(5)]

    opens = [ex.execute(make_order(i), broker) for i in range(5)]

    # Submits return the honest broker shape: accepted, not filled.
    assert [r["status"] for r in opens] == ["open"] * 5
    assert all(r["broker_id"] for r in opens)  # acceptance carries a broker id
    assert all(r["filled_qty"] == 0.0 for r in opens)

    filled = await_all(ex, broker, keys)
    assert [r["status"] for r in filled] == ["filled"] * 5
    assert len({r["broker_id"] for r in filled}) == 5
    assert all(r["filled_qty"] == 10.0 for r in filled)
    for k in keys:
        assert broker.submit_count[k] == 1


def test_open_key_reexecute_refreshes_without_resubmitting():
    broker = FakeAlpacaPaperBroker()
    ex = make_executor()
    key = "alphaforge-2026-09-11-000"

    first = ex.execute(make_order(0), broker)
    assert first["status"] == "open"
    second = ex.execute(make_order(0), broker)  # e.g. operator double-click

    assert second["status"] == "open"  # refreshed from broker, not resubmitted
    assert broker.submit_count[key] == 1
    final = ex.await_fill(key, broker, poll_interval=0)
    assert final["status"] == "filled"
    assert broker.submit_count[key] == 1


# 2. Timeout retry with the same key: exactly one order -----------------------

def test_timeout_retry_same_key_no_duplicate():
    broker = FakeAlpacaPaperBroker()
    broker.timeouts.add("alphaforge-2026-09-11-003")  # order 3 loses its response
    ex = make_executor(max_retries=3)
    keys = [f"alphaforge-2026-09-11-{i:03d}" for i in range(5)]

    opens = [ex.execute(make_order(i), broker) for i in range(5)]

    assert [r["status"] for r in opens] == ["open"] * 5
    # Order 3 was submitted twice (original + one retry) ...
    assert broker.submit_count["alphaforge-2026-09-11-003"] == 2
    # ... but the broker holds exactly ONE order for that key: no duplicate.
    assert len(broker.orders) == 5
    order3 = ex.ledger.get("alphaforge-2026-09-11-003")
    assert order3["attempts"] == 2

    filled = await_all(ex, broker, keys)
    assert all(r["status"] == "filled" for r in filled)
    assert len(broker.orders) == 5  # still five — the retry never duplicated


# 3. Ambiguous commit: reconcile finds acceptance, await_fill finishes -------

def test_ambiguous_commit_resolved_by_reconcile_then_poll():
    broker = FakeAlpacaPaperBroker()
    broker.timeouts.add("alphaforge-2026-09-11-001")
    ex = make_executor(max_retries=0)  # one attempt, then give up retrying

    result = ex.execute(make_order(1), broker)

    # Retries exhausted: the executor refuses to guess. Status stays 'timeout'.
    assert result["status"] == "timeout"
    assert broker.submit_count["alphaforge-2026-09-11-001"] == 1

    # The sweep asks the broker what actually happened: accepted, not filled.
    swept = ex.reconcile(broker)
    assert len(swept) == 1
    assert swept[0]["status"] == "open"
    assert swept[0]["broker_id"] is not None

    # The poll transition drives it to terminal.
    final = ex.await_fill("alphaforge-2026-09-11-001", broker, poll_interval=0)
    assert final["status"] == "filled"
    assert final["filled_qty"] == 10.0
    assert ex.ledger.pending_keys() == []  # nothing left ambiguous


def test_await_fill_max_wait_leaves_open_for_later_sweep():
    broker = FakeAlpacaPaperBroker()
    key = "alphaforge-2026-09-11-000"
    broker.lookups_before_terminal[key] = 10 ** 9  # effectively never fills
    ex = make_executor()

    ex.execute(make_order(0), broker)
    out = ex.await_fill(key, broker, poll_interval=0, max_wait=0)

    assert out["status"] == "open"  # not forced, not guessed: left for the sweep
    assert key in ex.ledger.pending_keys()


# 4. Settle window: missing record is not proof of abandonment ----------------

def test_settle_window_blocks_premature_abandonment():
    clock = FakeClock()
    broker = FakeAlpacaPaperBroker()
    ex = make_executor(clock=clock, settle_seconds=300)
    # Simulate a crash-after-ledger-write: ledger says submitted, broker empty.
    ex.ledger.record_attempt("ghost-key", make_order(9), 1)

    swept = ex.reconcile(broker)

    # The lookup found nothing, but the row is 0 seconds old: racing, not dead.
    assert swept[0]["status"] == "submitted"
    assert swept[0]["status"] != "abandoned"
    assert ex.ledger.pending_keys() == ["ghost-key"]  # still owed a decision

    # After the settle window, the same missing record IS proof of abandonment.
    clock.advance(301)
    swept = ex.reconcile(broker)
    assert swept[0]["status"] == "abandoned"
    assert ex.ledger.pending_keys() == []
    assert broker.lookup("ghost-key") is None  # safe to resubmit with same key


def test_reconcile_abandons_immediately_with_zero_settle_window():
    broker = FakeAlpacaPaperBroker()
    ex = make_executor(settle_seconds=0.0)
    ex.ledger.record_attempt("ghost-key", make_order(9), 1)

    resolved = ex.reconcile(broker)

    assert resolved[0]["status"] == "abandoned"


# 5. Sweep resilience: one key's network failure doesn't kill the sweep ------

def test_reconcile_sweep_survives_per_order_network_failure():
    broker = FakeAlpacaPaperBroker()
    ex = make_executor(max_retries=0, settle_seconds=0.0)

    broker.timeouts.add("alphaforge-2026-09-11-001")
    ex.execute(make_order(1), broker)  # ends 'timeout'; broker accepted it
    ex.ledger.record_attempt("alphaforge-2026-09-11-002", make_order(2), 1)
    broker.lookup_errors["alphaforge-2026-09-11-002"] = ConnectionError(
        "connection reset by peer"
    )

    swept = ex.reconcile(broker)  # must not raise

    by_key = {r["idempotency_key"]: r for r in swept}
    assert by_key["alphaforge-2026-09-11-001"]["status"] == "open"  # resolved fine
    failed = by_key["alphaforge-2026-09-11-002"]
    assert failed["status"] == "submitted"  # untouched, still owed a decision
    assert "ConnectionError" in failed["reconcile_error"]
    assert "alphaforge-2026-09-11-002" in ex.ledger.pending_keys()

    # Next sweep retries it: clear the fault, the order resolves.
    del broker.lookup_errors["alphaforge-2026-09-11-002"]
    swept = ex.reconcile(broker)
    by_key = {r["idempotency_key"]: r for r in swept}
    assert by_key["alphaforge-2026-09-11-002"]["status"] == "abandoned"
    assert by_key["alphaforge-2026-09-11-002"]["reconcile_error"] is None


# 6. Anti-corruption layer -----------------------------------------------------

def test_wrap_broker_converts_raw_transport_errors():
    def raw_reset(order, timeout):
        raise ConnectionError("connection reset by peer")

    def raw_timeout(order, timeout):
        raise TimeoutError("socket timed out")

    def raw_ok(order, timeout):
        return {"status": "accepted", "broker_id": "w-1"}

    with pytest.raises(BrokerError, match="connection reset"):
        wrap_broker(raw_reset)({}, 1.0)
    with pytest.raises(BrokerTimeout, match="transport timeout"):
        wrap_broker(raw_timeout)({}, 1.0)
    # Protocol exceptions pass through unchanged, not double-wrapped.
    with pytest.raises(BrokerTimeout):
        wrap_broker(lambda o, t: (_ for _ in ()).throw(BrokerTimeout("x")))({}, 1.0)
    assert wrap_broker(raw_ok)({}, 1.0)["broker_id"] == "w-1"


def test_executor_recovers_through_wrapped_broker():
    # This exercises only the submit path of the adapter (the fake is a
    # bare function, so there is nothing to reconcile against). The lookup
    # path gets its own dedicated tests below — the old suite's blind spot.
    calls = {"n": 0}

    def flaky(order, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("connection reset by peer")  # raw, unwrapped
        return {"status": "accepted", "broker_id": "w-1", "filled_qty": 0.0,
                "avg_price": None, "reason": "ok"}

    ex = make_executor(max_retries=3)
    rec = ex.execute(make_order(0), wrap_broker(flaky))

    # The raw ConnectionError became BrokerError -> timeout -> same-key retry.
    assert rec["status"] == "open"
    assert rec["attempts"] == 2
    assert calls["n"] == 2


def test_adapter_lookup_translates_raw_transport_errors():
    """The regression this chapter is honest about: lookup() is a network
    call too, and the adapter must translate its failures. The first
    (function-decorator) version of wrap_broker had no lookup at all —
    reconcile_key() crashed with AttributeError the first time a wrapped
    broker went to reconcile."""

    class RawBroker:
        def lookup(self, key):
            raise ConnectionError("connection reset by peer")

    adapter = wrap_broker(RawBroker())

    # The adapter implements the full protocol, not just submit ...
    assert isinstance(adapter, BrokerAdapter)
    # ... and the lookup path speaks the protocol's exceptions.
    with pytest.raises(BrokerError, match="connection reset"):
        adapter.lookup("any-key")


def test_reconcile_through_wrapped_adapter_forces_lookup():
    """End-to-end sweep through the adapter: raw transport failures on the
    lookup path are translated AND trapped per key, and a wrapped broker
    reconciles to open without AttributeError. This is the test the old
    suite was missing."""
    raw = FakeAlpacaPaperBroker()
    wrapped = wrap_broker(raw)
    assert isinstance(wrapped, BrokerAdapter)
    ex = make_executor(max_retries=0, settle_seconds=0.0)
    key = "alphaforge-2026-09-11-010"

    raw.timeouts.add(key)
    ex.execute(make_order(10), wrapped)  # submit times out; broker accepted it
    assert ex.ledger.get(key)["status"] == "timeout"
    assert raw.submit_count[key] == 1

    # The lookup path also hits the network: fault it with a RAW error.
    raw.lookup_errors[key] = ConnectionError("connection reset by peer")
    swept = ex.reconcile(wrapped)  # must not raise, must not AttributeError

    by_key = {r["idempotency_key"]: r for r in swept}
    failed = by_key[key]
    assert failed["status"] == "timeout"  # untouched; the sweep trapped it
    # The recorded error shows the TRANSLATED taxonomy (BrokerError), not the
    # raw transport exception — proof the adapter translated before trapping.
    assert "connection reset" in failed["reconcile_error"]
    assert failed["reconcile_error"].startswith("BrokerError")
    # The raw error was translated into the protocol taxonomy first —
    # prove it by calling reconcile_key directly on the faulty lookup.
    with pytest.raises(BrokerError, match="connection reset"):
        ex.reconcile_key(key, wrapped)

    # Clear the fault: the next sweep resolves the key through the adapter.
    del raw.lookup_errors[key]
    swept = ex.reconcile(wrapped)
    by_key = {r["idempotency_key"]: r for r in swept}
    assert by_key[key]["status"] == "open"  # broker truth: accepted, pending
    assert by_key[key]["reconcile_error"] is None
    final = ex.await_fill(key, wrapped, poll_interval=0)
    assert final["status"] == "filled"
    assert ex.ledger.pending_keys() == []


# 7. Terminal keys are never resubmitted ---------------------------------------

def test_reexecute_terminal_key_never_resubmits():
    broker = FakeAlpacaPaperBroker()
    ex = make_executor()
    key = "alphaforge-2026-09-11-000"

    ex.execute(make_order(0), broker)
    first = ex.await_fill(key, broker, poll_interval=0)
    assert first["status"] == "filled"
    second = ex.execute(make_order(0), broker)  # operator double-click

    assert broker.submit_count[key] == 1
    assert second["broker_id"] == first["broker_id"]
    assert second["status"] == "filled"


def test_reexecute_after_timeout_reconciles_before_resubmitting():
    broker = FakeAlpacaPaperBroker()
    broker.timeouts.add("alphaforge-2026-09-11-002")
    ex = make_executor(max_retries=0)
    key = "alphaforge-2026-09-11-002"

    ex.execute(make_order(2), broker)          # ends in 'timeout', broker accepted it
    again = ex.execute(make_order(2), broker)  # new call: reconcile, not resubmit

    assert broker.submit_count[key] == 1  # no second submit
    assert again["status"] == "open"       # broker truth: accepted, fill pending
    final = ex.await_fill(key, broker, poll_interval=0)
    assert final["status"] == "filled"
    assert len(broker.orders) == 1


# 8. Partials and rejections are terminal ---------------------------------------

def test_partial_fill_recorded_as_terminal():
    broker = FakeAlpacaPaperBroker()
    key = "alphaforge-2026-09-11-004"
    broker.terminal_status[key] = "partial"
    broker.partial_frac[key] = 0.5
    ex = make_executor()

    opened = ex.execute(make_order(4, qty=100.0), broker)
    assert opened["status"] == "open"
    result = ex.await_fill(key, broker, poll_interval=0)

    assert result["status"] == "partial"
    assert result["filled_qty"] == 50.0
    # The executor does NOT top up the remainder: that is a new proposal,
    # a new decision, a new idempotency key — not the executor's call.
    assert broker.submit_count[key] == 1


def test_rejected_order_recorded():
    broker = FakeAlpacaPaperBroker()
    ex = make_executor()

    result = ex.execute(make_order(7, qty=0), broker)

    assert result["status"] == "rejected"
    assert "positive" in result["reason"]
