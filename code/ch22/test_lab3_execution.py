"""Lab 3 — Execution Under Fire (Chapter 22).

THE FIRE DRILL. Every desk runs this before it touches real size.

Scenario: it is 14:32 on a Thursday. The market starts dropping — fast.
Over the next hour it falls more than 5%. Your paper broker first starts
*rejecting* orders ("risk: market-wide halt"), then goes *silent* entirely:
submits time out, lookups fail. When the dust settles, you must answer the
only question that matters:

    Is every intent accounted for — filled, rejected, or honestly unknown —
    with no phantom fills and no double-submits?

What you are proving (the Ch 10 + Ch 11 composition):

  - The action executor (Ch 10) keeps the ledger consistent while the
    world falls apart: write-ahead rows, idempotent retries with the SAME
    key, reconcile against broker truth, never a guess.
  - The kill switch (Ch 11) trips at the 5%/hour threshold and the SCOPED
    kill isolates only the affected desk — the other tenant keeps trading
    (the Ch 6 lesson returns: isolation is not a feature, it is the unit
    of accountability).
  - When the broker goes silent mid-reconciliation, the system says
    OUTCOME-UNKNOWN and means it. The Ch 14 on-call script is your
    reference for what the humans do next.

RED FIRST. This file FAILS as shipped — every function under
"STUDENT BUILDS" raises NotImplementedError. That is the point of the lab:
red, then green, then the answer key in Appendix B. Run it now:

    python -m pytest code/ch22/test_lab3_execution.py -q

and watch it burn. Then build.

WHAT YOU BUILD (the wiring — the cleared components are GIVEN):

  1. ``wire_desk(secret)`` — construct and wire the desk: Ledger,
     ActionExecutor (settle_seconds=0, max_retries=0, backoff=0 — the lab
     is about composition, not tuning), OperatorRegistry, KillSwitch with
     a beating supervisor heartbeat, and the broker wrapped as
     ``killswitch.guarded(wrap_broker(raw))``. Return a context dict the
     other functions use.

  2. ``submit_intent(ctx, order, scope)`` — the desk's single doorway to
     the market. Check the kill gate *with the scope*
     (``killswitch.check("submit", scope=scope)``) BEFORE the executor
     touches anything, then run ``executor.execute(order, ctx["broker"])``.
     If the gate refuses, return ``{"refused": True, "reason": ...}`` with
     the kill level NAMED in the reason — a refusal without a reason is
     a different kind of unknown.

  3. ``drive_market(ctx, bars, scope)`` — feed minute bars through the
     desk. Track the drop from the session's first close; the moment the
     drop reaches 5%, engage a SCOPED ``PAUSE_INTENTS`` kill for that
     scope with a WRITTEN reason naming the measured drop. Return the
     trip report: ``{"tripped": bool, "drop_pct": float, "at_bar": int}``.

  4. ``close_out(ctx)`` — the end-of-day discipline: run ``reconcile()``
     and return the final ledger states. After this, ``pending_keys()``
     must be empty and every row must be terminal — or honestly pending
     with a recorded reconcile error, never a guess.

GIVEN (do not modify): ``FlashCrashBroker``, ``crash_bars()``,
``second_wave_bars()``, ``make_order()``, and the test functions below.

HONESTY RULES (the lab grades these, Appendix B enforces them):

  - A row may be ``filled`` only if the BROKER says so (broker truth wins).
  - A row may be ``abandoned`` only after the settle window with no
    broker record — never while the broker is merely silent.
  - ``timeout``/``submitted``/``open`` are HONEST states, not failures.
    The failure is claiming to know what you do not.
  - One admin cannot lift a FULL_STOP. Ever. Test 7 checks.

Day-trading thread: this is the desk's worst afternoon, on paper, on
purpose. The crash fixture is synthetic (labeled SYNTHETIC throughout);
the discipline it teaches is real.
"""

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ch10"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ch11"))

from action_executor import ActionExecutor, Ledger, wrap_broker, TERMINAL
from killswitch import (
    KillSwitch,
    KillLevel,
    OperatorRegistry,
    HaltedError,
    KillAuthError,
)


# ---------------------------------------------------------------------------
# GIVEN — the flash-crash fixture. Do not modify.
# ---------------------------------------------------------------------------

