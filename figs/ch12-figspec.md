# FIG 12.1 — Injection Defense Pipeline (layout spec)

Sequence diagram, "Prompt Injection Defense Pipeline."

Six participants arranged left to right: **World (tools/feeds)**,
**Provenance Tagger**, **Planner (LLM)**, **Schema Gate**, **Intent
Reviewer**, **Action Plane**.

Two flows shown.

Top flow (attack path, red):
- World → Tagger: quote containing `SYSTEM OVERRIDE` (solid red arrow,
  labeled "attacker-controlled text")
- Tagger → Planner: prompt with the quote inside an UNTRUSTED DATA banner
  (solid arrow, labeled "quarantined, not cleaned — randomized delimiter
  id, sanitized literals")
- Planner → Schema Gate: `{"action": "liquidate", ...}` (dashed red arrow,
  labeled "model obeyed the injection")
- Schema Gate → Planner: rejection (solid red arrow, labeled
  "✕ STOP — 'liquidate' not in vocabulary; broker never contacted")

Bottom flow (contained path, green):
- World → Tagger: tainted news note (solid arrow)
- Tagger → Planner: bannered prompt (solid arrow)
- Planner → Schema Gate: well-formed `propose_signal short NVDA` (dashed
  green arrow, labeled "injection survived the gate")
- Schema Gate → Reviewer: valid-shaped proposal (solid green arrow)
- Reviewer → Planner: rejection (solid red arrow, labeled
  "✕ STOP — tripwire: 'note to AI assistants' in mcp:market_news; failing
  closed to hold")

A note beneath the Reviewer: "Unicode-smuggled variant: tripwire misses
by design (homoglyphs); the smuggled SHORT dies at the long-only mandate
only by coincidence of sides — a smuggled LONG inside the mandate is the
documented residual (see §12.7)."

A third, unboxed note at the bottom: "Data-plane lie (no imperative):
passes all three layers — fought with independent verification, not
input filters."

Caption beneath: "Three layers, three independent kill conditions. The
attack must defeat all of them; the defense needs only one."

Style: clean technical sequence diagram, monospace labels, red for
attack/reject paths, green for the contained path, generous whitespace
between the two flows.
