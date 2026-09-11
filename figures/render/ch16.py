"""Figure 16.1 -- Walk-forward embargo windows (Gantt), ~16:9."""
import sys
sys.path.insert(0, "/home/hatch/workspace/book-rebuild/figures")
from _style import *
import numpy as np
import matplotlib.patches as mpatches

rng = np.random.default_rng(42)

fig = plt.figure(figsize=(14, 7.9))
gs = fig.add_gridspec(2, 1, height_ratios=[1.18, 1.0], hspace=0.42)
axA = fig.add_subplot(gs[0])
axB = fig.add_subplot(gs[1], sharex=axA)

BH = 0.55  # bar height


def seg(ax, y, left, width, kind, alpha=1.0, ls="-"):
    """One contiguous window block."""
    if kind == "train":
        ax.barh(y, width, left=left, height=BH, color=COLORS["blue"],
                edgecolor=COLORS["ink"], lw=0.8, alpha=alpha, linestyle=ls)
    elif kind == "embargo":
        ax.barh(y, width, left=left, height=BH, color=COLORS["red_lt"],
                edgecolor=COLORS["red"], lw=1.2, hatch="///",
                alpha=alpha, linestyle=ls)
    elif kind == "test":
        ax.barh(y, width, left=left, height=BH, color=COLORS["green"],
                edgecolor=COLORS["ink"], lw=0.8, alpha=alpha, linestyle=ls)


# ================= Panel A: rolling calendar folds =====================
axA.set_title("A \u2014 Rolling calendar folds (anchor rolls forward)",
              loc="left", fontsize=10, weight="bold", pad=8)

# ghost row: shuffled k-fold (DO NOT DO THIS)
GY = 3.2
_blocks = []
for _ in range(16):
    left = rng.uniform(0, 92)
    w = rng.uniform(3, 9)
    kind = rng.choice(["train", "test"])
    _blocks.append((left, w))
    seg(axA, GY, left, w, kind, alpha=0.30, ls=(0, (3, 2)))
_cx = float(np.mean([l + w / 2 for l, w in _blocks]))
axA.plot([_cx - 8, _cx + 8], [GY - 0.35, GY + 0.35], color=COLORS["red"],
         lw=3.2)
axA.plot([_cx - 8, _cx + 8], [GY + 0.35, GY - 0.35], color=COLORS["red"],
         lw=3.2)
axA.text(104, GY, "time travel", color=COLORS["red"], fontsize=8.5,
         va="center", ha="left", weight="bold")

folds = [(2.2, 0, "fold-00"), (1.2, 10, "fold-01"), (0.2, 20, "fold-02")]
for y, start, _fid in folds:
    seg(axA, y, start, 40, "train")
    seg(axA, y, start + 40, 5, "embargo")
    seg(axA, y, start + 45, 10, "test")

# dashed anchor lines at each fold's train->embargo boundary (the roll)
for x in (40, 50, 60):
    axA.plot([x, x], [-0.2, 2.85], color=COLORS["gray"], lw=1.2,
             ls=(0, (4, 3)))
axA.text(50, 2.60, "anchor roll", fontsize=7, color=COLORS["gray"],
         ha="center", va="bottom", style="italic")

# embargo callout
axA.annotate("embargo absorbs:\nlabel-horizon smear + feature memory\n"
             "\u2014 \u00a716.3",
             xy=(42.5, 2.2), xytext=(86, 2.62), fontsize=7.5,
             ha="left", va="center",
             arrowprops=dict(arrowstyle="-|>", color=COLORS["ink"], lw=1.4),
             bbox=dict(boxstyle="round,pad=0.35", fc="white", ec="none",
                       alpha=0.92))

# leakage icons below fold-02, arrows into its embargo
for bx, label in [(6, "20-bar forward label"), (24, "trailing 30-bar MA")]:
    axA.add_patch(FancyBboxPatch((bx, -0.58), 16, 0.42,
                                 boxstyle="round,pad=0.02",
                                 facecolor="white",
                                 edgecolor=COLORS["ink"], lw=1.1))
    axA.text(bx + 8, -0.37, label, ha="center", va="center", fontsize=7,
             family=MONO)
axA.annotate("", xy=(39.5, 0.02), xytext=(22, -0.30),
             arrowprops=dict(arrowstyle="-|>", color=COLORS["ink"], lw=1.4,
                             connectionstyle="arc3,rad=0.2"))
