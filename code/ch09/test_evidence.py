"""Tests for Ch 9 evidence routing. Every test is framed as the failure it
prevents: evidence that can be rewritten, skipped, leaked across tenants,
re-labeled, truncated, or silently dropped is not evidence.

Tenant identity comes from real Ch 6 verified sessions: the router binds
the session's tenant_id, never a caller-supplied string.
"""

import datetime
import hashlib
import json
import os
import secrets
import sys
import threading

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "ch06"))
from tenant import TenantStore  # noqa: E402  (verified sessions, Ch 6)

from evidence import (  # noqa: E402
    AuditLog, EvalDataset, EvidenceRouter, TraceSink,
    EVENT_TYPES, EVAL_TYPES, TRACE_TYPES, _canonical,
)


@pytest.fixture
def store():
    s = TenantStore(secrets.token_bytes(32))
    s.register("t-ava", "Ava")
    s.register("t-ben", "Ben")
    return s


@pytest.fixture
def ava(store):
    return store.issue("t-ava", scopes=("submit",))


@pytest.fixture
def ben(store):
    return store.issue("t-ben", scopes=("submit",))


@pytest.fixture
def router():
    return EvidenceRouter(trace_capacity=100)


def emit(router, session, etype="broker_response", **payload):
    return router.emit(session, etype, payload or {"broker_id": "b1"})


# --- tamper evidence ---------------------------------------------------------

def test_chain_verifies_when_untampered(router, ava):
    for i in range(5):
        emit(router, ava, etype="tool_call", seq=i)
    ok, bad = router.verify()
    assert ok and bad is None


def test_tampered_payload_breaks_chain(router, ava):
    emit(router, ava, etype="intent_record", symbol="AAPL")
    emit(router, ava, etype="tool_call", tool="submit_order")
    emit(router, ava, etype="broker_response", status="filled")
    router.audit._entries[1]["payload"]["tool"] = "cancel_all_orders"  # attacker
    ok, bad = router.verify()
    assert not ok and bad == 1  # first broken link, not just "something's wrong"


def test_tampered_prev_hash_breaks_chain(router, ava):
    emit(router, ava, etype="intent_record")
    emit(router, ava, etype="broker_response")
    router.audit._entries[1]["prev_hash"] = "f" * 64
    ok, bad = router.verify()
    assert not ok and bad == 1


def test_hash_commits_to_tenant_and_type(router, ava):
    # Swapping the tenant label on an entry must break the chain too —
    # otherwise evidence could be re-attributed to another tenant.
    emit(router, ava, etype="broker_response")
    router.audit._entries[0]["tenant_id"] = "t-ben"
    ok, bad = router.verify()
    assert not ok and bad == 0


def test_audit_log_rejects_keyless_construction():
    # There is no "signing context" without a key. Refuse to exist without one.
    with pytest.raises((TypeError, ValueError)):
        AuditLog(None)
    with pytest.raises(ValueError):
        AuditLog(b"too-short")


def test_attacker_without_key_cannot_rewrite_chain(router, ava):
    # The old attack, for reference: the adversary has memory access, rewrites
    # an entry, and recomputes the chain with a plain unkeyed SHA-256 (what
    # the pre-HMAC code used). Without the HMAC key the forged links never
    # match, and verify_chain names the exact entry.
    emit(router, ava, etype="intent_record", symbol="AAPL")
    emit(router, ava, etype="broker_response", status="filled")
    victim = router.audit._entries[0]
    victim["payload"]["symbol"] = "GME"  # the rewrite
    for e in router.audit._entries:      # the best forgery money can't buy
        body = _canonical({
            "seq": e["seq"], "ts": e["ts"], "mono": e["mono"],
            "tenant_id": e["tenant_id"], "event_type": e["event_type"],
            "payload": e["payload"], "prev_hash": e["prev_hash"],
        })
        e["entry_hash"] = hashlib.sha256(body.encode()).hexdigest()
    ok, bad = router.verify()
    assert not ok and bad == 0


def test_concurrent_emits_keep_chain_intact(router, ava, ben):
    # Two strategies, one process, same instant. Without the lock in _append,
    # two threads read the same len()/prev_hash and one link is orphaned.
    errors = []

    def hammer(session, n):
        try:
            for i in range(n):
                emit(router, session, etype="tool_call", seq=i)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=hammer, args=(s, 50))
               for s in (ava, ben) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(router.audit) == 400
    ok, bad = router.verify()
    assert ok and bad is None
    seqs = sorted(e["seq"] for e in router.audit._entries)
    assert seqs == list(range(400))  # no gaps, no duplicates


