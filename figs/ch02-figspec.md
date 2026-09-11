# FIG spec — Chapter 2: The ODAV Loop

**Placement:** after the "The loop, stated plainly" section, one-line reference in chapter text:
`FIG: The ODAV loop — Observe → Decide → Act → Verify, with the authority gate and evidence taps.`

## Visual description

A circular flow diagram: four large nodes arranged in a ring, clockwise from top.

- **Top node — OBSERVE.** Icon: an eye or a radar sweep. Sublabel: "Gather state, with provenance & age." Incoming arrow from outside the ring labeled "world (quotes, inbox, positions)".
- **Right node — DECIDE.** Icon: a document/proposal. Sublabel: "Propose an intention — never an order." Small badge: "LLM lives here (non-deterministic)".
- **Bottom node — ACT.** Icon: a narrow doorway/gate. Sublabel: "External effect through the guarded boundary." The node itself is drawn as a gate/doorway to emphasize narrowness. Badge: "the only stage that changes the world".
- **Left node — VERIFY.** Icon: a magnifier over a checklist, or a scoreboard. Sublabel: "Read the world back. The loop is not closed until verification lands."

Arrows between nodes are thick and clockwise. Two special annotations:

1. **The authority gate:** on the arrow from DECIDE to ACT, a gatehouse icon labeled "AUTHORITY — verified at action time, not decision time."
2. **Evidence taps:** from each of the four nodes, a thin downward arrow into a horizontal "audit trail" bar beneath the ring, labeled "every stage emits evidence."

A fifth, dashed element: from VERIFY, a feedback arrow curving back up to OBSERVE labeled "verified state becomes the next observation."

A contrasting inset, smaller and in muted red: "Open loop (not a loop): OBSERVE → DECIDE → ACT, no VERIFY — commands issued, world assumed obedient. Works in demos; fails in production."

## Style

Clean technical diagram. Four stage colors: blue (observe), amber (decide), red (act — the dangerous one), green (verify). Monospace labels for stage names. The red inset uses a muted/dashed style to read as "the wrong way." Caption beneath: "Four stages, one gate, zero trust in the middle. Verification is what makes it a loop."
