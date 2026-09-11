# Figure 20.1 — Figspec: The Morning Pipeline

**Placement:** Chapter 20 (Lab 1), after the "What the lab proves" section.

**Type:** Horizontal data-flow diagram with an adversarial overlay. Five
lanes left to right; the validation gate is the visual center of mass.

**Elements (left to right):**

1. **Lane 1 — MCP quote server (Ch 7).** A server box labeled
   `alphaforge-market-data`, with the `get_quote` tool card beneath it.
   An arrow leaves it labeled "JSON-RPC `tools/call` → quote dict".
   The quote is annotated: every field present, `provenance: SYNTHETIC`
   stamped in green. Caption note: "the real wire always arrives
   labeled".

2. **Lane 2 — The student's pipeline (the lab).** A vertical stack of
   five chevrons labeled FETCH → VALIDATE → LABEL → ROUTE →
   ACKNOWLEDGE. VALIDATE is drawn larger, as a gatehouse: four red
   adversarial arrows strike it from below and are stopped or diverted:
   - "no provenance" → STOP sign, labeled `UnlabeledData` —
     "inadmissible, never emitted"
   - "stale quote" → diverted upward with a yellow flag, labeled
     `"stale": True` — "flagged, not dropped"
   - "untrusted source" → STOP sign, labeled `UntrustedSource`
   - "scrambled arrival (3,1,2)" → reordered to (1,2,3), labeled
     "evidence keeps seq order"
   A small green arrow passes through the gate labeled "valid quote →
   `tool_call` payload".

3. **Lane 3 — Evidence spine (Ch 9).** A vertical stack of chained
   blocks (each block shows `seq`, `entry_hash`, and a link arrow to
   the previous block's hash). The top block is highlighted: the
   acknowledgement — "the receipt: `seq` + `entry_hash`".

4. **Lane 4 — Downstream signals.** A signal-agent box with an arrow
   *from* the evidence spine (never from the server directly). The
   arrow is labeled "signals read only validated evidence". A second,
   crossed-out arrow runs directly from Lane 1 to Lane 4, labeled
   "the canonical failure: a signal that read unlabeled data" with a
   red prohibition mark.

5. **Lane 5 (margin note) — The guarantee.** A callout box: "Every
   entry in this log survived validation — the only way in was through
   the pipeline." Beneath it, the Ch 9 chain-verification checkmark:
   `router.verify() → clean`.

**Style:** Clean technical-diagram style, monospace labels for code
identifiers (`UnlabeledData`, `tool_call`, `seq`), green for the valid
path, red for refusals, yellow for the stale flag. No characters, no
photography, no decorative elements. Aspect ratio ~16:9. Must remain
legible at 5 inches wide in print: minimum 9pt equivalent for labels.
