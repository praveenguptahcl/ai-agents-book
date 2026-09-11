"""Adversarial tests for Chapter 14's operating machinery.

The tests attack the three components the way production will:
- TraceWriter: concurrency, wedged consumers, poisoned entries.
- ModelGateway: dead providers, unpriced models, stale caches.
- DurableRun: zombie writers, stolen leases, mid-night deaths.
"""

import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ch09"))

from trace_writer import TraceWriter, EvidenceWriterDown
from model_gateway import (ModelGateway, ProviderResult, GatewayResult,
                           ProviderOutage, ProviderContractViolation)
from durable import (DurableRun, LeaseStore, CheckpointStore, StaleFenceError,
                    LeaseConflict)
from evidence import EvidenceRouter


@dataclass(frozen=True)
class FakeSession:
    """Stands in for Ch 6's TenantSession: an object, never a string."""
    tenant_id: str


SESSION = FakeSession("t-ava")
SECRET = b"test-hmac-secret-16b!"


# ---------------------------------------------------------------------------
# TraceWriter
# ---------------------------------------------------------------------------

class RecordingRouter:
    """Test double for EvidenceRouter: records emissions, optionally slow."""

    def __init__(self, gate: threading.Event | None = None,
                 poison_on: str | None = None):
        self.emitted: list[tuple[int, str, dict]] = []
        self._lock = threading.Lock()
        self._gate = gate
        self._poison_on = poison_on
        self.entered = threading.Event()  # set when the consumer calls emit

    def emit(self, session, event_type, payload):
        self.entered.set()
        if self._gate is not None:
            assert self._gate.wait(timeout=10.0), "test gate never opened"
        if self._poison_on is not None and payload.get("id") == self._poison_on:
            raise RuntimeError("router exploded on poisoned entry")
        with self._lock:
            self.emitted.append((session, event_type, dict(payload)))


