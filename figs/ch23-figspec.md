# Figure 23.1 — Lab 4 pipeline (figspec)

## Purpose
Show the capstone composition as a single left-to-right pipeline: the
fixture flows through folds, walk-forward, DSR deflation, thesis writing,
and judging, and lands as a VerdictReport. The diagram must make the
honesty trap visible: the in-sample Sharpe (2.47) enters at the left, and
the FAIL verdict exits at the right.

## Layout
Horizontal pipeline, seven stages, left to right:

1. **Fixture** — box labeled "Q3-2025 replay universe / 600 daily bars,
   SYNTHETIC, seeded (2033)". Sub-note: "in-sample Sharpe 2.47 (seductive)".
2. **Folds** — box labeled "make_calendar_folds / train 120 · embargo 10 ·
   test 90 → 5 folds". Red annotation: "embargo = 0 refused".
3. **Walk-forward** — box labeled "walk_forward / fresh strategy per fold /
   t+1 execution". Below it, five small chips in fold order: PASS, PASS,
   PASS, FAIL, HOLD.
4. **DSR** — box labeled "dsr() vs 25 null trials". Large annotation:
   "0.67 < 0.95 — deflated". A small side box: "in-sample 2.47 → deflated
   0.67" with a downward arrow, captioned "multiplicity control".
5. **Thesis** — document icon labeled "one-paragraph thesis: verdict,
   folds, embargo, DSR". Red annotation: "no 'PASS' unless earned".
6. **Judges** — two judge icons labeled "judge-a / judge-b, frozen
   dataset (hash-pinned)". Annotation: "κ = 1.0 ≥ 0.6; cost 0.024 ≤ 1.00".
7. **VerdictReport** — box labeled "verdict: FAIL / reason: walk-forward +
   DSR reject". Green check annotation: "evidence trail complete".

## Edges
Solid arrows between stages 1→7 in order. A dashed red arrow from stage 1
("2.47 in-sample") directly to stage 7, labeled "the shortcut the lab
forbids", crossed out with a prohibition mark.

## Style
Match the book's figure style (Ch 16 embargo Gantt, Ch 15 judge pipeline).
The crossed-out shortcut arrow is the visual thesis of the chapter: the
honest path is longer than the seductive one.
