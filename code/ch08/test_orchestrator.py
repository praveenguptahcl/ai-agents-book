"""Adversarial tests for the orchestrator: every refusal must fire, every
poison must be quarantined, and the happy path must prove the discipline
works — not just that it exists."""

import pytest

from orchestrator import (
    Budget,
    CycleDetected,
    DelegationContext,
    DepthExceeded,
    Observation,
    Orchestrator,
    ScopeDenied,
    TenantMismatch,
    UnknownWorker,
    WorkerResult,
    WorkerSpec,
)

SECRET_AUTHORITY = {"market.read", "orders.propose", "risk.veto", "risk.read"}


def make_orc(**kw):
    kw.setdefault("authority", set(SECRET_AUTHORITY))
    kw.setdefault("tenant_id", "desk-alpha")
    return Orchestrator(**kw)


def ok_result(ctx: DelegationContext, summary="done", verdict="approve",
              tokens=120, provenance="SYNTHETIC"):
    return {
        "task_id": ctx.delegation_id,
        "worker": ctx.worker,
        "status": "ok",
        "verdict": verdict,
        "summary": summary,
        "observations": [
            {"kind": "quote", "detail": "NVDA 187.42",
             "provenance": provenance, "as_of": "2026-09-11T15:30:00Z"}
        ],
        "cost_tokens": tokens,
    }


def register_echo(orc, name="research", scopes=("market.read",), fn=None):
    fn = fn or (lambda ctx, payload: ok_result(ctx))
    orc.register(WorkerSpec(name=name, declared_scopes=frozenset(scopes),
                            dispatch=fn))
    return orc


# -- happy path ------------------------------------------------------------


def test_happy_path_merges_evidence_into_trace():
    orc = register_echo(make_orc())
    rec = orc.delegate("research", "pull NVDA fundamentals", {"market.read"})
    assert rec.status == "ok"
    assert rec.evidence is not None
    assert rec.evidence.observations[0].provenance == "SYNTHETIC"
    assert rec.tenant_id == "desk-alpha"  # handoff preserves tenant (Ch 6)
    assert rec.granted_scopes == frozenset({"market.read"})
    assert len(orc.trace) == 1


# -- attenuation: the ceiling holds -----------------------------------------


def test_scope_beyond_orchestrator_authority_is_refused_not_narrowed():
    orc = register_echo(make_orc())
    with pytest.raises(ScopeDenied):
        orc.delegate("research", "propose an order",
                     {"market.read", "orders.propose", "admin.wipe"})
    # Refused at the boundary: nothing was dispatched, nothing traced.
    assert orc.trace == []


def test_scope_beyond_worker_capability_is_refused():
    # The research worker is CAPABLE of market.read only. Asking it to
    # veto risk must fail — silently granting a scope the worker cannot
    # honor would produce a confusing half-success.
    orc = register_echo(make_orc())
    with pytest.raises(ScopeDenied):
        orc.delegate("research", "veto this trade", {"risk.veto"})


def test_research_worker_may_never_propose_orders():
    # The trading-desk invariant: research reads, risk vetoes, the
    # signal agent proposes. Scopes enforce the org chart.
    orc = make_orc()
    orc.register(WorkerSpec(
        name="research", declared_scopes=frozenset({"market.read"}),
        dispatch=lambda ctx, p: ok_result(ctx)))
    orc.register(WorkerSpec(
        name="risk", declared_scopes=frozenset({"risk.read", "risk.veto"}),
        dispatch=lambda ctx, p: ok_result(ctx, verdict="veto",
                                          summary="drawdown breach")))
    with pytest.raises(ScopeDenied):
        orc.delegate("research", "propose AAPL order", {"orders.propose"})
    rec = orc.delegate("risk", "check drawdown", {"risk.veto"})
    assert rec.status == "ok" and rec.evidence.verdict == "veto"


def test_unknown_worker():
    orc = make_orc()
    with pytest.raises(UnknownWorker):
        orc.delegate("ghost", "anything", {"market.read"})


# -- depth ------------------------------------------------------------------


def test_depth_exceeded():
    orc = register_echo(make_orc(max_depth=1))
    with pytest.raises(DepthExceeded):
        orc.delegate("research", "too deep", {"market.read"}, depth=5)


