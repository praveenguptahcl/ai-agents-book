# Figure spec — Chapter 17 (ch17-figspec.md)

## Figure 17.1 — The deflation diagram

**Purpose:** make multiplicity control visual in one glance: the null distribution of the best-of-K Sharpe, the observed Sharpe, and the haircut the DSR applies.

**Layout:** a single horizontal axis labeled "Sharpe ratio (annualized)".

1. **The null curve:** a bell-shaped density centered near 0.57, labeled "Distribution of the best Sharpe among K=250 trials *under the null* (no edge anywhere)". Mark its mean with a vertical dashed line labeled "SR₀ ≈ 0.57 — what luck alone expects".
2. **The death case:** a solid marker at 0.65 labeled "Observed 0.65 — DSR ≈ 0.56: a coin flip once you admit the 250 tries". Draw a leftward arrow from 0.65 back to 0.57 labeled "the haircut".
3. **The survivor:** a second solid marker at 1.2 labeled "Observed 1.2 over 20y — DSR ≈ 0.98: survives, at the price of twenty years".
4. **Annotation:** a caption box: "Same observed Sharpe, different verdicts. The DSR does not grade the number — it grades the number *given how hard you looked*."

**Style notes:** two inks only (null curve in gray, observed markers in black); no 3-D; axis ticks at 0, 0.57, 0.65, 1.2. The figure must reproduce the chapter's hand-worked numbers exactly.

## Figure 17.2 (optional) — The three lies

A three-panel strip: (1) two return histograms with identical Sharpe but opposite skew, labeled "same Sharpe, different risk"; (2) a confidence band widening as the track record shortens, labeled "your Sharpe is a rumor below minTRL"; (3) 250 faint dots (trial Sharpes) with the maximum highlighted, labeled "best of 250 ≈ 0.57 under the null". Only build if layout budget allows; Figure 17.1 is the required one.