class FlashCrashBroker:
    """Raw paper-broker simulator with a scripted four-phase timeline.

    Phases:
      normal    — fills every order immediately (broker truth recorded).
      rejecting — the broker answers, but with rejections
                  ("risk: market-wide halt").
      silent    — the broker is GONE: submits raise TimeoutError, lookups
                  raise ConnectionError. Nothing here may be interpreted
                  as an outcome. OUTCOME-UNKNOWN is the only honest answer.
      recovered — the network is back; broker truth is readable again.

    The ``orders`` dict is the broker's book of record. The lab's no-phantom-
    fill test compares it against the ledger: they must agree exactly.
    """

    NORMAL, REJECTING, SILENT, RECOVERED = (
        "normal", "rejecting", "silent", "recovered",
    )

    def __init__(self):
        self.phase = self.NORMAL
        self.orders = {}
        self.submits = 0

    def set_phase(self, phase):
        assert phase in (self.NORMAL, self.REJECTING, self.SILENT, self.RECOVERED)
        self.phase = phase

    def __call__(self, order, timeout):
        key = order["idempotency_key"]
        if self.phase == self.SILENT:
            raise TimeoutError("broker went silent mid-crash")
        self.submits += 1
        if key in self.orders:
            return dict(self.orders[key])  # idempotent replay, same key
        if self.phase == self.REJECTING:
            record = {
                "status": "rejected",
                "broker_id": f"brk-{key[:8]}",
                "filled_qty": 0.0,
                "avg_price": None,
                "reason": "risk: market-wide halt",
            }
        else:
            record = {
                "status": "filled",
                "broker_id": f"brk-{key[:8]}",
                "filled_qty": float(order["qty"]),
                "avg_price": order.get("limit_price"),
                "reason": "",
            }
        self.orders[key] = record
        return dict(record)

    def lookup(self, key):
        if self.phase == self.SILENT:
            raise ConnectionError("broker went silent mid-crash")
        record = self.orders.get(key)
        return dict(record) if record is not None else None


def crash_bars(n=60, start=100.0, end=93.4):
    """Sixty minute bars sliding ~6.6% — the crash. Labeled SYNTHETIC.

    Each bar is a dict with ``close``. Deterministic: no randomness,
    so the trip bar is reproducible.
    """
    step = (start - end) / n
    return [
        {"t": i, "close": round(start - step * i, 4), "synthetic": True}
        for i in range(n + 1)
    ]


def second_wave_bars(n=20, start=93.4, end=90.0):
    """A second leg down DURING the halt — the no-re-entry test."""
    step = (start - end) / n
    return [
        {"t": 100 + i, "close": round(start - step * i, 4), "synthetic": True}
        for i in range(n + 1)
    ]


def make_order(key, symbol="NVDA", side="buy", qty=100.0, limit_price=93.0):
    """One validated order dict, as the decision plane would hand it over."""
    return {
        "idempotency_key": key,
        "symbol": symbol,
        "side": side,
        "qty": float(qty),
        "order_type": "limit",
        "limit_price": float(limit_price),
    }


SCOPE_A = ("tenant", "desk-a")  # the desk that catches the crash
SCOPE_B = ("tenant", "desk-b")  # the innocent desk next door

OPERATORS = {"op-ruth": "admin", "op-sam": "admin", "op-ella": "operator"}


# ---------------------------------------------------------------------------
# STUDENT BUILDS — everything below this line is YOUR code.
# ---------------------------------------------------------------------------

def wire_desk(secret: bytes) -> dict:
    """Construct and wire one desk's execution stack. Return the context.

    The context dict must carry at least: ``ledger``, ``executor``,
    ``registry``, ``killswitch``, ``broker`` (the raw FlashCrashBroker),
    and ``wired_broker`` (killswitch.guarded(wrap_broker(raw))).

    Discipline checklist:
      - Ledger first, in-memory is fine for the lab.
      - Executor with settle_seconds=0, max_retries=0, backoff=0.
      - Registry built from OPERATORS and your secret.
      - KillSwitch with a FRESH heartbeat — it boots armed-by-default,
        and a desk that never beats is a desk that never trades.
      - The broker wrapped ONCE, at the boundary: guarded(wrap_broker(raw)).
    """
    raise NotImplementedError(
        "LAB TODO 1: wire_desk — build the Ledger, ActionExecutor, "
        "OperatorRegistry, and KillSwitch; beat the heartbeat; wrap the "
        "broker as killswitch.guarded(wrap_broker(raw)). Return them in a "
        "context dict."
    )


def submit_intent(ctx: dict, order: dict, scope) -> dict:
    """The desk's single doorway to the market.

    1. Check the kill gate WITH the scope: killswitch.check("submit",
       scope=scope). The scope is what makes the kill surgical — a global
       check here would punish the innocent desk.
    2. If the gate refuses, return {"refused": True, "reason": <str>} with
       the kill level NAMED in the reason. No phantom ledger rows: a
       refusal is something the system DECLINED to do.
    3. Otherwise run executor.execute(order, ctx["wired_broker"]) and
       return the ledger record.
    """
    raise NotImplementedError(
        "LAB TODO 2: submit_intent — scope-aware killswitch.check, named "
        "refusal on HaltedError/HeartbeatStale, else executor.execute "
        "through the wired (guarded) broker."
    )