axA.text(30.5, -0.86, "labels leak forward \u2014 the embargo eats them",
         ha="center", fontsize=7, style="italic", color=COLORS["gray"])
axA.annotate("", xy=(44.6, 0.02), xytext=(40, -0.30),
             arrowprops=dict(arrowstyle="-|>", color=COLORS["ink"], lw=1.4,
                             connectionstyle="arc3,rad=-0.2"))
axA.text(52, -0.86, "features remember \u2014 the embargo waits them out",
         ha="left", fontsize=7, style="italic", color=COLORS["gray"])

axA.set_yticks([3.2, 2.2, 1.2, 0.2])
axA.set_yticklabels(["shuffled k-fold\n(DO NOT DO THIS)", "fold-00",
                     "fold-01", "fold-02"], fontsize=8, family=MONO)
axA.set_ylim(-1.15, 4.05)
axA.set_xlim(0, 122)
axA.tick_params(labelbottom=False)
axA.grid(axis="x", color=COLORS["gray_lt"], lw=0.7)
axA.set_axisbelow(True)

# ================= Panel B: regime-cut fold ============================
axB.set_title("B \u2014 Regime-cut fold", loc="left", fontsize=10,
              weight="bold", pad=8)
axB.axvspan(0, 60, color=COLORS["blue_lt"], alpha=0.45, zorder=0)
axB.axvspan(60, 120, color=COLORS["orange_lt"], alpha=0.45, zorder=0)
axB.text(30, 1.52, "BULL", ha="center", fontsize=9, color=COLORS["gray"],
         weight="bold")
axB.text(90, 1.52, "HIGH-VOL", ha="center", fontsize=9,
         color=COLORS["gray"], weight="bold")

seg(axB, 0.9, 0, 55, "train")
seg(axB, 0.9, 55, 5, "embargo")
seg(axB, 0.9, 60, 60, "test")
axB.text(90, 0.9, "test window never straddles\nthe regime break \u2014 "
                  "\u00a716.6",
         ha="center", va="center", fontsize=7.5, color="white",
         weight="bold")

# ghost row: skipped fold (regime break at bar 4, 5-bar embargo can't fit)
seg(axB, 0.25, 0, 4, "train", alpha=0.25, ls=(0, (3, 2)))
seg(axB, 0.25, 4, 5, "embargo", alpha=0.25, ls=(0, (3, 2)))
seg(axB, 0.25, 9, 10, "test", alpha=0.25, ls=(0, (3, 2)))
axB.plot([4, 4], [-0.05, 1.25], color=COLORS["red"], lw=1.6,
         ls=(0, (4, 3)))
axB.text(5.2, 0.25, "regime break (bar 4)", fontsize=7,
         color=COLORS["red"], va="center", style="italic")
axB.text(24, 0.25, "skipped honestly \u2014 embargo cannot fit",
         fontsize=7.5, color=COLORS["gray"], va="center", style="italic")

axB.set_yticks([0.9, 0.25])
axB.set_yticklabels(["regime-HIGH-VOL-01", "skipped fold"], fontsize=8,
                     family=MONO)
axB.set_ylim(-0.15, 1.72)
axB.set_xlabel("bar index", fontsize=9)
for lab in axB.get_xticklabels():
    lab.set_family("monospace")
axB.grid(axis="x", color=COLORS["gray_lt"], lw=0.7)
axB.set_axisbelow(True)

# ================= legend ==============================================
handles = [
    mpatches.Patch(facecolor=COLORS["blue"], edgecolor=COLORS["ink"],
                   label="train"),
    mpatches.Patch(facecolor=COLORS["red_lt"], edgecolor=COLORS["red"],
                   hatch="///", label="embargo (quarantine)"),
    mpatches.Patch(facecolor=COLORS["green"], edgecolor=COLORS["ink"],
                   label="test"),
    mpatches.Patch(facecolor=COLORS["gray_mid"], edgecolor="none",
                   alpha=0.35, label="skipped"),
]
fig.legend(handles=handles, loc="lower center", ncol=4, fontsize=8,
           frameon=False, bbox_to_anchor=(0.5, 0.0))

fig.suptitle("Figure 16.1 \u2014 Walk-forward embargo windows",
             fontsize=12, weight="bold", y=0.98)

fig.tight_layout(rect=[0, 0.04, 1, 0.94])
fig.savefig("/home/hatch/workspace/book-rebuild/figures/ch16.png", dpi=200)
fig.savefig("/home/hatch/workspace/book-rebuild/figures/ch16.svg")
print("ch16 done")