def test_writer_preserves_submission_order_under_concurrency():
    router = RecordingRouter()
    writer = TraceWriter(router, capacity=10_000)
    try:
        seqs: list[tuple[int, int]] = []
        lock = threading.Lock()

        def producer(base: int):
            for i in range(50):
                seq = writer.submit(SESSION, "tool_call", {"id": base + i})
                with lock:
                    seqs.append((seq, base + i))

        threads = [threading.Thread(target=producer, args=(t * 1000,))
                   for t in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert writer.flush(timeout=10.0)
        # Every submission got a unique, gapless seq; emissions are in seq order.
        returned = sorted(s for s, _ in seqs)
        assert returned == list(range(400))
        id_by_seq = {s: i for s, i in seqs}
        emitted_ids = [p["id"] for _, _, p in router.emitted]
        assert emitted_ids == [id_by_seq[s] for s in sorted(id_by_seq)]
    finally:
        writer.close()


def test_writer_backpressure_pauses_the_agent_instead_of_dropping():
    gate = threading.Event()
    router = RecordingRouter(gate=gate)
    writer = TraceWriter(router, capacity=2, put_timeout=30.0)
    try:
        done = threading.Event()

        def flood():
            for i in range(4):  # capacity is 2; the 3rd+ must wait for drain
                writer.submit(SESSION, "tool_call", {"id": i})
            done.set()

        t = threading.Thread(target=flood)
        t.start()
        time.sleep(0.3)
        assert not done.is_set(), "producer finished without backpressure"
        gate.set()  # consumer drains; the paused agent resumes
        t.join(timeout=10.0)
        assert done.is_set()
        assert writer.flush(timeout=10.0)
        assert len(router.emitted) == 4  # nothing was lost
    finally:
        gate.set()
        writer.close()


def test_writer_wedged_consumer_fails_loud_not_silent():
    gate = threading.Event()  # never opened: the consumer is wedged
    router = RecordingRouter(gate=gate)
    writer = TraceWriter(router, capacity=1, put_timeout=0.3)
    try:
        writer.submit(SESSION, "tool_call", {"id": 0})
        # Wait until the consumer has TAKEN #0 and is wedged inside emit.
        # Now the queue is empty but the consumer cannot drain: #1 fills it,
        # and #2 must fail loudly rather than buffer into the void.
        assert router.entered.wait(timeout=5.0), "consumer never took entry 0"
        writer.submit(SESSION, "tool_call", {"id": 1})  # fills the queue
        with pytest.raises(EvidenceWriterDown):
            writer.submit(SESSION, "tool_call", {"id": 2})  # wedged: loud
        assert writer.stats()["backpressure_events"] == 1
    finally:
        gate.set()
        try:
            writer.close()
        except EvidenceWriterDown:
            pass


def test_writer_poisoned_entry_marks_writer_failed():
    router = RecordingRouter(poison_on="poison")
    writer = TraceWriter(router, capacity=100)
    writer.submit(SESSION, "tool_call", {"id": "ok-1"})
    writer.submit(SESSION, "tool_call", {"id": "poison"})
    time.sleep(0.5)  # let the consumer hit the poison
    # The writer is now failed: new evidence is REFUSED, not buffered voidward.
    with pytest.raises(EvidenceWriterDown):
        writer.submit(SESSION, "tool_call", {"id": "after"})
    with pytest.raises(EvidenceWriterDown):
        writer.flush(timeout=2.0)
    assert writer.stats()["failed"]


def test_writer_flush_and_close_are_complete():
    router = RecordingRouter()
    with TraceWriter(router, capacity=100) as writer:
        for i in range(25):
            writer.submit(SESSION, "broker_response", {"id": i})
        assert writer.flush(timeout=10.0)
        stats = writer.stats()
        assert stats["submitted"] == 25 and stats["emitted"] == 25
    assert len(router.emitted) == 25  # close() drained everything


def test_writer_integrates_with_real_ch09_router():
    """The writer drives Ch 9's actual EvidenceRouter, not just a double."""
    real = EvidenceRouter(secret=SECRET)
    writer = TraceWriter(real, capacity=100)
    try:
        writer.submit(SESSION, "tool_call", {"tool": "submit_order"})
        assert writer.flush(timeout=10.0)
        ok, bad = real.verify()
        assert ok and bad is None
        assert len(real.audit.read("t-ava")) == 1
    finally:
        writer.close()


# ---------------------------------------------------------------------------
# ModelGateway
# ---------------------------------------------------------------------------

def _fake_provider(model: str, text: str = "ok", t_in: int = 100,
                   t_out: int = 50):
    def call(request):
        return ProviderResult(text=text, model=model,
                              tokens_in=t_in, tokens_out=t_out)
    return call


def _outage_provider(request):
    raise ProviderOutage("primary is down")


def _gateway(**overrides):
    routes = {"summarize": "small-1", "grade": "large-1"}
    providers = {"small-1": _fake_provider("small-1"),
                 "large-1": _fake_provider("large-1")}
    prices = {"small-1": (0.10, 0.30), "large-1": (2.00, 6.00)}
    fallbacks = {"large-1": ["small-1"]}
    kw = dict(routes=routes, providers=providers, prices_per_1k=prices,
              fallbacks=fallbacks, intent_hash="intent-v1")
    kw.update(overrides)
    return ModelGateway(**kw)


def test_gateway_routes_by_task_class_and_rejects_unknown():
    gw = _gateway()
    assert gw.route("summarize") == "small-1"
    assert gw.route("grade") == "large-1"
    with pytest.raises(KeyError):
        gw.route("write-sonnet")  # unknown class: fail closed, don't guess


def test_gateway_falls_back_on_provider_outage():
    providers = {"large-1": _outage_provider,
                 "small-1": _fake_provider("small-1", text="degraded")}
    gw = _gateway(providers=providers)
    result = gw.complete("grade", {"q": "score this thesis"})
    assert result.model == "small-1" and result.text == "degraded"
    assert not result.cached
    assert gw.ledger()[-1]["fallback"] is True


def test_gateway_all_providers_down_raises():
    providers = {"large-1": _outage_provider}  # fallback small-1 missing too
    gw = _gateway(providers=providers,
                  fallbacks={"large-1": ["small-1"]})
    with pytest.raises(ProviderOutage):
        gw.complete("grade", {"q": "score this thesis"})


def test_gateway_cache_avoids_the_second_call():
    calls = []

    def counting(request):
        calls.append(request)
        return ProviderResult(text="cached-answer", model="small-1",
                              tokens_in=10, tokens_out=5)

    gw = _gateway(providers={"small-1": counting,
                             "large-1": _fake_provider("large-1")})
    first = gw.complete("summarize", {"doc": "earnings call"})
    second = gw.complete("summarize", {"doc": "earnings call"})
    assert len(calls) == 1
    assert second.cached and second.cost_usd == 0.0
    assert first.text == second.text


def test_gateway_cache_invalidates_on_intent_rotation():
    calls = []

    def counting(request):
        calls.append(request)
        return ProviderResult(text="v1-answer", model="small-1",
                              tokens_in=10, tokens_out=5)

    gw = _gateway(providers={"small-1": counting,
                             "large-1": _fake_provider("large-1")})
    gw.complete("summarize", {"doc": "x"})
    gw.rotate_intent("intent-v2")  # the system changed: old answers suspect
    gw.complete("summarize", {"doc": "x"})
    assert len(calls) == 2, "rotated intent must re-ask, not serve stale cache"


def test_gateway_cost_ledger_accumulates():
    gw = _gateway()
    gw.complete("summarize", {"doc": "a"})   # 100 in @ .10, 50 out @ .30
    gw.complete("grade", {"thesis": "b"})    # 100 in @ 2.00, 50 out @ 6.00
    expected = (100 / 1000 * 0.10 + 50 / 1000 * 0.30) + \
               (100 / 1000 * 2.00 + 50 / 1000 * 6.00)
    assert gw.total_cost_usd() == pytest.approx(expected)
    assert len(gw.ledger()) == 2


def test_gateway_refuses_unaccountable_providers():
    def no_usage(request):
        return ProviderResult(text="x", model="small-1",
                              tokens_in=-1, tokens_out=5)

    gw = _gateway(providers={"small-1": no_usage,
                             "large-1": _fake_provider("large-1")})
    with pytest.raises(ProviderContractViolation):
        gw.complete("summarize", {"doc": "a"})

    def wrong_shape(request):
        return {"text": "not a ProviderResult"}

    gw2 = _gateway(providers={"small-1": wrong_shape,
                              "large-1": _fake_provider("large-1")})
    with pytest.raises(ProviderContractViolation):
        gw2.complete("summarize", {"doc": "a"})

    # Unpriced model: refusing unpriced calls, not guessing the cost.
    gw3 = _gateway(providers={"tiny-9": _fake_provider("tiny-9"),
                              "large-1": _fake_provider("large-1")},
                   routes={"summarize": "tiny-9", "grade": "large-1"})
    with pytest.raises(ProviderContractViolation):
        gw3.complete("summarize", {"doc": "a"})


# ---------------------------------------------------------------------------
# DurableRun
# ---------------------------------------------------------------------------

class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _leases():
    return LeaseStore(clock=FakeClock())


def _run(leases, router):
    return DurableRun("nightly-paper-run", leases, router, "t-ava")


def test_durable_resume_replays_ledger_not_actions():
    clock = FakeClock()
    leases = LeaseStore(clock=clock)
    router = EvidenceRouter(secret=SECRET)
    checkpoints = CheckpointStore()  # shared: outlives the dead worker
    run = DurableRun("nightly-paper-run", leases, router, "t-ava",
                     checkpoints=checkpoints)
    run.start("worker-1", ttl_s=60.0)
    run.checkpoint({"signals_evaluated": 120, "orders_staged": 0})
    # The dead worker kept emitting evidence after its last checkpoint...
    router.emit(SESSION, "intent_record", {"symbol": "NVDA", "side": "short"})
    router.emit(SESSION, "tool_call", {"tool": "submit_order"})
    # ...then died at 3am. The replacement wakes up after expiry.
    clock.now += 3600.0
    run2 = DurableRun("nightly-paper-run", leases, router, "t-ava",
                      checkpoints=checkpoints)
    state, new_entries = run2.resume("worker-2", ttl_s=60.0)
    assert state == {"signals_evaluated": 120, "orders_staged": 0}
    assert [e["event_type"] for e in new_entries] == ["intent_record",
                                                     "tool_call"]
    # The replacement holds the fence now; the zombie's token is dead.
    with pytest.raises(StaleFenceError):
        run.guarded_write(lambda: "zombie writes")


def test_durable_zombie_write_rejected_after_lease_expiry():
    clock = FakeClock()
    leases = LeaseStore(clock=clock)
    router = EvidenceRouter(secret=SECRET)
    run = _run(leases, router)
    run.start("worker-1", ttl_s=60.0)
    clock.now += 61.0  # lease expired, no heartbeat
    with pytest.raises(StaleFenceError):
        run.guarded_write(lambda: "conflicting reality")


def test_durable_heartbeat_extends_the_lease():
    clock = FakeClock()
    leases = LeaseStore(clock=clock)
    router = EvidenceRouter(secret=SECRET)
    run = _run(leases, router)
    run.start("worker-1", ttl_s=60.0)
    clock.now += 50.0
    run.heartbeat()          # renewed at t=1050, now good until t=1110
    clock.now += 55.0        # t=1105: past the ORIGINAL expiry, still live
    assert run.guarded_write(lambda: "alive") == "alive"


def test_durable_takeover_of_live_lease_refused():
    clock = FakeClock()
    leases = LeaseStore(clock=clock)
    token = leases.acquire("run-9", "worker-1", ttl_s=60.0)
    with pytest.raises(LeaseConflict):
        leases.take_over("run-9", "worker-2", ttl_s=60.0)
    # ...but the live owner's token still works.
    leases.heartbeat("run-9", token)


def test_durable_takeover_of_expired_lease_kills_old_token():
    clock = FakeClock()
    leases = LeaseStore(clock=clock)
    old_token = leases.acquire("run-9", "worker-1", ttl_s=60.0)
    clock.now += 61.0
    new_token = leases.take_over("run-9", "worker-2", ttl_s=60.0)
    assert new_token != old_token
    with pytest.raises(StaleFenceError):
        leases.guard("run-9", old_token)   # the fence moved
    leases.guard("run-9", new_token)        # the new owner passes


def test_durable_double_acquire_while_live_conflicts():
    leases = _leases()
    leases.acquire("run-9", "worker-1", ttl_s=60.0)
    with pytest.raises(LeaseConflict):
        leases.acquire("run-9", "worker-2", ttl_s=60.0)


def test_concurrent_submits_preserve_fifo_order_despite_preemption():
    # Regression: submit() once assigned the sequence number under the
    # lock but performed the queue put outside it. A thread holding an
    # earlier sequence could be preempted before its put, and a later
    # thread's entry would be emitted first — out-of-order evidence,
    # permanently recorded. The put must be inside the sequence lock.
    emitted = []
    assigned = []
    assign_lock = threading.Lock()

    class OrderRouter:
        def emit(self, session, event_type, payload):
            emitted.append(payload["n"])

    def submit_n(n):
        seq = writer.submit(SESSION, "e", {"n": n})
        with assign_lock:
            assigned.append((seq, n))

    writer = TraceWriter(OrderRouter(), capacity=16)
    real_put = writer._queue.put

    def slow_first_put(item, *a, **k):
        if item is not None and item[3].get("n") == 0:
            # Preempt the n=0 submitter between number acquisition and
            # insertion — the exact interleaving the lock placement
            # must close.
            time.sleep(0.5)
        return real_put(item, *a, **k)

    writer._queue.put = slow_first_put
    t0 = threading.Thread(target=submit_n, args=(0,))
    t1 = threading.Thread(target=submit_n, args=(1,))
    t0.start()
    time.sleep(0.2)  # let t0 acquire its sequence and enter the slow put
    t1.start()
    t1.join(timeout=10)
    t0.join(timeout=10)
    assert writer.flush(timeout=10.0)
    writer.close()
    # Emission order must match sequence-acquisition order, never the
    # queue-race order.
    expected = [n for _, n in sorted(assigned)]
    assert emitted == expected
