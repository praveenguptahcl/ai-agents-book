# Figure Spec — Appendix E: The Nine-Gate Checklist Diagram

**Chapter one-line reference:** The nine certification gates as a single checklist the reader can print — each gate a row with its artifact, chapter anchor, and the evidence-demand rule.

## Figure E-1 — The nine-gate certification wall

**Type:** Checklist / gate diagram. Two-column layout.

**Left column — the gates (top to bottom, numbered 1–9):**
1. Identity — Ch 3, 6
2. Authority — Ch 6, 18
3. Contracts — Ch 4
4. Threat model — Ch 12
5. Eval thresholds — Ch 15
6. Rollback — Ch 11, 14
7. Logging — Ch 9
8. Escalation — Ch 19
9. Incident owner — Ch 14

Each gate row shows: checkbox, gate name, chapter anchor chips, and the artifact demanded (e.g. "authority policy — principals + scopes, default-deny asserted").

**Right column — the verdict panel:**
- Top: `run_standard(evidence)` → `GateReport`
- Middle: the `ships` property as a traffic light: green only when all nine boxes are checked; a single unchecked box turns the whole panel red.
- Bottom: the rendered verdict block, showing one passing gate line (`[x] identity: demonstrated`) and one failing gate line with its remediation (`[ ] authority: MISSING: ...` → "Produce the authority policy...").

**Annotations (callouts):**
- Callout A (on the traffic light): "One unchecked box fails the build. Certification is all-or-nothing by design — a system with eight gates is a system with a hole."
- Callout B (on a failing row): "The remediation names the exact document to write. Red-to-green is a work list, not a feeling."
- Callout C (footer): "A claim is not a demonstration. STANDARD_VERSION 1.0 — re-certify on every bump."

**Caption:** "The Agent Production Standard v1.0 as a certification wall: nine gates, nine artifacts, one verdict. The gate demands evidence, not claims."

**Style notes:** Monospace for code identifiers (`run_standard`, `ships`, `[x]`/`[ ]`); chapter anchors as small chips; the failing row highlighted in the book's warning color; print-friendly (the figure doubles as the wall poster for the production review).