def test_sub_delegate_must_narrow_again():
    orc = make_orc(max_depth=3)
    captured = {}

    def parent_dispatch(ctx, payload):
        captured["ctx"] = ctx
        return ok_result(ctx)

    orc.register(WorkerSpec(name="parent",
                            declared_scopes=frozenset({"market.read"}),
                            dispatch=parent_dispatch))
    orc.register(WorkerSpec(name="child",
                            declared_scopes=frozenset({"market.read"}),
                            dispatch=lambda ctx, p: ok_result(ctx)))
    rec = orc.delegate("parent", "do it", {"market.read"})
    ctx = captured["ctx"]
    # Narrowing further is fine.
    sub = orc.sub_delegate(ctx, "child", "help", {"market.read"})
    assert sub.status == "ok" and sub.depth == 1
    assert sub.parent_id == rec.delegation_id
    # Widening beyond the parent's grant is refused.
    with pytest.raises(ScopeDenied):
        orc.sub_delegate(ctx, "child", "help",
                         {"market.read", "orders.propose"})
    # Cross-tenant delegation is not a feature.
    with pytest.raises(TenantMismatch):
        orc.sub_delegate(ctx, "child", "help", {"market.read"},
                         tenant_id="desk-beta")


# -- cycle guard -------------------------------------------------------------


def test_peer_cycle_is_detected():
    orc = make_orc()
    orc.register(WorkerSpec(
        name="a", declared_scopes=frozenset({"market.read"}),
        dispatch=lambda ctx, p: (
            orc.delegate("b", "b help a", {"market.read"},
                         depth=ctx.depth + 1,
                         parent_id=ctx.delegation_id),
            ok_result(ctx))[1]))  # a real worker returns its OWN result dict;
    # the sub-delegation is a side effect, not the return value
    orc.register(WorkerSpec(
        name="b", declared_scopes=frozenset({"market.read"}),
        dispatch=lambda ctx, p: orc.delegate(
            "a", "a help b", {"market.read"}, depth=ctx.depth + 1,
            parent_id=ctx.delegation_id)))
    rec = orc.delegate("a", "start", {"market.read"})
    # The cycle was caught at b -> a; b's delegation records the refusal.
    b_rec = next(r for r in orc.trace if r.worker == "b")
    assert b_rec.status == "failed"
    assert "CycleDetected" in (b_rec.failure or "")
    assert "a -> b -> a" in (b_rec.failure or "")


# -- evidence discipline ------------------------------------------------------


def test_poisoned_evidence_extra_field_is_quarantined():
    orc = register_echo(make_orc(), fn=lambda ctx, p: {
        **ok_result(ctx), "execute_now": True,  # injected field
    })
    rec = orc.delegate("research", "pull data", {"market.read"})
    assert rec.status == "quarantined"
    assert rec.evidence is None  # never merged
    assert len(orc.quarantine) == 1  # kept for forensics


def test_poisoned_evidence_bad_provenance_is_quarantined():
    # "REAL" and "SYNTHETIC" are the only valid provenance values — the
    # point of this test is the shape, not the label. An invented third
    # provenance ("TRUSTME") must fail validation and be quarantined.
    orc = register_echo(
        make_orc(), name="research", scopes=("market.read",),
        fn=lambda ctx, p: {**ok_result(ctx),
                           "observations": [{"kind": "quote",
                                             "detail": "x",
                                             "provenance": "TRUSTME",
                                             "as_of": "now"}]})
    rec = orc.delegate("research", "pull data", {"market.read"})
    assert rec.status == "quarantined"


def test_worker_identity_laundering_is_quarantined():
    orc = register_echo(make_orc(), fn=lambda ctx, p: {
        **ok_result(ctx), "worker": "risk",  # claims to be someone else
    })
    rec = orc.delegate("research", "pull data", {"market.read"})
    assert rec.status == "quarantined"
    assert "identity mismatch" in (rec.failure or "")


# -- failure semantics ----------------------------------------------------------


def test_timeout_leaves_delegation_open_not_failed():
    def silent(ctx, payload):
        raise TimeoutError("worker went silent")

    orc = register_echo(make_orc(), fn=silent)
    rec = orc.delegate("research", "pull data", {"market.read"})
    assert rec.status == "open"  # Ch 2's rule: the loop stays open
    assert "timeout" in (rec.failure or "")


def test_reconcile_closes_open_delegation_with_same_validation():
    def silent(ctx, payload):
        raise TimeoutError("worker went silent")

    orc = register_echo(make_orc(), fn=silent)
    rec = orc.delegate("research", "pull data", {"market.read"})
    late = ok_result(
        DelegationContext(
            delegation_id=rec.delegation_id, task="pull data",
            worker="research", tenant_id="desk-alpha",
            granted_scopes=frozenset({"market.read"}), depth=0,
            token_budget=4000, timeout_s=30.0),
        summary="late answer", tokens=40)
    closed = orc.reconcile(rec.delegation_id, late)
    assert closed.status == "ok"
    assert closed.evidence.summary == "late answer"
    # A late answer is still untrusted: poison fails reconciliation too.
    rec2 = orc.delegate("research", "pull more", {"market.read"})
    closed2 = orc.reconcile(rec2.delegation_id, {"garbage": 1})
    assert closed2.status == "quarantined"


