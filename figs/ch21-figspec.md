# Figure 21.1 — FigSpec: The Signal Validation Pipeline

**Chapter:** 21 (Lab 2) · **Type:** vertical flowchart, four stages + terminal
states · **Style:** engineering schematic, monospace labels, no clip art.

## Layout

Top to bottom, single column, five boxes. Each stage box is split: left half
names the stage, right half names what it checks. Downward arrows between
stages. From each stage, a rightward arrow exits to a shared "REJECTED"
column on the right, labeled with that stage's reason code.

```
┌─────────────────────────────────┐
│ 1. PARSE                        │
│    raw string → JSON            │─── MALFORMED_JSON ──→ ┐
└─────────────────────────────────┘                      │
┌─────────────────────────────────┐                      │
│ 2. SCHEMA-CHECK                 │                      │
│    shape: required, types, enum  │─── SCHEMA_VIOLATION ─→│  REJECTED
└─────────────────────────────────┘                      │  (named reason,
┌─────────────────────────────────┐                      │   closed set)
│ 3. CONTRACT-GATE                │                      │
│    judgment: ranges, allowlist, │─── CONTRACT_VIOLATION→│
│    notional cap                 │                      │
└─────────────────────────────────┘                      │
┌─────────────────────────────────┐                      │
│ 4. DEDUPE                       │                      │
│    proposal_id seen before?     │─── DUPLICATE_ID ────→ ┘
└─────────────────────────────────┘
            │
            ▼
      ┌───────────┐
      │ ACCEPTED  │  → to the executor (Lab 3)
      └───────────┘
```

## Annotations (small callouts, not boxes)

- Between stages 2 and 3, a bracket labeled **"the layer split"**: stage 2
  cannot express ranges (strict mode); stage 3 cannot express nothing the
  provider already guaranteed. Neither layer trusts the other.
- On the `absurd_size` path through stage 3, a callout: "10,000,000 × $590
  — perfectly shaped, semantically absurd. Only the contract knows."
- On the dedupe stage, a callout: "retry or replay — accepted exactly once."
- The REJECTED column footer: "Every refusal has a name. A rejection
  without a name is a shrug."

## Caption

**Figure 21.1.** The four-stage signal validation pipeline. Each stage
refuses in its own vocabulary — parse, shape, judgment, dedupe — and every
refusal carries a closed-set reason code so the 2 a.m. log names the layer
that did its job.

## Cross-references

- Ch 5 (strict provider schema — stage 2's data), Ch 4 (Pydantic contract —
  stage 3's code), Ch 2 (the absurd-but-valid lesson), Lab 3 / Ch 22 (the
  executor that receives only ACCEPTED proposals).
