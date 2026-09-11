"""Figure 15.2 -- Kappa vs raw agreement (6x4, half-width)."""
import sys
sys.path.insert(0, "/home/hatch/workspace/book-rebuild/figures")
from _style import *

fig, ax = new_fig(6, 4)
title(ax, "Figure 15.2 \u2014 Kappa vs raw agreement", fs=11)

# ---- 2x2 confusion grid: Judge A rows x Judge B columns --------------
# counts: PP=2, PF=1, FP=0, FF=2  ->  p_o = 0.80, p_e = 0.48,
# kappa = (0.80-0.48)/(1-0.48) = 8/13 ~= 0.615
gx, gy, cw, chh = 9, 30, 13, 13
cells = {(0, 0): (2, "green_lt"), (0, 1): (1, "amber_lt"),
         (1, 0): (0, "paper"),   (1, 1): (2, "green_lt")}
for (i, j), (n, face) in cells.items():
    x = gx + j * cw
    y = gy + (1 - i) * chh
    box(ax, x, y, cw, chh, str(n), face=face, edge="ink", fs=16, lw=1.6)

# column headers (Judge B)
ax.text(gx + cw, gy + 2 * chh + 5.5, "Judge B", ha="center", fontsize=8,
        weight="bold")
ax.text(gx + cw / 2, gy + 2 * chh + 1.5, "pass", ha="center", fontsize=7)
ax.text(gx + 3 * cw / 2, gy + 2 * chh + 1.5, "fail", ha="center", fontsize=7)
# row headers (Judge A)
ax.text(gx - 4.4, gy + chh, "Judge A", ha="center", va="center",
        fontsize=8, weight="bold", rotation=90)
ax.text(gx - 1.0, gy + 3 * chh / 2, "pass", ha="right", va="center",
        fontsize=7)
ax.text(gx - 1.0, gy + chh / 2, "fail", ha="right", va="center",
        fontsize=7)

ax.text(gx + cw, 22.5, "4 agreements \u00b7 1 disagreement", ha="center",
        fontsize=7, color=COLORS["gray"])

# ---- the punchline -----------------------------------------------------
ax.text(74, 60, "raw agreement 80% \u2192", ha="center", fontsize=10)
ax.text(74, 51, "\u03ba = 8/13 \u2248 0.615", ha="center", fontsize=13,
        weight="bold")
ax.text(74, 43, "chance agreement  pe = 12/25 = 0.48",
        ha="center", fontsize=7.5, color=COLORS["gray"])
ax.text(74, 34, "agreements on the diagonal;\nthe one off-diagonal miss\nis all chance leaves behind",
        ha="center", fontsize=7, color=COLORS["gray"])

caption(ax, "Raw agreement flatters; kappa subtracts chance.")

save(fig, "ch15-2")
print("ch15-2 done")