def drive_market(ctx: dict, bars: list, scope) -> dict:
    """Feed minute bars through the desk; trip the scoped kill at -5%.

    Track the drop from the FIRST bar of the list passed in:
        drop = (bars[0]["close"] - min_close_so_far) / bars[0]["close"]
    The moment drop >= 0.05, engage a SCOPED PAUSE_INTENTS kill for
    ``scope`` with a written reason naming the measured drop, and stop
    tripping.

    If a kill at PAUSE_INTENTS or above is ALREADY armed for the scope,
    do NOT attempt to re-engage (re-engaging is refused, not stacked) —
    just measure and return {"tripped": False, ...}.

    Returns {"tripped": bool, "drop_pct": float, "at_bar": int|None} where
    drop_pct is the drop measured at the trip bar (or the maximum drop
    seen, when nothing tripped).
    """
    raise NotImplementedError(
        "LAB TODO 3: drive_market — per-bar drop tracking from the first "
        "close; at >=5% engage KillLevel.PAUSE_INTENTS scoped to the desk "
        "with a written reason (use a verified operator session from the "
        "registry). Return the trip report."
    )


def close_out(ctx: dict) -> dict:
    """End-of-day discipline: reconcile everything against broker truth.

    Run executor.reconcile(ctx["wired_broker"]) and return
    {"pending": [...], "states": {key: status}}.

    After this, pending must be empty OR every remaining row must carry
    a recorded reconcile_error (the broker is still silent — honest
    unknown, never a guess).
    """
    raise NotImplementedError(
        "LAB TODO 4: close_out — run the reconcile sweep through the "
        "wired broker and report pending keys plus final states."
    )


# ---------------------------------------------------------------------------
# THE TESTS — the fire drill. All red until you build.
# ---------------------------------------------------------------------------

@pytest.fixture()
def ctx():
    return wire_desk(secret=b"lab3-test-secret")


def test_kill_trips_at_five_percent_drop(ctx):
    """The crash trips the kill — and the refusal says WHY."""
    report = drive_market(ctx, crash_bars(), SCOPE_A)
    assert report["tripped"] is True
    assert report["drop_pct"] >= 0.05
    level = ctx["killswitch"].level_for(SCOPE_A)
    assert level >= KillLevel.PAUSE_INTENTS, f"kill never armed: {level}"

    outcome = submit_intent(
        ctx, make_order("lab3-k1", qty=10.0), SCOPE_A
    )
    assert outcome.get("refused") is True, "halted desk submitted anyway"
    reason = outcome["reason"]
    assert "PAUSE_INTENTS" in reason, f"refusal must name the kill level: {reason!r}"


def test_scoped_kill_isolates_desk(ctx):
    """The innocent desk keeps trading. Isolation is the unit of blame."""
    drive_market(ctx, crash_bars(), SCOPE_A)

    assert ctx["killswitch"].level_for(SCOPE_B) == KillLevel.NONE
    outcome = submit_intent(ctx, make_order("lab3-b1", qty=10.0), SCOPE_B)
    assert not outcome.get("refused"), f"innocent desk refused: {outcome}"
    assert outcome["status"] == "filled"


def test_in_flight_orders_reconciled(ctx):
    """Orders in flight when the crash hits: no phantoms, no doubles."""
    raw = ctx["broker"]

    # Three orders land clean before the crash.
    for i in range(3):
        rec = submit_intent(ctx, make_order(f"lab3-pre-{i}"), SCOPE_A)
        assert rec["status"] == "filled"

    # The broker starts rejecting, then goes silent.
    raw.set_phase(FlashCrashBroker.REJECTING)
    rec = submit_intent(ctx, make_order("lab3-rej-0"), SCOPE_A)
    assert rec["status"] == "rejected"

    raw.set_phase(FlashCrashBroker.SILENT)
    rec = submit_intent(ctx, make_order("lab3-sil-0"), SCOPE_A)
    assert rec["status"] == "timeout"  # honest unknown, not a guess

    # The network comes back. Reconcile against broker truth.
    raw.set_phase(FlashCrashBroker.RECOVERED)
    final = close_out(ctx)
    assert final["pending"] == [], f"unresolved after recovery: {final['pending']}"

    ledger = ctx["ledger"]
    for key, status in final["states"].items():
        assert status in TERMINAL, f"{key} left non-terminal: {status}"

    # No phantom fills: every ledger 'filled' row exists in the broker's book.
    broker_filled = {k for k, r in raw.orders.items() if r["status"] == "filled"}
    ledger_filled = {
        k for k, s in final["states"].items() if s == "filled"
    }
    assert ledger_filled == broker_filled, (
        f"ledger/broker disagree: ledger={ledger_filled} broker={broker_filled}"
    )
    # No double-submits: one broker record per key, keys unique by construction.
    assert raw.submits == len(raw.orders), "broker saw a duplicate submit"


