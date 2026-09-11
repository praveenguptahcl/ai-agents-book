# Figure spec — Chapter 8: Multi-Agent Systems

## Figure 8.1 — Orchestration topology and delegation scope

**Type:** two-panel diagram (topology left, scope attenuation right).

**Left panel — "Three topologies":**
- (a) Supervisor: one central node "Supervisor" with directed edges to three
  worker nodes (Research, Risk, Settle); all return edges come back to the
  supervisor. Label: "authority centralized; every delegation an explicit grant."
- (b) Hierarchical: Supervisor → two mid-level nodes → leaves. Label:
  "intent degrades per hop; depth limits mandatory."
- (c) Peer/market: three nodes with bidirectional edges, no center. Label:
  "'who said so?' needs a constitution; cycles are the normal case."
- A red dashed cycle A → B → A on panel (c) with the annotation
  "CycleDetected names every hop."

**Right panel — "Attenuation down the chain":**
- Three nested boxes, outermost to innermost: "Orchestrator authority
  {market.read, orders.propose, risk.veto}" → "Delegation grant {market.read}"
  → "Sub-delegation grant {market.read}". Each inner box strictly inside the
  outer; the region between boxes shaded and labeled "refused, never silently
  narrowed."
- A red arrow attempting to go outward from the inner box labeled
  "ScopeDenied."
- Below: a timeline strip for one delegation: OPEN → (ok | failed | open |
  quarantined), with the timeout branch looping back via "reconcile()."

**Caption (for the chapter):** "Authority attenuates down the delegation
chain and never widens; every delegation starts open and only verified
evidence closes it."

**Render notes:** monochrome-friendly; use distinct hatch patterns for the
three topologies; the nested-box panel must make strict-subset visually
obvious (no touching borders).