# --- truncation: the blindspot, and the anchor that closes it ----------------

def test_truncation_is_invisible_to_local_verification(router, ava):
    # Deleting the tail leaves a perfectly valid chain. This test documents
    # the blindspot so nobody deploys on the belief that verify_chain()
    # catches it.
    for i in range(10):
        emit(router, ava, etype="tool_call", seq=i)
    del router.audit._entries[-3:]  # the quiet crime
    ok, _ = router.verify()
    assert ok  # local verification cannot see it


def test_checkpoint_anchor_detects_truncation(router, ava):
    # The infrastructure anchors (seq, head_hash) to WORM storage. After
    # truncation the local chain verifies, but the head no longer matches
    # the anchor — and that mismatch is the detection.
    for i in range(10):
        emit(router, ava, etype="tool_call", seq=i)
    anchored_head = router.audit.checkpoint()  # -> WORM, on a schedule
    anchored_seq = len(router.audit) - 1
    del router.audit._entries[-3:]
    assert router.verify()[0]  # still "valid" locally...
    assert (len(router.audit) - 1, router.audit.checkpoint()) != (
        anchored_seq, anchored_head)  # ...but the anchor disagrees


def test_checkpoint_of_empty_log_is_genesis():
    log = AuditLog(secrets.token_bytes(32))
    assert log.checkpoint() == AuditLog.GENESIS


# --- the agent cannot write directly ------------------------------------------

def test_audit_log_has_no_public_write_path():
    public_writers = [n for n in dir(AuditLog)
                      if not n.startswith("_") and n not in
                      ("read", "verify_chain", "checkpoint")  # reads, not writes
                      and not n.isupper()]  # class constants are not write paths
    # __len__/__init__ etc. are dunder; read/verify_chain/checkpoint are reads.
    writers = [n for n in public_writers if not (n.startswith("__") and n.endswith("__"))]
    assert writers == [], f"public write path exists: {writers}"


def test_emit_is_the_only_way_evidence_lands(router, ava):
    emit(router, ava, etype="kill_switch", reason="drawdown")
    assert len(router.audit) == 1
    assert router.audit.read("t-ava")[0]["event_type"] == "kill_switch"


def test_emit_rejects_bare_string_tenant(router):
    # A string is a claim, not a proof. The session is the proof.
    with pytest.raises(TypeError):
        router.emit("t-ava", "tool_call", {"tool": "x"})
    with pytest.raises(TypeError):
        router.emit(None, "tool_call", {"tool": "x"})


def test_session_tenant_cannot_be_spoofed(router, ava, ben):
    # The caller hands us ava's verified session but a payload claiming to
    # be ben's business. The entry lands under ava — the proof, not the word.
    entry = router.emit(ava, "broker_response",
                        {"tenant_id": "t-ben", "qty": 999})
    assert entry["tenant_id"] == "t-ava"
    assert router.audit.read("t-ben") == []
    assert router.trace.read("t-ben") == []
    assert router.evalset.records("t-ben") == []


# --- tenant partitioning -------------------------------------------------------

def test_tenant_read_returns_absence_not_error(router, ava, ben):
    emit(router, ava, etype="broker_response", qty=100)
    emit(router, ben, etype="broker_response", qty=999)
    ava_entries = router.audit.read("t-ava")
    assert [e["payload"]["qty"] for e in ava_entries] == [100]
    # No error, no hint of t-ben's entry: absence, per Ch 6's convention.
    assert router.audit.read("t- NOBODY".strip()) == []


def test_trace_and_eval_are_tenant_scoped(router, ava, ben):
    emit(router, ava, etype="tool_call", tool="get_quote")
    emit(router, ben, etype="tool_call", tool="dump_positions")
    assert [e["payload"]["tool"] for e in router.trace.read("t-ava")] == ["get_quote"]
    assert [r["payload"]["tool"] for r in router.evalset.records("t-ava")] == ["get_quote"]


# --- routing --------------------------------------------------------------------

def test_everything_lands_in_audit(router, ava):
    for etype in EVENT_TYPES:
        emit(router, ava, etype=etype, probe=True)
    seen = {e["event_type"] for e in router.audit.read("t-ava")}
    assert seen == set(EVENT_TYPES)