def test_ledger_consistent_after_halt(ctx):
    """After the halt and the sweep: every intent accounted for."""
    # Two clean fills before the crash.
    for i in range(2):
        rec = submit_intent(ctx, make_order(f"lab3-h{i}"), SCOPE_A)
        assert rec["status"] == "filled"
    drive_market(ctx, crash_bars(), SCOPE_A)

    # A refused submit leaves no phantom ledger row: the refusal is
    # something the system DECLINED to do, and the ledger records only
    # what the system did.
    refused_key = "lab3-h-refused"
    outcome = submit_intent(ctx, make_order(refused_key), SCOPE_A)
    assert outcome.get("refused") is True
    assert ctx["ledger"].get(refused_key) is None, \
        "refused submit left a phantom ledger row"

    raw = ctx["broker"]
    raw.set_phase(FlashCrashBroker.RECOVERED)
    final = close_out(ctx)
    assert final["pending"] == []
    for key, status in final["states"].items():
        assert status in TERMINAL, f"{key}: {status} is not a final answer"
    assert set(final["states"]) == {"lab3-h0", "lab3-h1"}


def test_silent_broker_is_outcome_unknown(ctx):
    """While the broker is silent, reconcile must not invent an outcome."""
    rec = submit_intent(ctx, make_order("lab3-unk-0"), SCOPE_A)
    assert rec["status"] == "filled"  # clean fill before the storm

    raw = ctx["broker"]
    raw.set_phase(FlashCrashBroker.SILENT)
    rec = submit_intent(ctx, make_order("lab3-unk-1"), SCOPE_A)
    assert rec["status"] == "timeout"

    # Sweep while silent: the row stays pending WITH a recorded error.
    # The failure would be a row that claims 'filled' or 'abandoned'.
    ctx["executor"].reconcile(ctx["wired_broker"])
    row = ctx["ledger"].get("lab3-unk-1")
    assert row["status"] == "timeout", f"silent broker invented: {row['status']}"
    assert row["reconcile_error"], "the unknown must be documented, not silent"
    assert ctx["ledger"].pending_keys() == ["lab3-unk-1"]


def test_second_wave_no_reentry(ctx):
    """A second crash wave during the halt changes nothing."""
    drive_market(ctx, crash_bars(), SCOPE_A)
    kill = ctx["killswitch"]
    assert kill.level_for(SCOPE_A) >= KillLevel.PAUSE_INTENTS

    # Re-engaging at the same or lower level is refused, not stacked.
    op = ctx["registry"].issue("op-ella")
    with pytest.raises(KillAuthError):
        kill.engage(KillLevel.PAUSE_INTENTS, [op], "second wave panic",
                    scope=SCOPE_A)

    # The second wave breaks against the armed kill.
    report = drive_market(ctx, second_wave_bars(), SCOPE_A)
    assert report["tripped"] is False, "re-tripped an armed kill"
    assert kill.level_for(SCOPE_A) >= KillLevel.PAUSE_INTENTS

    outcome = submit_intent(ctx, make_order("lab3-k2"), SCOPE_A)
    assert outcome.get("refused") is True


def test_single_admin_cannot_lift_full_stop(ctx):
    """One admin is never two people. The two-person rule holds."""
    kill = ctx["killswitch"]
    reg = ctx["registry"]
    ruth = reg.issue("op-ruth")
    sam = reg.issue("op-sam")

    kill.engage(KillLevel.FULL_STOP, [ruth, sam], "suspected compromise")
    assert kill.level >= KillLevel.FULL_STOP

    # One admin alone cannot lift it — not even a different one.
    with pytest.raises(KillAuthError):
        kill.disarm(ruth, "looks fine now")
    with pytest.raises(KillAuthError):
        kill.disarm(sam, "looks fine now", scope=None)
    assert kill.armed, "the kill disarmed on a single admin"


def test_two_admins_can_lift_and_trading_resumes(ctx):
    """Two verified admins, a written reason, a fresh heartbeat: trading."""
    kill = ctx["killswitch"]
    reg = ctx["registry"]
    ruth = reg.issue("op-ruth")
    sam = reg.issue("op-sam")

    kill.engage(KillLevel.FULL_STOP, [ruth, sam], "suspected compromise")
    kill.disarm(ruth, "forensics clean; keys rotated; postmortem filed",
                second_session=sam)
    assert not kill.armed

    kill.beat()  # the supervisor is watching again
    outcome = submit_intent(ctx, make_order("lab3-resume-0"), SCOPE_A)
    assert not outcome.get("refused"), f"still refused after lift: {outcome}"
    assert outcome["status"] == "filled"
