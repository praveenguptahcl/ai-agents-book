# Figure 16.1 — Walk-forward embargo windows (Gantt)

**Chapter reference (one line):** Rolling anchored folds — train → embargo → test — with the regime-cut variant and the leakage paths the embargo absorbs.

## Purpose

Make the protocol's geometry visible at a glance: where each fold trains, where the quarantine sits, where it is tested, and how the anchor rolls. A reader who absorbs this figure understands why shuffling is time travel (§16.2) and what the embargo is absorbing (§16.3).

## Layout

Two panels, stacked vertically, sharing one horizontal time axis (bar index, 0–120).

### Panel A — Rolling calendar folds (3 folds)

- Each fold is one horizontal row: three contiguous blocks —
  **TRAIN** (solid blue, 40 bars), **EMBARGO** (hatched red, 5 bars), **TEST** (solid green, 10 bars).
- Fold 0: bars 0–40 / 40–45 / 45–55. Fold 1: bars 10–50 / 50–55 / 55–65. Fold 2: bars 20–60 / 60–65 / 65–75.
- Dashed vertical "anchor" lines at each fold's train/test boundary show the roll.
- Callouts on the embargo block: "absorbs label-horizon smear + feature memory — §16.3".
- A struck-through ghost row at top labeled "shuffled k-fold (DO NOT DO THIS)": randomly colored blocks scattered across the axis, with a red ✗ and the caption "time travel".

### Panel B — Regime-cut fold (1 fold)

- Background shading marks regimes: light blue "BULL" (bars 0–60), light orange "HIGH-VOL" (bars 60–120).
- One fold row: TRAIN (bars 0–55, blue), EMBARGO (55–60, hatched red, straddling the regime boundary), TEST (60–120, green, entirely inside HIGH-VOL).
- Callout: "test window never straddles the regime break — §16.6".
- A second ghost row shows the skipped fold: a regime break at bar 4 with a 5-bar embargo requirement, rendered faded with the label "skipped honestly — embargo cannot fit".

## Annotations

- Arrow from a "20-bar forward label" icon in the train region pointing right into the embargo: "labels leak forward — the embargo eats them".
- Arrow from a "trailing 30-bar MA" icon similarly into the embargo: "features remember — the embargo waits them out".
- Legend: blue = train, hatched red = embargo (quarantine), green = test, faded = skipped.

## Style notes

- Flat, print-friendly palette; no gradients. Hatching (not color alone) distinguishes the embargo for grayscale printing.
- Monospace labels for bar indices; the fold IDs (`fold-00`, `regime-HIGH-VOL-01`) match the code's naming exactly.
- Aspect ratio ~16:9; minimum readable at 5 inches wide.
