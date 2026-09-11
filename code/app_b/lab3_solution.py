"""Lab 3 answer key (Appendix B) — the reference desk wiring.

The composition the lab proves: Ch 10's action executor (the ledger stays
consistent while the world falls apart) + Ch 11's kill switch (the scoped
halt isolates one desk, never the firm).

Three wiring decisions carry the whole lab:

1. The gate is checked BEFORE the executor touches anything, WITH the
   scope. A global check here would punish the innocent desk; a late
   check would leave phantom ledger rows for submits the system
   declined to make. A refusal is something the system DECLINED to do —
   the ledger records only what the system did.

2. The broker is wrapped ONCE, at the boundary, as
   ``killswitch.guarded(wrap_broker(raw))``. wrap_broker is the
   anti-corruption layer (raw TimeoutError/ConnectionError become
   BrokerTimeout/BrokerError, the only taxonomy the executor's except
   clause understands); guarded re-checks the gate at send time, closing
   the TOCTOU window between the early check and the wire call.

3. drive_market measures the drop from the FIRST bar of the list it is
   given and engages a SCOPED PAUSE_INTENTS with a WRITTEN reason naming
   the measured drop. If a kill at PAUSE_INTENTS or above is already
   armed for the scope, it measures and returns — re-engaging is refused
   by the switch, not stacked by the caller.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))                    # the lab's GIVEN fixtures
sys.path.insert(0, str(_HERE.parent / "ch10"))    # Ch 10: the action plane
sys.path.insert(0, str(_HERE.parent / "ch11"))    # Ch 11: kill switches

from action_executor import (  # noqa: E402
    ActionExecutor,
    Ledger,
    TERMINAL,
    wrap_broker,
)
from killswitch import (  # noqa: E402
    HaltedError,
    KillAuthError,  # noqa: F401 — re-exported: the tests import it from here
    KillLevel,
    KillSwitch,
    OperatorRegistry,
)
from test_lab3_execution import (  # noqa: E402 — the lab's GIVEN fixtures
    OPERATORS,
    FlashCrashBroker,
)

DROP_THRESHOLD = 0.05  # the kill trips at a 5%/hour drop


def wire_desk(secret: bytes) -> dict:
    """Construct and wire one desk's execution stack.

    Ledger first (write-ahead, in-memory is fine for the lab); the
    executor with the lab's composition settings (settle_seconds=0,
    max_retries=0, backoff=0 — the lab is about composition, not tuning);
    the operator registry from OPERATORS; the kill switch with a FRESH
    heartbeat (it boots armed-by-default, and a desk that never beats is
    a desk that never trades); and the broker wrapped once, at the
    boundary: killswitch.guarded(wrap_broker(raw)).
    """
    ledger = Ledger()
    executor = ActionExecutor(
        ledger, timeout=5.0, max_retries=0, backoff=0, settle_seconds=0
    )
    registry = OperatorRegistry(OPERATORS, secret)
    killswitch = KillSwitch(registry)
    killswitch.beat()  # the supervisor is watching from the first second
    raw = FlashCrashBroker()
    wired_broker = killswitch.guarded(wrap_broker(raw))
    return {
        "ledger": ledger,
        "executor": executor,
        "registry": registry,
        "killswitch": killswitch,
        "broker": raw,            # the raw simulator: phases are driven here
        "wired_broker": wired_broker,  # the only path the executor may use
    }


def submit_intent(ctx: dict, order: dict, scope) -> dict:
    """The desk's single doorway to the market.

    The kill gate is checked WITH the scope before the executor touches
    anything. A refusal names the kill level — a refusal without a reason
    is a different kind of unknown — and leaves no ledger row.
    """
    killswitch = ctx["killswitch"]
    try:
        killswitch.check("submit", scope=scope)
    except HaltedError as exc:
        level = killswitch.level_for(scope).name
        return {"refused": True,
                "reason": f"submit refused by kill gate ({level}): {exc}"}
    return ctx["executor"].execute(order, ctx["wired_broker"])


def drive_market(ctx: dict, bars: list, scope) -> dict:
    """Feed minute bars through the desk; trip the scoped kill at -5%.

    The drop is measured from the FIRST bar of the list passed in — the
    session's open, not a rolling window, because the kill answers "how
    far have we fallen since the session started". The moment the drop
    reaches 5%, a SCOPED PAUSE_INTENTS is engaged with a written reason
    naming the measured drop, and the function stops tripping.

    If a kill at PAUSE_INTENTS or above is already armed for the scope,
    the function measures and returns {"tripped": False, ...} — it does
    not attempt to re-engage (the switch refuses stacking, loudly).
    """
    killswitch = ctx["killswitch"]
    first_close = bars[0]["close"]
    max_drop = 0.0
    trip_bar: int | None = None
    for i, bar in enumerate(bars):
        drop = (first_close - bar["close"]) / first_close
        if drop > max_drop:
            max_drop = drop
        if drop >= DROP_THRESHOLD and trip_bar is None:
            if killswitch.level_for(scope) >= KillLevel.PAUSE_INTENTS:
                break  # already armed: measure, don't stack
            operator = ctx["registry"].issue("op-ella")
            killswitch.engage(
                KillLevel.PAUSE_INTENTS,
                [operator],
                f"market drop {drop:.2%} from session open "
                f"({first_close:.2f} -> {bar['close']:.2f}); "
                f"scoped halt for {scope[1]}",
                scope=scope,
            )
            trip_bar = i
            break
    return {"tripped": trip_bar is not None,
            "drop_pct": max_drop,
            "at_bar": trip_bar}


def close_out(ctx: dict) -> dict:
    """End-of-day discipline: reconcile everything against broker truth.

    The sweep runs through the WIRED broker (guarded: lookups are never
    gated, even at FULL_STOP — freezing is not resolving). Afterwards
    every row is terminal, or honestly pending with a recorded reconcile
    error. A guess is never an option.
    """
    ctx["executor"].reconcile(ctx["wired_broker"])
    ledger = ctx["ledger"]
    rows = ledger.conn.execute(
        "SELECT idempotency_key, status FROM executions"
    ).fetchall()
    states = {row["idempotency_key"]: row["status"] for row in rows}
    for key, status in states.items():
        assert status in TERMINAL or status in ("submitted", "timeout", "open"), (
            f"close_out: {key} left in an impossible state {status!r}")
    return {"pending": ledger.pending_keys(), "states": states}