def test_worker_crash_is_recorded_not_retried_here():
    def boom(ctx, payload):
        raise RuntimeError("segfault in worker")

    orc = register_echo(make_orc(), fn=boom)
    rec = orc.delegate("research", "pull data", {"market.read"})
    assert rec.status == "failed"
    assert "RuntimeError" in (rec.failure or "")


def test_transport_returning_non_dict_is_worker_failed():
    # The dispatch seam promises a dict. A worker that returns anything
    # else cannot speak the evidence protocol and cannot be trusted.
    orc = register_echo(make_orc(), fn=lambda ctx, p: "trust me")
    rec = orc.delegate("research", "pull data", {"market.read"})
    assert rec.status == "failed"
    assert "not a dict" in (rec.failure or "")
# -- budgets: the leash ---------------------------------------------------------


def test_token_budget_exhaustion_halts():
    orc = register_echo(
        make_orc(), fn=lambda ctx, p: ok_result(ctx, tokens=10_000))
    rec = orc.delegate("research", "pull data", {"market.read"},
                         budget=Budget(max_tokens=4_000, max_seconds=30.0))
    assert rec.status == "failed"
    assert "budget exhausted" in (rec.failure or "")


def test_latency_budget_exhaustion_halts():
    now = [1000.0]

    def slow(ctx, payload):
        now[0] += 45.0  # the worker burned 45 seconds
        return ok_result(ctx, tokens=10)

    orc = register_echo(make_orc(clock=lambda: now[0]), fn=slow)
    rec = orc.delegate("research", "pull data", {"market.read"},
                       budget=Budget(max_tokens=4_000, max_seconds=30.0))
    assert rec.status == "failed"
    assert rec.latency_s == pytest.approx(45.0)


def test_unaccounted_spend_fails_closed():
    # A worker that cannot account for its own cost is treated as having
    # spent its entire budget. No free compute.
    orc = register_echo(make_orc(),
                        fn=lambda ctx, p: {k: v for k, v in
                                           ok_result(ctx).items()
                                           if k != "cost_tokens"})
    rec = orc.delegate("research", "pull data", {"market.read"})
    assert rec.status == "failed"
    assert "unaccounted spend" in (rec.failure or "")
    # The worksheet shows the budget line, not a poisoned integer.
    assert rec.cost_tokens == 4_000


# -- adjudication: the supervisor decides ----------------------------------------


def _result(worker, verdict, summary="s"):
    return WorkerResult(task_id="t", worker=worker, status="ok",
                        verdict=verdict, summary=summary,
                        cost_tokens=10)


def test_veto_wins():
    orc = make_orc()
    out = orc.adjudicate([_result("signal", "approve", "momentum long"),
                          _result("risk", "veto", "drawdown breach")])
    assert out["decision"] == "blocked"
    assert "drawdown breach" in out["reason"]


def test_unanimous_approval():
    orc = make_orc()
    out = orc.adjudicate([_result("signal", "approve"),
                          _result("research", "approve")])
    assert out["decision"] == "approved"


def test_contested_without_veto_escalates():
    orc = make_orc()
    out = orc.adjudicate([_result("signal", "approve"),
                          _result("research", "abstain")])
    assert out["decision"] == "contested"


# -- the cost model of the second call ----------------------------------------------


def test_cost_worksheet_accounts_every_delegation():
    orc = make_orc()
    for i, name in enumerate(["research", "risk", "settle"]):
        orc.register(WorkerSpec(
            name=name, declared_scopes=frozenset({"market.read"}),
            dispatch=lambda ctx, p, t=100 * (i + 1): ok_result(ctx,
                                                               tokens=t)))
    for name in ["research", "risk", "settle"]:
        orc.delegate(name, "work", {"market.read"})
    sheet = orc.cost_worksheet()
    assert sheet["delegations"] == 3
    assert sheet["total_tokens"] == 600  # 100 + 200 + 300, no hidden lines
    assert sheet["quarantined"] == 0 and sheet["open"] == 0


# -- review fixes: reconcile enforces budget and identity --------------------

