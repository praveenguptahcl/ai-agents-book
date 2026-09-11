# FIG 9.1 — The Evidence Routing Pipeline (visual spec)

Title: "The Evidence Routing Pipeline."

## Layout

- **Sources (left):** strategy → intent_record; authority layer → authority_check; tool boundary → tool_call; broker adapter → broker_response; reconcile sweep → reconcile_event; provider client → refusal; circuit breaker → kill_switch. Each source emits through the router's emit() — no source writes any sink directly. A red "✕" marks the forbidden path: no arrow from any source to any sink except through the router.
- **Router (center):** a gate labeled "emit(session, type, payload) — taxonomy check; tenant from session, never from string." Unknown types → audit log flagged (fail closed, never dropped); known types fan out per the routing table.
- **Sinks (right):** three boxes.
  - **AuditLog** — append-only, HMAC-chained, infinite retention, tenant-scoped reads (absence convention); dual clocks (ts + mono); checkpoint() head hash → WORM anchor.
  - **TraceSink** — ring buffer, TRACE_TYPES only, short retention.
  - **EvalDataset** — EVAL_TYPES only, frozen deepcopy snapshots, versioned with model checkpoints.
- **Verification loop (bottom):** verify_chain() runs on rotation, export, and post-incident; reports first broken seq. A separate dashed arrow: checkpoint() → WORM storage → truncation detection on mismatch.

## Invariants (caption or sidebar)

1. Every event lands in the audit log — unknown types flagged, never dropped.
2. The agent holds emit() and nothing else — no public write path on the audit log.
3. MACs commit to tenant id, event type, both clocks, and payload — not just payload.
4. Tenant reads return absence, never cross-tenant data and never existence-revealing errors.
5. The trace forgets by design, the audit log never does.
6. Truncation is invisible to the chain; the WORM anchor is what catches it.

## Style

Clean technical pipeline diagram: left-to-right flow, three sink boxes in muted blue, the router gate in bold outline, red for the forbidden direct-write path, a dashed line for the WORM anchor loop. Monospace labels for event types and method names.
