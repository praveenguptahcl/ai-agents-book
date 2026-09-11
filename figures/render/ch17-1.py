"""Figure 17.1 -- The deflation diagram (two inks only)."""
import sys
sys.path.insert(0, "/home/hatch/workspace/book-rebuild/figures")
from _style import *
import numpy as np

GRAY = "#6B7280"
BLACK = "#111111"

fig, ax = plt.subplots(figsize=(10, 5.6))

xs = np.linspace(0, 1.4, 500)
mu, sd = 0.57, 0.28
pdf = (1 / (sd * np.sqrt(2 * np.pi))) * np.exp(-0.5 * ((xs - mu) / sd) ** 2)

ax.fill_between(xs, 0, pdf, color=GRAY, alpha=0.18, zorder=1)
ax.plot(xs, pdf, color=GRAY, lw=2.2, zorder=2)

# null mean
ax.axvline(0.57, color=GRAY, lw=1.6, ls=(0, (5, 4)), zorder=2)
ax.text(0.57, 1.52, "SR0 \u2248 0.57\nwhat luck alone expects",
        ha="center", va="top", fontsize=9, color=GRAY)
ax.text(0.20, 0.42,
        "Distribution of the best Sharpe among K=250 trials\n"
        "under the null (no edge anywhere)",
        ha="center", va="center", fontsize=8.5, color=GRAY, style="italic")

# the haircut: leftward arrow from 0.65 to 0.57
ax.annotate("", xy=(0.575, 0.42), xytext=(0.645, 0.42),
            arrowprops=dict(arrowstyle="-|>", color=BLACK, lw=1.8))
ax.text(0.61, 0.50, "the haircut", ha="center", fontsize=8.5,
        style="italic", color=BLACK,
        bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none",
                  alpha=0.9))

# death case marker at 0.65
ax.plot(0.65, 0.03, marker="D", color=BLACK, ms=11, zorder=5,
        clip_on=False)
ax.annotate("Observed 0.65 \u2014 DSR \u2248 0.56:\na coin flip once you "
            "admit the 250 tries",
            xy=(0.65, 0.03), xytext=(0.06, 1.22), fontsize=9, color=BLACK,
            ha="left", va="bottom",
            arrowprops=dict(arrowstyle="-", color=BLACK, lw=1.2,
                            connectionstyle="arc3,rad=0.18"))

# survivor marker at 1.2
ax.plot(1.2, 0.03, marker="D", color=BLACK, ms=11, zorder=5,
        clip_on=False)
ax.annotate("Observed 1.2 over 20y \u2014 DSR \u2248 0.98:\nsurvives, at "
            "the price of twenty years",
            xy=(1.2, 0.03), xytext=(1.39, 0.66), fontsize=9, color=BLACK,
            ha="right", va="bottom",
            arrowprops=dict(arrowstyle="-", color=BLACK, lw=1.2,
                            connectionstyle="arc3,rad=-0.15"))

ax.set_xlim(0, 1.4)
ax.set_ylim(0, 1.72)
ax.set_xticks([0, 0.57, 0.65, 1.2])
ax.set_xticklabels(["0", "0.57", "0.65", "1.2"], family="monospace",
                   fontsize=9)
ax.set_xlabel("Sharpe ratio (annualized)", fontsize=10)
ax.set_yticks([])
for spine in ("top", "right", "left"):
    ax.spines[spine].set_visible(False)
ax.spines["bottom"].set_color(BLACK)

ax.set_title("Figure 17.1 \u2014 The deflation diagram", fontsize=12,
             weight="bold", pad=12)

fig.text(0.5, 0.02,
         "Same observed Sharpe, different verdicts. The DSR does not grade "
         "the number \u2014 it grades the number given how hard you looked.",
         ha="center", fontsize=9, style="italic", color=GRAY,
         bbox=dict(boxstyle="round,pad=0.5", fc="#F4F5F7", ec="none"))

fig.tight_layout(rect=[0, 0.08, 1, 0.96])
fig.savefig("/home/hatch/workspace/book-rebuild/figures/ch17-1.png",
            dpi=200)
fig.savefig("/home/hatch/workspace/book-rebuild/figures/ch17-1.svg")
print("ch17-1 done")