def test_reconcile_rejects_late_result_over_budget():
    # A timed-out worker does not earn unbounded spend for being late:
    # the late result is checked against the budget stored on the record.
    def silent(ctx, payload):
        raise TimeoutError("worker went silent")

    orc = register_echo(make_orc(), fn=silent)
    rec = orc.delegate("research", "pull data", {"market.read"},
                       budget=Budget(max_tokens=4_000, max_seconds=30.0))
    assert rec.token_budget == 4_000  # the budget rides on the record
    late = ok_result(
        DelegationContext(
            delegation_id=rec.delegation_id, task="pull data",
            worker="research", tenant_id="desk-alpha",
            granted_scopes=frozenset({"market.read"}), depth=0,
            token_budget=4000, timeout_s=30.0),
        summary="late and expensive", tokens=50_000)
    closed = orc.reconcile(rec.delegation_id, late)
    assert closed.status == "failed"
    assert "exceeded delegation budget" in (closed.failure or "")


def test_reconcile_quarantines_late_identity_laundering():
    def silent(ctx, payload):
        raise TimeoutError("worker went silent")

    orc = register_echo(make_orc(), fn=silent)
    rec = orc.delegate("research", "pull data", {"market.read"})
    ctx = DelegationContext(
        delegation_id=rec.delegation_id, task="pull data",
        worker="research", tenant_id="desk-alpha",
        granted_scopes=frozenset({"market.read"}), depth=0,
        token_budget=4000, timeout_s=30.0)
    late = {**ok_result(ctx, summary="late"), "worker": "risk"}
    closed = orc.reconcile(rec.delegation_id, late)
    assert closed.status == "quarantined"
    assert "identity mismatch" in (closed.failure or "")
    assert len(orc.quarantine) == 1


def test_reconcile_within_budget_closes_ok():
    def silent(ctx, payload):
        raise TimeoutError("worker went silent")

    orc = register_echo(make_orc(), fn=silent)
    rec = orc.delegate("research", "pull data", {"market.read"},
                       budget=Budget(max_tokens=4_000, max_seconds=30.0))
    ctx = DelegationContext(
        delegation_id=rec.delegation_id, task="pull data",
        worker="research", tenant_id="desk-alpha",
        granted_scopes=frozenset({"market.read"}), depth=0,
        token_budget=4000, timeout_s=30.0)
    closed = orc.reconcile(rec.delegation_id, ok_result(ctx, tokens=40))
    assert closed.status == "ok"
    assert closed.cost_tokens == 40


# -- review fixes: budget attenuation in sub_delegate -------------------------

def test_sub_delegate_refuses_child_budget_above_parent():
    orc = make_orc(max_depth=3)
    captured = {}

    def parent_dispatch(ctx, payload):
        captured["ctx"] = ctx
        return ok_result(ctx)

    orc.register(WorkerSpec(name="parent",
                            declared_scopes=frozenset({"market.read"}),
                            dispatch=parent_dispatch))
    orc.register(WorkerSpec(name="child",
                            declared_scopes=frozenset({"market.read"}),
                            dispatch=lambda ctx, p: ok_result(ctx)))
    rec = orc.delegate("parent", "do it", {"market.read"},
                       budget=Budget(max_tokens=1_000, max_seconds=10.0))
    ctx = captured["ctx"]
    assert ctx.token_budget == 1_000
    # Asking for more than the parent holds is ScopeDenied — budgets
    # attenuate, they do not widen.
    with pytest.raises(ScopeDenied):
        orc.sub_delegate(ctx, "child", "help", {"market.read"},
                         budget=Budget(max_tokens=5_000, max_seconds=10.0))
    with pytest.raises(ScopeDenied):
        orc.sub_delegate(ctx, "child", "help", {"market.read"},
                         budget=Budget(max_tokens=500, max_seconds=60.0))
    # Narrowing the budget is fine.
    sub = orc.sub_delegate(ctx, "child", "help", {"market.read"},
                           budget=Budget(max_tokens=500, max_seconds=5.0))
    assert sub.status == "ok"
    assert sub.token_budget == 500


def test_sub_delegate_defaults_to_parent_bounded_budget():
    # No budget passed: the child gets the parent's budget, never a
    # fresh default that would let N agents spend N x the limit.
    orc = make_orc(max_depth=3)
    captured = {}

    def parent_dispatch(ctx, payload):
        captured["ctx"] = ctx
        return ok_result(ctx)

    orc.register(WorkerSpec(name="parent",
                            declared_scopes=frozenset({"market.read"}),
                            dispatch=parent_dispatch))
    orc.register(WorkerSpec(name="child",
                            declared_scopes=frozenset({"market.read"}),
                            dispatch=lambda ctx, p: ok_result(ctx)))
    orc.delegate("parent", "do it", {"market.read"},
                 budget=Budget(max_tokens=1_000, max_seconds=10.0))
    sub = orc.sub_delegate(captured["ctx"], "child", "help",
                           {"market.read"})
    assert sub.status == "ok"
    assert sub.token_budget == 1_000
    assert sub.timeout_s == 10.0