def test_trace_gets_operational_types_only(router, ava):
    for etype in EVENT_TYPES:
        emit(router, ava, etype=etype, probe=True)
    seen = {e["event_type"] for e in router.trace.read("t-ava")}
    assert seen == set(TRACE_TYPES)


def test_eval_gets_curated_types_only(router, ava):
    for etype in EVENT_TYPES:
        emit(router, ava, etype=etype, probe=True)
    seen = {r["event_type"] for r in router.evalset.records("t-ava")}
    assert seen == set(EVAL_TYPES)
    # authority_check is plumbing, not judgeable: audited, never evaluated.
    assert "authority_check" not in seen


def test_unknown_event_type_fails_closed_never_dropped(router, ava):
    entry = router.emit(ava, "mind_meld", {"x": 1})
    assert entry["flagged"] is True
    audited = router.audit.read("t-ava")
    assert any(e["event_type"] == "mind_meld" and e["flagged"] for e in audited)
    # ...and it went nowhere else. The misconfiguration is evidence now.
    assert router.trace.read("t-ava") == []
    assert router.evalset.records("t-ava") == []


def test_unserializable_payload_is_evidence_not_a_crash(router, ava):
    # A circular payload must not take the evidence layer down with it — and
    # the failure must itself be recorded, not swallowed.
    loop = {}
    loop["self"] = loop
    entry = router.emit(ava, "tool_call", {"nested": loop})
    assert entry["payload"]["serialization_failed"] is True
    assert "raw_repr" in entry["payload"]
    assert entry["flagged"] is True
    assert router.verify()[0]  # the chain still verifies


def test_entries_carry_dual_clocks(router, ava):
    for i in range(5):
        emit(router, ava, etype="tool_call", seq=i)
    entries = router.audit.read("t-ava")
    assert all("ts" in e and "mono" in e for e in entries)
    monos = [e["mono"] for e in entries]
    assert monos == sorted(monos)  # monotonic ordering holds


def test_trace_ring_buffer_discards_oldest(router, ava):
    for i in range(150):
        emit(router, ava, etype="tool_call", seq=i)
    assert len(router.trace) == 100
    seqs = [e["payload"]["seq"] for e in router.trace.read("t-ava")]
    assert seqs[0] == 50  # oldest evicted; audit log still holds all 150
    assert len(router.audit) == 150


def test_eval_records_are_frozen(router, ava):
    payload = {"symbol": "AAPL", "qty": 100}
    router.emit(ava, "intent_record", payload)
    payload["qty"] = 10_000  # caller mutates after the fact
    rec = router.evalset.records("t-ava")[0]
    assert rec["payload"]["qty"] == 100  # the judge saw the original


def test_eval_preserves_native_types(router, ava):
    # deepcopy freeze: datetimes, UUIDs, sets survive — the judge sees what
    # the tool returned, not a stringified shadow of it.
    ts = datetime.datetime(2026, 9, 11, 13, 41, 24)
    router.emit(ava, "tool_call", {"at": ts, "tags": {"fast", "backtest"}})
    rec = router.evalset.records("t-ava")[0]["payload"]
    assert isinstance(rec["at"], datetime.datetime) and rec["at"] == ts
    assert isinstance(rec["tags"], set) and rec["tags"] == {"fast", "backtest"}


def test_refusal_is_evidence(router, ava):
    # Ch 5's refusal must be recorded as a first-class event, not a log line.
    router.emit(ava, "refusal",
                {"category": "safety_filter", "attempts_before": 1})
    entry = router.audit.read("t-ava")[0]
    assert entry["event_type"] == "refusal"
    assert router.evalset.records("t-ava")[0]["event_type"] == "refusal"


def test_reconcile_events_reach_trace_but_not_eval(router, ava):
    emit(router, ava, etype="reconcile_event", key="k1", resolution="open")
    assert len(router.trace.read("t-ava")) == 1
    assert router.evalset.records("t-ava") == []  # plumbing, not judgement


def test_trace_sink_rejects_nonpositive_capacity():
    with pytest.raises(ValueError):
        TraceSink(capacity=0)


def test_entries_hash_commits_to_both_clocks(router, ava):
    # Rewriting the monotonic clock must break the chain too — ordering is
    # evidence, not decoration.
    emit(router, ava, etype="tool_call")
    router.audit._entries[0]["mono"] -= 1000.0
    ok, bad = router.verify()
    assert not ok and bad == 0
