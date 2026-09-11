# FIG spec — Ch 3: Reference Architecture (trading edition)

**Title:** "System Intent: Four Planes, One Mandate"

**Layout:** Four horizontal swim lanes, top to bottom: **Control plane**,
**Execution plane**, **Data plane**, **Evaluation plane**. A vertical band on
the left, spanning all four lanes, labeled **"System Intent (this chapter)"**
— the frozen, hashed mandate. A dashed arrow from the intent band into each
lane, labeled "declares the boundary."

- **Control plane:** planner/orchestrator box ("AlphaForge signal agent").
  Receives the mandate's strategy allowlist and universe; emits intentions.
- **Execution plane:** tool contracts (Ch 4), action executor (Ch 10),
  kill switch (Ch 11), paper broker. Receives risk limits, t+1 rule,
  paper-only endpoint from the mandate.
- **Data plane:** market-data feed stamped REAL/SYNTHETIC per
  `data_mode`; feature store; the provenance declaration flows from intent.
- **Evaluation plane:** evidence log carrying the `intent_hash` on every
  entry (Ch 9); walk-forward harness; evaluators (Ch 15).

**Attack defeated (red dashed):** a hand reaching in from the right labeled
"prompt paragraph: 'trade momentum names'" — stopped at the intent band
with a bold ✕, caption: "A suggestion is not an intent."

**Caption:** "The mandate is declared once, validated fail-closed, frozen,
and hashed. Every plane reads its boundary from the same intent."

**Style:** clean technical architecture diagram; blue for the intent band,
neutral grays for planes, red for the defeated suggestion; monospace labels.
