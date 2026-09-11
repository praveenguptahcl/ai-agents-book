# Figure 14.1 — The Operating Pipeline (FIG-spec)

## Purpose
Show the full production topology of the evidence pipeline in operation:
the agent loop emitting through the backpressure-aware writer, the router
fanning out to the three Ch 9 sinks, the model gateway sitting beside the
provider calls, and the durability substrate (leases, heartbeats,
checkpoints) under the long-running workers.

## Layout (left → right, three lanes)

### Lane 1 — The agent loop (left)
- Box: "Agent loop (ODAV)" with the four stages as small stacked chips:
  Observe → Decide → Act → Verify.
- A thin arrow labeled `submit(session, event, payload)` (non-blocking)
  from the loop down into Lane 2's writer.

### Lane 2 — The evidence path (center, the spine)
- Box: "TraceWriter — bounded queue (10k), single consumer, seq under lock".
  - In-annotation: "queue full → agent PAUSES (backpressure), never drops".
  - In-annotation: "consumer dead → EvidenceWriterDown (loud), never silent".
- Arrow from the writer to a box: "EvidenceRouter.emit() (Ch 9 — the single
  choke point)".
- From the router, a fan-out to three sink boxes:
  - "Audit log — HMAC-chained, everything, forever" (with a small anchor
    icon labeled "WORM checkpoint anchor").
  - "Trace sink — ring buffer, last hour, full fidelity".
  - "Eval dataset — frozen snapshots for the judge (Ch 15)".
- A return arrow from the audit log back left labeled
  "resume-from-ledger (durable runs read here)".

### Lane 3 — The model gateway (right, beside the provider calls)
- Box: "ModelGateway" with four stacked sub-boxes:
  "route(task → model)", "fallback chain", "cache (keyed by intent hash)",
  "cost ledger ($/verified call)".
- Arrow from the agent loop's Decide chip into the gateway labeled
  "complete(task_class, request)".
- Arrow from the gateway to a cloud box "Providers (primary → fallback)".
- A dashed arrow from the gateway ledger down to a small box: "SLO
  dashboard — evidence lag, cost/verified signal, κ".

### Underlay — Durability substrate (bottom, spanning all lanes)
- A wide, low box spanning the figure: "Durable runs".
- Inside, left to right: "Lease (monotonic TTL)" → "heartbeat renews" →
  "fence: stale token writes REJECTED" → "checkpoint(state, audit seq)" →
  "replacement replays evidence, not actions".
- A small "3:07am" clock icon at the lease box and a "3:08am" icon at the
  replacement arrow, marking the worked failover.

## Styling notes
- The spine (Lane 2) is the visual backbone: heavier borders, centered.
- Failure paths (backpressure pause, loud writer death, fence rejection)
  in a contrasting accent color with "never silent" callouts.
- No vendor logos; provider box is generic. All monetary figures are
  desk-example numbers, labeled as such.
