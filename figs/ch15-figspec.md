# Figure spec — Chapter 15: Evaluators

Chapter one-line reference (in `ch15-evaluators.md`):
*Figure: the eval pipeline — golden set → graders + budgeted judges → agreement stats → CI gate.*

## Figure 15.1 — The eval pipeline (full-page width)

A left-to-right pipeline diagram with five stages and two feedback loops:

1. **Frozen golden set** (leftmost box): a cylinder/database icon labeled
   "FrozenDataset — content-hash pinned". A small lock badge. Annotation:
   "mutation → DatasetTamperedError".
2. **Grading** (second box, split into two lanes):
   - Upper lane: "Deterministic graders (seeded, self-checked)" with three
     small chips: ExactMatch, RealBarsOnly, SchemaConform.
   - Lower lane: "LLM judges (budgeted)" with a wallet icon and the label
     "judge_on: explicit case list". A "$" meter showing cost accumulating
     into a CostLedger box below.
3. **Agreement statistics** (third box): two judge verdicts entering a
   comparator labeled "κ (Cohen)". Two exits: "agree → ScoreResult" and
   "disagree → HumanReviewTicket" (the latter drawn as a ticket stub going
   to a human icon, with a dashed return arrow labeled "verdict re-enters
   as ScoreResult").
4. **Report** (fourth box): "EvalReport — pass rate + Wilson interval +
   cost-per-verified-success". Show the interval as a horizontal bar:
   point estimate 0.92 with whiskers (0.65, 0.99) labeled "n=12" next to a
   tighter bar (0.90, 0.93) labeled "n=1200".
5. **CI gate** (rightmost box, drawn as a gate/turnstile): lists the two
   thresholds — "Wilson lower ≥ 0.90" and "cost/verified ≤ $0.05". Two
   exits: green "merge" and red "blocked" (blocked exit annotated with
   "RegressionError / CostGateExceededError").

Feedback loops (dashed arrows):
- From the gate back to the golden set: "rotate: versioned datasets,
  archived runs" (contamination defense).
- From HumanReviewTicket back to the judge lane: "disagreement patterns →
  rubric review" (the monthly eval review).

Below the pipeline, a thin strip labeled "Chapter 16 consumes this":
"walk_forward imports graders → scores each fold → PSR/DSR (Ch 17)".
This makes the machinery-vs-methodology split visual.

## Figure 15.2 — Kappa vs raw agreement (half-width, optional)

A small 2×2 confusion-style illustration for the hand-worked example:
Judge A rows (pass/pass/pass/fail/fail), Judge B columns. Highlight the
four agreements and the one disagreement. Beside it: "raw agreement 80% →
κ = 8/13 ≈ 0.615". Caption: "Raw agreement flatters; kappa subtracts
chance."

## Rendering notes

- Color semantics (consistent with the book's palette): green = verified /
  passing, red = blocked / refused, amber = human review / pending,
  gray = archived. Disagreement paths are always amber; refusal paths are
  always red.
- The "$" cost meter must visually accumulate left-to-right so the reader
  sees cost as a flow, not a footnote.
- No code in the figure; mechanism names (FrozenDataset, HumanReviewTicket,
  CostLedger) match the chapter text exactly.
