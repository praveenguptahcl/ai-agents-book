"""Ch3 — System Intent: four planes, one mandate. Four horizontal swim
lanes, a vertical blue intent band on the left with dashed
'declares the boundary' arrows, and a defeated prompt-injection
(hand) from the right stopped with a bold X at the intent band."""
import sys
sys.path.insert(0, "/home/hatch/workspace/book-rebuild/figures")
from _style import *
from matplotlib.patches import FancyBboxPatch

fig, ax = new_fig(10, 6.5)
title(ax, "System Intent: Four Planes, One Mandate", fs=18)

# --- vertical intent band ---
box(ax, 2, 10, 16, 78, "", face="blue", edge="blue")
ax.text(11.5, 49, "System Intent (this chapter)", rotation=90,
        ha="center", va="center", fontsize=13, weight="bold", color="white")
ax.text(6.5, 49, "frozen · hashed mandate", rotation=90,
        ha="center", va="center", fontsize=9.5, color="white", alpha=0.92)

# --- four swim lanes ---
lanes = [("Control plane", 74, 90), ("Execution plane", 56, 72),
         ("Data plane", 38, 54), ("Evaluation plane", 20, 36)]
for name, y0, y1 in lanes:
    box(ax, 20, y0, 56, y1 - y0, "", face="gray_lt", edge="gray_mid", lw=1.0)
    ax.text(74.5, y1 - 1.2, name, ha="right", va="top", fontsize=12,
            weight="bold", color=COLORS["gray"])
    arrow(ax, 18.5, (y0 + y1) / 2, 27, (y0 + y1) / 2,
          color="blue", ls="--", lw=1.5)
ax.text(20.5, 84.6, "declares the boundary", ha="left", va="bottom",
        fontsize=9.5, color=COLORS["blue"])

# --- Control plane ---
box(ax, 36, 78, 20, 9, "AlphaForge signal agent", mono=True, fs=10.5, lw=1.4)
arrow(ax, 56, 82.5, 60, 82.5, lw=1.4)
box(ax, 60, 78, 12, 9, "allowlist +\nuniverse", fs=9.5, lw=1.2)

# --- Execution plane ---
ex = [(28, "tool contracts\n(Ch 4)"), (40, "action executor\n(Ch 10)"),
      (52, "kill switch\n(Ch 11)"), (64, "paper broker")]
for x, t in ex:
    box(ax, x, 59, 11, 9, t, fs=10, lw=1.2)

# --- Data plane ---
box(ax, 28, 41, 24, 9, "market-data feed\nstamped REAL / SYNTHETIC",
    fs=10, lw=1.2)
box(ax, 54, 41, 18, 9, "feature store", fs=10.5, lw=1.2)

# --- Evaluation plane ---
box(ax, 28, 23, 17, 9, "evidence log\nintent_hash (Ch 9)", fs=10, lw=1.2)
box(ax, 47, 23, 14, 9, "walk-forward\nharness", fs=10, lw=1.2)
box(ax, 63, 23, 12, 9, "evaluators\n(Ch 15)", fs=10, lw=1.2)

# --- defeated prompt injection: a hand reaching in from the right ---
box(ax, 79, 57.5, 18, 8, 'prompt paragraph:\n"trade momentum names"',
    face="red_lt", edge="red", fs=9.5, lw=1.6)
# simple hand glyph (palm + pointing finger) at the arrow tail
ax.add_patch(FancyBboxPatch((89, 52.6), 6, 4.8, boxstyle="round,pad=0.01",
                            facecolor=COLORS["red"], edgecolor=COLORS["red"]))
ax.add_patch(FancyBboxPatch((82.5, 54.2), 7, 1.7, boxstyle="round,pad=0.01",
                            facecolor=COLORS["red"], edgecolor=COLORS["red"]))
arrow(ax, 82, 55, 20, 55, color="red", ls="--", lw=2.0)
stop_mark(ax, 18.8, 55, s=3.2)

caption(ax, "A suggestion is not an intent.", fs=12.5)

save(fig, "ch03")
print("ch03 done")
