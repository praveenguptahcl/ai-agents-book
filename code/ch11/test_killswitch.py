"""Kill-switch drills for the AlphaForge / WealthForge agent team.

Every test here is a chaos drill or an authority attack: the kill switch
is the component that must work when everything else is on fire, so the
suite treats it adversarially. Fake clock drives the heartbeat window;
no sleeps, no network, stdlib + pytest only.

Operator identities are VERIFIED sessions (HMAC-signed, registry-issued).
Passing raw credential strings to engage()/disarm() is rejected — that
was the first draft's API theater, and the suite proves it stays dead.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# The real-ledger drill (test_drill_*) uses the REAL Ch 10 ledger and
# executor — not mocks — to prove the kill switch against the production
# state machine it actually guards.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ch10"))

from killswitch import (
    GuardedBroker,
    HaltedError,
    HeartbeatStale,
    KillAuthError,
    KillLevel,
    KillSwitch,
    OperatorRegistry,
    OperatorSession,
    RiskMonitor,
    SYSTEM_ACTOR,
)


@pytest.fixture
def registry():
    return OperatorRegistry(
        {
            "op-ella": "operator",       # rank 1 — the on-call operator
            "op-marcus": "operator",     # rank 1 — second pair of hands
            "risk-ana": "risk_officer",  # rank 2
            "admin-ruth": "admin",       # rank 3
            "admin-sam": "admin",        # rank 3
            SYSTEM_ACTOR: "risk_officer",
        },
        secret=b"test-secret-16bytes-minimum",
    )


@pytest.fixture
def sessions(registry):
    """Verified sessions for every operator — the only identities
    engage()/disarm() will accept."""
    return {op: registry.issue(op) for op in (
        "op-ella", "op-marcus", "risk-ana", "admin-ruth", "admin-sam",
    )}


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def switch(registry, clock):
    return KillSwitch(registry, heartbeat_window_s=30.0, clock=clock)


# ---------------------------------------------------------------- heartbeat
def test_submit_allowed_when_healthy(switch):
    switch.beat()
    assert switch.check("submit") is None


def test_submit_refused_before_first_beat(switch):
    # Fail closed from boot: no heartbeat ever -> no trading, ever.
    with pytest.raises(HeartbeatStale):
        switch.check("submit")


def test_stale_heartbeat_blocks_submit(switch, clock):
    switch.beat()
    clock.advance(31.0)
    with pytest.raises(HeartbeatStale):
        switch.check("submit")


def test_heartbeat_recovers_after_stale(switch, clock):
    switch.beat()
    clock.advance(31.0)
    with pytest.raises(HeartbeatStale):
        switch.check("submit")
    switch.beat()  # supervisor restarts
    assert switch.check("submit") is None


def test_heartbeat_stale_is_a_halted_error(switch):
    # Callers can catch HaltedError uniformly: killed or supervisor-dead,
    # the answer is the same — do not submit.
    assert issubclass(HeartbeatStale, HaltedError)
    with pytest.raises(HaltedError):
        switch.check("submit")


# ------------------------------------------- verified identity enforcement
def test_raw_strings_are_not_identities(switch, sessions):
    # The API-theater kill: a single attacker typing two names must not
    # constitute two-person control.
    switch.beat()
    with pytest.raises(KillAuthError):
        switch.engage(KillLevel.FULL_STOP, ["admin-ruth", "admin-sam"], "spoofed consensus")
    assert not switch.armed


def test_disarm_rejects_raw_strings(switch, sessions):
    switch.beat()
    switch.engage(KillLevel.PAUSE_INTENTS, [sessions["op-ella"]], "drill")
    with pytest.raises(KillAuthError):
        switch.disarm("risk-ana", "typed, not verified")
    assert switch.armed


def test_forged_session_rejected(registry, switch, sessions):
    switch.beat()
    good = sessions["op-ella"]
    forged = OperatorSession(
        token=good.token[:-4] + "ffff",  # tampered signature
        operator_id=good.operator_id,
        role=good.role,
        issued_at=good.issued_at,
        expires_at=good.expires_at,
    )
    with pytest.raises(KillAuthError):
        switch.engage(KillLevel.PAUSE_INTENTS, [forged], "forgery attempt")


def test_expired_session_rejected(switch, registry):
    switch.beat()
    # A session minted with a 1s TTL, verified after it dies.
    import time as _time

    class ExpClock:
        def __init__(self):
            self.t = _time.time()

        def __call__(self):
            return self.t

    exp_clock = ExpClock()
    reg = OperatorRegistry({"op-ella": "operator"}, secret=b"test-secret-16bytes-minimum", clock=exp_clock)
    sw = KillSwitch(reg, clock=FakeClock())
    sw.beat()
    sess = reg.issue("op-ella", ttl_seconds=1.0)
    exp_clock.t += 2.0
    with pytest.raises(KillAuthError):
        sw.engage(KillLevel.PAUSE_INTENTS, [sess], "stale credential")


def test_revoked_operator_session_dies_on_next_use(registry, switch, sessions):
    switch.beat()
    registry.revoke("op-ella")
    with pytest.raises(KillAuthError):
        switch.engage(KillLevel.PAUSE_INTENTS, [sessions["op-ella"]], "revoked mid-shift")


def test_demoted_operator_session_rejected(registry, switch):
    switch.beat()
    sess = registry.issue("admin-ruth")  # minted while admin
    registry._operators["admin-ruth"] = "operator"  # demoted afterwards
    with pytest.raises(KillAuthError):
        switch.engage(KillLevel.FULL_STOP, [sess, registry.issue("admin-sam")], "demotion test")
    assert not switch.armed


def test_session_binds_role_at_issue(registry, sessions):
    verified = registry.verify(sessions["risk-ana"])
    assert verified.role == "risk_officer"
    assert verified.operator_id == "risk-ana"


# ------------------------------------------------------------------ levels
def test_level1_pause_blocks_submit_allows_cancel_and_reconcile(switch, sessions):
    switch.beat()
    switch.engage(KillLevel.PAUSE_INTENTS, [sessions["op-ella"]], "looping signal, investigating")
    with pytest.raises(HaltedError):
        switch.check("submit")
    assert switch.check("cancel") is None
    assert switch.check("reconcile") is None
    assert switch.check("read") is None


def test_level2_engage_cancels_open_once(switch, sessions):
    calls = []
    sw = KillSwitch(
        switch._registry,
        clock=FakeClock(),
        cancel_open_fn=lambda scope: calls.append(scope) or "2 cancelled",
    )
    sw.beat()
    result = sw.engage(KillLevel.CANCEL_OPEN, [sessions["op-ella"]], "bad batch, pull opens")
    assert calls == [None]  # effect receives the (global) scope
    assert result["effects"]["cancel_open"] == "2 cancelled"


def test_level2_escalation_runs_only_new_effects(switch, sessions):
    calls = []
    sw = KillSwitch(
        switch._registry,
        clock=FakeClock(),
        cancel_open_fn=lambda scope: calls.append("cancel"),
        flatten_fn=lambda scope: calls.append("flatten"),
    )
    sw.beat()
    sw.engage(KillLevel.PAUSE_INTENTS, [sessions["op-ella"]], "pause first")
    sw.engage(KillLevel.CANCEL_OPEN, [sessions["op-ella"]], "now cancel")
    sw.engage(KillLevel.FLATTEN_HALT, [sessions["op-ella"]], "now flatten")
    assert calls == ["cancel", "flatten"]


def test_engage_lower_than_current_rejected(switch, sessions):
    switch.beat()
    switch.engage(KillLevel.CANCEL_OPEN, [sessions["op-ella"]], "up")
    with pytest.raises(KillAuthError):
        switch.engage(KillLevel.PAUSE_INTENTS, [sessions["op-ella"]], "sneaky downgrade")


def test_engage_requires_written_reason(switch, sessions):
    switch.beat()
    with pytest.raises(KillAuthError):
        switch.engage(KillLevel.PAUSE_INTENTS, [sessions["op-ella"]], "   ")


def test_unknown_operator_cannot_engage(switch, registry):
    switch.beat()
    with pytest.raises(KillAuthError):
        registry.issue("ghost")
    # ...and a session minted by a FOREIGN registry (different secret) dies too.
    foreign = OperatorRegistry({"ghost": "admin"}, secret=b"a-different-16byte-secret!")
    with pytest.raises(KillAuthError):
        switch.engage(KillLevel.PAUSE_INTENTS, [foreign.issue("ghost")], "i am the agent")


def test_effect_failure_does_not_disarm_the_kill(switch, sessions):
    def boom(scope):
        raise ConnectionError("broker cancel endpoint flapping")

    sw = KillSwitch(switch._registry, clock=FakeClock(), cancel_open_fn=boom)
    sw.beat()
    sw.engage(KillLevel.CANCEL_OPEN, [sessions["op-ella"]], "kill despite flapping broker")
    assert sw.level == KillLevel.CANCEL_OPEN  # the kill arms regardless
    entry = sw.audit()[-1]
    assert entry["effects"][0]["ok"] is False
    assert "ConnectionError" in entry["effects"][0]["detail"]


# ------------------------------------------------------- two-person control
def test_full_stop_needs_two_sessions(switch, sessions):
    switch.beat()
    with pytest.raises(KillAuthError):
        switch.engage(KillLevel.FULL_STOP, [sessions["op-ella"]], "one person panic")


def test_full_stop_same_operator_twice_rejected(switch, sessions):
    switch.beat()
    with pytest.raises(KillAuthError):
        switch.engage(KillLevel.FULL_STOP, [sessions["op-ella"], sessions["op-ella"]], "not two people")


def test_full_stop_two_distinct_sessions_ok(switch, sessions):
    revoked = []
    sw = KillSwitch(
        switch._registry,
        clock=FakeClock(),
        revoke_keys_fn=lambda scope: revoked.append(scope) or "keys rotated",
    )
    sw.beat()
    sw.engage(KillLevel.FULL_STOP, [sessions["op-ella"], sessions["op-marcus"]], "runaway loop, confirmed by two")
    assert sw.level == KillLevel.FULL_STOP
    assert revoked == [None]  # API keys revoked: even a bypassed check cannot trade
    with pytest.raises(HaltedError):
        sw.check("submit")
    with pytest.raises(HaltedError):
        sw.check("cancel")  # state freeze: no effects at all
    assert sw.check("reconcile") is None  # freezing is not resolving


# ------------------------------------------------------------------- re-arm
def test_disarm_needs_strictly_higher_authority(switch, sessions):
    switch.beat()
    switch.engage(KillLevel.PAUSE_INTENTS, [sessions["op-ella"]], "investigating")
    with pytest.raises(KillAuthError):
        switch.disarm(sessions["op-ella"], "i fixed it")  # same rank: no
    with pytest.raises(KillAuthError):
        switch.disarm(sessions["op-marcus"], "trust me")  # peer rank: no
    switch.disarm(sessions["risk-ana"], "root cause found: stale signal cache; cache TTL fixed, paper-verified")
    assert switch.level == KillLevel.NONE


def test_full_stop_by_operators_needs_two_admins_to_lift(switch, sessions):
    # THE re-arm bypass fix: two rank-1 operators engage FULL_STOP. A
    # single rank-2 risk officer is "strictly greater" — and must STILL
    # be refused. A full stop always takes two admins to lift.
    switch.beat()
    switch.engage(
        KillLevel.FULL_STOP,
        [sessions["op-ella"], sessions["op-marcus"]],
        "runaway loop, confirmed by two",
    )
    with pytest.raises(KillAuthError):
        switch.disarm(sessions["risk-ana"], "i outrank the engagers")
    assert switch.armed
    with pytest.raises(KillAuthError):
        switch.disarm(sessions["admin-ruth"], "single admin tries")
    assert switch.armed
    with pytest.raises(KillAuthError):
        switch.disarm(
            sessions["admin-ruth"], "admin plus operator",
            second_session=sessions["op-ella"],
        )
    assert switch.armed
    switch.disarm(
        sessions["admin-ruth"],
        "root cause fixed and paper-verified",
        second_session=sessions["admin-sam"],
    )
    assert switch.level == KillLevel.NONE


def test_admin_engaged_full_stop_needs_two_distinct_admins(switch, sessions):
    switch.beat()
    switch.engage(
        KillLevel.FULL_STOP,
        [sessions["admin-ruth"], sessions["admin-sam"]],
        "exchange halt rumor",
    )
    with pytest.raises(KillAuthError):
        switch.disarm(sessions["admin-ruth"], "single admin tries")
    with pytest.raises(KillAuthError):
        switch.disarm(
            sessions["admin-ruth"], "one admin twice",
            second_session=sessions["admin-ruth"],
        )
    switch.disarm(
        sessions["admin-ruth"],
        "rumor cleared by exchange notice",
        second_session=sessions["admin-sam"],
    )
    assert switch.level == KillLevel.NONE


def test_disarm_without_reason_rejected(switch, sessions):
    switch.beat()
    switch.engage(KillLevel.PAUSE_INTENTS, [sessions["op-ella"]], "investigating")
    with pytest.raises(KillAuthError):
        switch.disarm(sessions["risk-ana"], "   ")
    assert switch.armed  # still armed


def test_disarm_when_nothing_armed_rejected(switch, sessions):
    with pytest.raises(KillAuthError):
        switch.disarm(sessions["admin-ruth"], "no kill to lift")


def test_disarm_wrong_scope_names_armed_scopes(switch, sessions):
    switch.beat()
    switch.engage(
        KillLevel.PAUSE_INTENTS, [sessions["op-ella"]], "harbor loop",
        scope=("tenant", "harbor"),
    )
    with pytest.raises(KillAuthError) as excinfo:
        switch.disarm(sessions["risk-ana"], "wrong scope", scope=("tenant", "beacon"))
    assert "harbor" in str(excinfo.value)
    assert switch.armed


def test_rearm_reason_lands_in_audit_verbatim(switch, sessions):
    switch.beat()
    switch.engage(KillLevel.PAUSE_INTENTS, [sessions["op-ella"]], "investigating")
    reason = "root cause: signal cache TTL; fix: TTL 60s; verified on paper 2026-09-11"
    switch.disarm(sessions["risk-ana"], reason)
    entry = switch.audit()[-1]
    assert entry["event"] == "disarm"
    assert entry["reason"] == reason
    assert entry["previous_engagers"] == ["op-ella"]


# ------------------------------------------------------------ scoped kills
def test_scoped_kill_blocks_only_its_tenant(switch, sessions):
    switch.beat()
    harbor = ("tenant", "harbor")
    switch.engage(KillLevel.PAUSE_INTENTS, [sessions["op-ella"]], "harbor loop", scope=harbor)
    # Harbor is halted...
    with pytest.raises(HaltedError):
        switch.check("submit", scope=harbor)
    # ...beacon trades on, untouched...
    assert switch.check("submit", scope=("tenant", "beacon")) is None
    # ...and unscoped (global-path) submits are NOT governed by a scoped kill.
    assert switch.check("submit") is None


def test_global_kill_blocks_scoped_submits(switch, sessions):
    switch.beat()
    switch.engage(KillLevel.PAUSE_INTENTS, [sessions["op-ella"]], "firm-wide pause")
    with pytest.raises(HaltedError):
        switch.check("submit", scope=("tenant", "harbor"))


def test_scoped_and_global_kills_compose(switch, sessions):
    switch.beat()
    switch.engage(KillLevel.PAUSE_INTENTS, [sessions["op-ella"]], "harbor loop", scope=("tenant", "harbor"))
    switch.engage(KillLevel.CANCEL_OPEN, [sessions["op-ella"]], "firm-wide", scope=None)
    assert switch.level_for(("tenant", "harbor")) == KillLevel.CANCEL_OPEN
    assert switch.level_for(("tenant", "beacon")) == KillLevel.CANCEL_OPEN
    # Disarming the global kill leaves the scoped one armed.
    switch.disarm(sessions["risk-ana"], "firm-wide clear", scope=None)
    assert switch.check("submit", scope=("tenant", "beacon")) is None
    with pytest.raises(HaltedError):
        switch.check("submit", scope=("tenant", "harbor"))
    switch.disarm(sessions["risk-ana"], "harbor clear", scope=("tenant", "harbor"))
    assert not switch.armed


def test_scoped_effects_receive_scope_and_run_once_per_scope(switch, sessions):
    seen = []
    sw = KillSwitch(
        switch._registry,
        clock=FakeClock(),
        cancel_open_fn=lambda scope: seen.append(scope) or f"cancelled {scope}",
    )
    sw.beat()
    harbor = ("tenant", "harbor")
    sw.engage(KillLevel.CANCEL_OPEN, [sessions["op-ella"]], "harbor loop", scope=harbor)
    assert seen == [harbor]  # the effect targeted harbor, not the firm
    sw.engage(KillLevel.CANCEL_OPEN, [sessions["op-ella"]], "beacon loop", scope=("tenant", "beacon"))
    assert seen == [harbor, ("tenant", "beacon")]
    # Escalating harbor to FLATTEN_HALT re-runs only the NEW effect for harbor.
    sw2_calls = []
    sw2 = KillSwitch(
        switch._registry,
        clock=FakeClock(),
        cancel_open_fn=lambda scope: sw2_calls.append(("cancel", scope)),
        flatten_fn=lambda scope: sw2_calls.append(("flatten", scope)),
    )
    sw2.beat()
    sw2.engage(KillLevel.CANCEL_OPEN, [sessions["op-ella"]], "harbor loop", scope=harbor)
    sw2.engage(KillLevel.FLATTEN_HALT, [sessions["op-ella"]], "worse", scope=harbor)
    assert sw2_calls == [("cancel", harbor), ("flatten", harbor)]


def test_bad_scope_rejected(switch, sessions):
    switch.beat()
    with pytest.raises(KillAuthError):
        switch.engage(KillLevel.PAUSE_INTENTS, [sessions["op-ella"]], "bad", scope=("desk", "x"))
    with pytest.raises(KillAuthError):
        switch.check("submit", scope="harbor")


# ------------------------------------------------- TOCTOU: wrap the client
class RawFakeBroker:
    """A naive broker client: touches the wire without consulting the
    kill switch. This is the race."""

    def __init__(self):
        self.sent = []

    def __call__(self, order, timeout=None):
        self.sent.append(order)
        return {"status": "accepted", "broker_id": "b-1"}

    def lookup(self, key):
        return None


def _order(key="k-toctou"):
    return {"idempotency_key": key, "symbol": "NVDA", "side": "buy", "qty": 10, "order_type": "market"}


def test_unwrapped_client_has_the_toctou_race(switch):
    # Documents the bug the wrapper fixes: an early check passes, the kill
    # engages in the gap, and the naive client sends anyway.
    switch.beat()
    assert switch.check("submit") is None  # early gate: green
    raw = RawFakeBroker()
    raw(_order(), 1.0)  # no kill yet: sends fine
    assert len(raw.sent) == 1


def test_guarded_broker_refuses_at_send_time(switch, sessions):
    # The fix: the wrapper consults the gate at the last possible instant.
    # Kill engages AFTER the early check passed but BEFORE the wire call.
    switch.beat()
    assert switch.check("submit") is None  # early gate: green
    guarded = switch.guarded(RawFakeBroker())
    switch.engage(KillLevel.PAUSE_INTENTS, [sessions["op-ella"]], "halt in the gap")
    with pytest.raises(HaltedError):
        guarded(_order(), 1.0)  # refused at send time — nothing touched the wire
    assert guarded._broker.sent == []


def test_guarded_broker_lookup_never_gated(switch, sessions):
    # Reconcile reads are truth-seeking, not effects — even at FULL_STOP.
    switch.beat()
    guarded = switch.guarded(RawFakeBroker())
    switch.engage(
        KillLevel.FULL_STOP,
        [sessions["admin-ruth"], sessions["admin-sam"]],
        "freeze everything",
    )
    assert guarded.lookup("k-1") is None  # passes through, ungated
    with pytest.raises(HaltedError):
        guarded(_order(), 1.0)


def test_guarded_broker_is_transparent_when_healthy(switch):
    switch.beat()
    guarded = switch.guarded(RawFakeBroker())
    assert guarded(_order(), 1.0)["status"] == "accepted"
    assert len(guarded._broker.sent) == 1


# ------------------------------------------------------------ hard limits
def test_auto_halt_on_drawdown(registry, sessions):
    monitor = RiskMonitor(registry, max_daily_drawdown=0.03)
    sw = KillSwitch(
        registry,
        clock=FakeClock(),
        flatten_fn=lambda scope: "flattened 4 positions",
    )
    sw.beat()
    monitor.record_equity(100_000)
    monitor.record_equity(101_000)  # new peak
    assert monitor.check(sw) is False
    monitor.record_equity(97_800)  # (101000-97800)/101000 = 3.17%
    assert monitor.check(sw) is True
    assert sw.level == KillLevel.FLATTEN_HALT
    entry = sw.audit()[-1]
    assert entry["by"] == [SYSTEM_ACTOR]
    assert "3.17%" in entry["reason"]


def test_auto_halt_needs_admin_to_disarm(registry, sessions):
    monitor = RiskMonitor(registry, max_daily_drawdown=0.03)
    sw = KillSwitch(registry, clock=FakeClock())
    sw.beat()
    monitor.record_equity(100_000)
    monitor.record_equity(96_000)
    assert monitor.check(sw) is True
    # The machine that stopped you doesn't restart you: risk_officer is
    # not strictly above the monitor's own rank.
    with pytest.raises(KillAuthError):
        sw.disarm(sessions["risk-ana"], "looks fine")
    sw.disarm(sessions["admin-ruth"], "drawdown was a bad corporate-action adjustment; data fixed")
    assert sw.level == KillLevel.NONE


def test_monitor_holds_verified_system_session(registry):
    monitor = RiskMonitor(registry, max_daily_drawdown=0.03)
    verified = registry.verify(monitor._actor)
    assert verified.operator_id == SYSTEM_ACTOR
    assert verified.role == "risk_officer"


def test_drawdown_resets_on_new_peak(registry):
    monitor = RiskMonitor(registry, max_daily_drawdown=0.03)
    monitor.record_equity(100_000)
    monitor.record_equity(98_000)  # 2% — under the limit
    assert monitor.drawdown() == pytest.approx(0.02)
    monitor.record_equity(105_000)  # new peak resets the drawdown
    assert monitor.drawdown() == pytest.approx(0.0)


# ------------------------------------------------------------ chaos drills
def test_kill_during_open_order_leaves_ledger_consistent(switch, sessions):
    # The dangerous moment: broker accepted the order, fill pending, and
    # the operator kills. The wired cancel effect must pull the open
    # order exactly once; no new submits afterwards; reconcile still works.
    holder = {}
    killer = KillSwitch(
        switch._registry,
        clock=FakeClock(),
        cancel_open_fn=lambda scope: holder["ex"].cancel_all(scope),
    )
    ex = FakeExecutor(killer)
    holder["ex"] = ex
    killer.beat()
    ex.submit("k-1")
    ex.on_accept("k-1")
    assert ex.reconcile("k-1") == "open"

    killer.engage(KillLevel.CANCEL_OPEN, [sessions["op-ella"]], "kill during open fill")
    assert ex.ledger["k-1"] == "cancelled"  # opens pulled, exactly once
    with pytest.raises(HaltedError):
        ex.submit("k-2")  # no new effects after the kill
    assert "k-2" not in ex.ledger  # refused BEFORE any ledger mutation: no phantom row
    assert ex.reconcile("k-1") == "cancelled"  # truth-seeking still works under kill
    entry = killer.audit()[-1]
    assert entry["effects"][0]["name"] == "cancel_open"
    assert entry["effects"][0]["ok"] is True


def test_kill_during_reconcile_sweep(switch, sessions):
    # The sweep from Ch 10 runs under kill: reconcile is read-only, so the
    # kill must not stop it — unknown states still get resolved.
    ex = FakeExecutor(switch)
    switch.beat()
    ex.submit("k-9")
    switch.engage(
        KillLevel.FULL_STOP,
        [sessions["op-ella"], sessions["op-marcus"]],
        "freeze everything",
    )
    assert ex.reconcile("k-9") == "submitted"  # allowed even at FULL_STOP
    with pytest.raises(HaltedError):
        ex.submit("k-10")


def test_audit_log_is_append_only_and_complete(switch, sessions):
    switch.beat()
    switch.engage(KillLevel.PAUSE_INTENTS, [sessions["op-ella"]], "drill")
    switch.disarm(sessions["risk-ana"], "drill complete, all green")
    events = [e["event"] for e in switch.audit()]
    assert events == ["engage", "disarm"]
    assert all("ts" in e and "by" in e and "reason" in e for e in switch.audit())
    # Callers get copies: mutating the return must not rewrite history.
    switch.audit().clear()
    assert len(switch.audit()) == 2


class FakeExecutor:
    """Mirrors the Ch 10 binding contract: early check() BEFORE any ledger
    mutation, so a refused submit leaves no phantom state. Production
    pairs this with the guarded() wrapper for the send-time check."""

    def __init__(self, killswitch):
        self.kill = killswitch
        self.ledger = {}  # key -> status

    def submit(self, key, scope=None):
        self.kill.check("submit", scope=scope)
        self.ledger[key] = "submitted"
        return key

    def on_accept(self, key):
        self.ledger[key] = "open"

    def cancel_all(self, scope=None):
        self.kill.check("cancel", scope=scope)
        cancelled = [k for k, s in self.ledger.items() if s == "open"]
        for k in cancelled:
            self.ledger[k] = "cancelled"
        return f"cancelled {len(cancelled)}"

    def reconcile(self, key, scope=None):
        self.kill.check("reconcile", scope=scope)
        return self.ledger.get(key)


# ----------------------------------- drill against the REAL Ch 10 machinery
def test_drill_real_ledger_kill_leaves_no_phantom_row(tmp_path, registry, sessions):
    """The honesty drill: FakeExecutor proves the ORDER of operations, but
    only the REAL Ch 10 Ledger proves no phantom row exists — a dict
    cannot have write-ahead semantics.

    What this drill proves: the kill gate composes with the production
    SQLite ledger — a refused submit writes nothing. What it does NOT
    prove: graceful degradation under live network conditions (timeouts,
    half-open connections, broker-side partial fills). That needs network
    fault injection — a proxy that drops packets on command — which is a
    production game-day exercise, not a unit test.
    """
    from action_executor import ActionExecutor, Ledger

    tick = {"t": datetime(2026, 9, 11, 9, 30, tzinfo=timezone.utc)}

    def dt_clock():
        return tick["t"]

    ledger = Ledger(path=str(tmp_path / "ledger.db"), clock=dt_clock)
    ex = ActionExecutor(ledger, timeout=1.0, max_retries=1, backoff=0)

    clock = FakeClock()
    sw = KillSwitch(registry, heartbeat_window_s=30.0, clock=clock)
    sw.beat()

    broker = RawFakeBroker()
    guarded = sw.guarded(broker)

    order = {
        "idempotency_key": "k-real-1",
        "symbol": "NVDA",
        "side": "buy",
        "qty": 10,
        "order_type": "market",
    }
    rec = ex.execute(order, guarded)
    assert rec["status"] == "open"  # broker accepted; fill pending

    # Kill engages mid-flight. The caller's early gate refuses BEFORE the
    # write-ahead row — against the REAL ledger, not a dict.
    sw.engage(KillLevel.CANCEL_OPEN, [sessions["op-ella"]], "kill during open fill")
    order2 = dict(order, idempotency_key="k-real-2")
    with pytest.raises(HaltedError):
        sw.check("submit")  # early gate refuses; execute() is never called
    assert ledger.get("k-real-2") is None  # no phantom row in SQLite either

    # Reconcile still resolves the open row against broker truth.
    broker_lookup = {"k-real-1": {"status": "filled", "broker_id": "b-1",
                                 "filled_qty": 10.0, "avg_price": 181.2}}
    broker.lookup = lambda key: broker_lookup.get(key)
    resolved = ex.reconcile(guarded)
    assert resolved[0]["status"] == "filled"
    assert ledger.get("k-real-1")["status"] == "filled"


def test_drill_real_ledger_toctou_late_gate(tmp_path, registry, sessions):
    """The TOCTOU drill against the real executor: the early check passes,
    the kill engages, and the guarded wrapper refuses at the wire — the
    ledger keeps the honest 'submitted' row, which the next sweep resolves
    instead of anyone guessing."""
    from action_executor import ActionExecutor, Ledger

    tick = {"t": datetime(2026, 9, 11, 9, 30, tzinfo=timezone.utc)}
    ledger = Ledger(path=str(tmp_path / "ledger2.db"), clock=lambda: tick["t"])
    ex = ActionExecutor(ledger, timeout=1.0, max_retries=1, backoff=0)

    clock = FakeClock()
    sw = KillSwitch(registry, heartbeat_window_s=30.0, clock=clock)
    sw.beat()
    broker = RawFakeBroker()
    guarded = sw.guarded(broker)

    order = {
        "idempotency_key": "k-real-3",
        "symbol": "NVDA",
        "side": "buy",
        "qty": 10,
        "order_type": "market",
    }
    sw.check("submit")  # early gate: green — the ledger write proceeds
    sw.engage(KillLevel.PAUSE_INTENTS, [sessions["op-ella"]], "halt in the gap")
    with pytest.raises(HaltedError):
        ex.execute(order, guarded)  # late gate refuses at the wire
    assert broker.sent == []  # nothing reached the broker
    row = ledger.get("k-real-3")
    # The write-ahead row exists ('submitted') — honest, not phantom: the
    # system TRIED and was refused at the wire. The sweep resolves it.
    assert row is not None and row["status"] == "submitted"
    resolved = ex.reconcile(guarded)
    # Broker never saw it and the settle window (60s) hasn't passed... it
    # stays pending — correctly unresolved, never guessed.
    assert resolved[0]["status"] == "submitted"
