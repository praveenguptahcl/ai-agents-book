import sys
sys.path.insert(0, "/home/hatch/workspace/book-rebuild/figures")
from _style import *

fig, ax = new_fig(14, 6)
title(ax, "Figure 23.1 \u2014 Lab 4: The Honest Pipeline", fs=12)

xs = [1.5, 15.5, 29.5, 43.5, 58.5, 73, 86.5]
ws = [12.5, 12.5, 12.5, 13.5, 12, 11.5, 12]
names = ["1. Fixture", "2. Folds", "3. Walk-forward", "4. DSR", "5. Thesis",
         "6. Judges", "7. VerdictReport"]
bodies = [
    "Q3-2025 replay universe\n600 daily bars\nSYNTHETIC, seeded (2033)",
    "make_calendar_folds\ntrain 120 \u00b7 embargo 10\ntest 90 \u2192 5 folds",
    "walk_forward\nfresh strategy per fold\nt+1 execution",
    "dsr()\nvs 25 null trials",
    "one-paragraph thesis:\nverdict, folds,\nembargo, DSR",
    "judge-a / judge-b\nfrozen dataset\n(hash-pinned)",
    "verdict: FAIL\nreason: walk-forward\n+ DSR reject",
]
faces = ["blue_lt", "gray_lt", "gray_lt", "purple_lt", "gray_lt", "gray_lt", "paper"]
edges = ["blue", "ink", "ink", "purple", "ink", "ink", "ink"]
for x, w, n, b, f, e in zip(xs, ws, names, bodies, faces, edges):
    box(ax, x, 46, w, 28, f"{n}\n{b}", face=f, edge=e, fs=7, mono=False,
        lw=2.0 if n.startswith("7.") else 1.4)
    if not n.startswith("7."):
        arrow(ax, x + w, 60, x + w + 1.5, 60, color="ink", lw=1.6)

# stage 1 sub-note: seductive in-sample Sharpe
ax.text(xs[0] + ws[0] / 2, 38, "in-sample Sharpe 2.47\n(seductive)", ha="center",
        va="top", fontsize=7, style="italic", color=COLORS["red"])

# stage 2: embargo = 0 refused
ax.text(xs[1] + ws[1] / 2, 38, "embargo = 0 refused", ha="center", va="top",
        fontsize=7, weight="bold", color=COLORS["red"],
        bbox=dict(boxstyle="round,pad=0.3", fc=COLORS["red_lt"], ec=COLORS["red"]))

# stage 3: five chips PASS PASS PASS FAIL HOLD
chips = [("PASS", "green_lt", "green"), ("PASS", "green_lt", "green"),
         ("PASS", "green_lt", "green"), ("FAIL", "red_lt", "red"),
         ("HOLD", "amber_lt", "amber")]
cx = xs[2]
for i, (lbl, f, e) in enumerate(chips):
    box(ax, cx + i * 2.55, 33, 2.3, 4, lbl, face=f, edge=e, fs=5.5)

# stage 4: DSR annotation
ax.text(xs[3] + ws[3] / 2, 38, "0.67 < 0.95 \u2014 deflated", ha="center",
        va="top", fontsize=8, weight="bold", color=COLORS["purple"])
# side box: in-sample 2.47 -> deflated 0.67
box(ax, xs[3] - 0.5, 18, 14.5, 12,
    "in-sample 2.47\n\u2192 deflated 0.67\nmultiplicity control",
    face="purple_lt", edge="purple", fs=6.5, mono=True)
ax.text(xs[3] + 6.8, 28.5, "\u25bc", ha="center", va="center", fontsize=10,
        color=COLORS["purple"])

# stage 5: no 'PASS' unless earned
ax.text(xs[4] + ws[4] / 2, 38, "no \u2018PASS\u2019 unless earned", ha="center",
        va="top", fontsize=7, weight="bold", color=COLORS["red"])

# stage 6: judges annotation
ax.text(xs[5] + ws[5] / 2, 38, "\u03ba = 1.0 \u2265 0.6\ncost 0.024 \u2264 1.00",
        ha="center", va="top", fontsize=7, family=MONO, color=COLORS["ink"])

# stage 7: green check evidence trail complete
ax.text(xs[6] + ws[6] / 2, 38, "\u2713 evidence trail complete", ha="center",
        va="top", fontsize=7, weight="bold", color=COLORS["green"])

# dashed red shortcut arrow from stage 1 to stage 7 (routed below the stages)
ax.annotate("", xy=(xs[6] + ws[6] / 2, 12), xytext=(xs[0] + ws[0] / 2, 12),
            arrowprops=dict(arrowstyle="-|>", color=COLORS["red"], lw=2,
                            ls=(0, (6, 4)), mutation_scale=14, shrinkA=1, shrinkB=3))
ax.text(50, 15.8, "the shortcut the lab forbids (2.47 in-sample \u2192 verdict)",
        ha="center", va="center", fontsize=7.5, style="italic",
        color=COLORS["red"],
        bbox=dict(boxstyle="round,pad=0.3", fc=COLORS["red_lt"], ec="none"))
stop_mark(ax, 50, 12, s=2.4, color="red")

save(fig, "ch23")
print("ch23 ok")
