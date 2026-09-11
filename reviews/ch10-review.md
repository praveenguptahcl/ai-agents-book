# Gemini Review — Ch 10: The Action Plane and Execution
- **Model:** Pro Extended (Gemini 3.1 Pro class)
- **Date:** 2026-09-11
- **Verdict:** REWRITE
- **Files reviewed:** ch10-action-plane.md, action_executor.py, test_action_executor.py (all attached and cited)

## Full verbatim review

Verdict: REWRITE

The foundation of using a write-ahead ledger and idempotency keys is excellent. However, the execution model has fatal distributed systems flaws. If a reader deploys this code against a live broker API, they will encounter double-fills and deadlocks.

### Technical & Code Findings

**Critical: Synchronous Fill Assumption.** action_executor.py crashes if it receives a non-terminal broker response. Real APIs return new or accepted before filling. Raising a ValueError on these responses leaves the order perpetually stuck. Just as a robust UVM testbench cannot assume a zero-cycle delay between a transaction and the DUT's acknowledgment, the executor cannot assume instantaneous fills. Introduce an open state.

**Critical: Read-After-Write Race Condition.** reconcile_key treats broker.lookup(key) == None as definitive proof to mark the order abandoned. Broker read-replicas often have replication lag. If a timeout occurs and reconcile() immediately hits a lagging read database, it will abandon an active order, allowing a resubmit and causing a catastrophic double-fill. You must enforce a settling time threshold before declaring a missing record abandoned.

**High: SQLite Concurrency.** sqlite3.connect defaults to blocking cross-thread calls. If the end-of-day sweep runs concurrently as the prose claims, check_same_thread=False and PRAGMA journal_mode=WAL; are mandatory to prevent database locking errors.

**Medium: Fragile Reconcile Sweep.** reconcile_key does not trap network exceptions. If the broker API times out during the end-of-day sweep, the uncaught exception will crash the entire reconciliation loop, leaving remaining orders unverified.

**Medium: Hardcoded Exceptions.** The retry loop only catches BrokerTimeout and BrokerError. You should explicitly state in the prose that the injected broker callable must act as an anti-corruption layer, trapping standard network errors (e.g., connection resets) and wrapping them into these domain exceptions.

### Pedagogy & Prose

**Align the Figure and the Code:** The prose flowchart references an acknowledged state, but the module explicitly sets TERMINAL = {"filled", "partial", "rejected", "abandoned"} and completely omits intermediate acknowledgments.

**Cut the Word Soup:** Remove the sentence: "Trace the spine: Intent → Authority → Capability → Action → Evidence → Verification → Accountability.". It is pure padding.

**Open question from reviewer:** How do you plan to handle the polling or websocket mechanisms required to transition an order from open to filled?
