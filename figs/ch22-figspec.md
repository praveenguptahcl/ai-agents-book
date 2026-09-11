# Figure specification — Chapter 22 (Lab 3: Execution Under Fire)

## Figure 22.1 — The crash timeline

**Type:** horizontal timeline with four swim lanes: Market, Broker, Kill switch, Ledger.

**Time axis (left to right):** 14:32 → 15:35, marked at phase boundaries.

**Lane 1 — Market (minute bars, synthetic):**
- A declining price line from 100.0 to ~93.4 over 60 bars.
- A horizontal dashed threshold line at 95.0 labeled "−5% trip".
- A vertical marker at the bar where the line first crosses the threshold,
  labeled "trip bar (~bar 46): scoped PAUSE_INTENTS engages for desk A".
- A second, steeper decline segment labeled "second wave (during halt)".

**Lane 2 — Broker (four phase bands):**
- `normal` (green): "fills immediately".
- `rejecting` (amber): "answers, but rejected — risk: market-wide halt".
- `silent` (red): "submits time out · lookups fail · OUTCOME-UNKNOWN".
- `recovered` (green): "broker truth readable again".

**Lane 3 — Kill switch:**
- Idle until the trip bar, then a solid block labeled
  "PAUSE_INTENTS, scope=(tenant, desk-a)" extending through the halt.
- A second marker: "FULL_STOP drill (tests 7–8): two-admin engage → single-admin
  lift refused → two-admin lift".
- Desk B's row (thin, below): uninterrupted "trading" shading throughout.

**Lane 4 — Ledger (row states over time):**
- Three rows submitted pre-crash: `submitted → filled`.
- One row in the rejecting phase: `submitted → rejected`.
- One row in the silent phase: `submitted → timeout (reconcile_error recorded)
  → abandoned` only after the recovered-phase sweep finds no broker record
  past the settle window.
- Annotation: "no row ever claims filled without broker truth".

**Caption:** "Lab 3's bad afternoon: the broker's four phases, the 5% trip,
the silent window where the only honest answer is unknown, and the
reconcile sweep that closes every row against broker truth."

**Render notes:** monochrome-safe; phase bands use patterns (solid / hatch /
cross-hatch) in addition to color; all text ≥ 9pt at print size.
