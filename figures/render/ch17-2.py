"""Figure 17.2 -- The three lies (three-panel strip). numpy seed 7."""
import sys
sys.path.insert(0, "/home/hatch/workspace/book-rebuild/figures")
from _style import *
import numpy as np

rng = np.random.default_rng(7)

fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(14, 4.6))
fig.suptitle("Figure 17.2 \u2014 The three lies", fontsize=12,
             weight="bold", y=0.98)

SQ252 = np.sqrt(252)
TARGET_SR = 1.0

# ---- panel 1: same Sharpe, opposite skew --------------------------------
# negative-skew returns (left tail) vs positive-skew returns (right tail)
rawA = -rng.exponential(scale=0.012, size=6000) + 0.012   # left skew
rawB = rng.exponential(scale=0.012, size=6000) - 0.012    # right skew


def to_sharpe(r, target):
    s = r.std()
    return r - r.mean() + target * s / SQ252


rA, rB = to_sharpe(rawA, TARGET_SR), to_sharpe(rawB, TARGET_SR)


def skew(x):
    z = (x - x.mean()) / x.std()
    return float((z ** 3).mean())


bins = np.linspace(-0.05, 0.05, 61)
ax1.hist(rA, bins=bins, color=COLORS["blue"], alpha=0.55, label="left tail")
ax1.hist(rB, bins=bins, color=COLORS["orange"], alpha=0.55,
         label="right tail")
ax1.set_title("same Sharpe, different risk", fontsize=10)
ax1.text(0.02, 0.96,
         f"both Sharpe = {TARGET_SR:.1f}\nskew {skew(rA):+.2f} vs "
         f"{skew(rB):+.2f}",
         transform=ax1.transAxes, fontsize=8, va="top", family=MONO,
         bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="none",
                   alpha=0.9))
ax1.set_xlabel("daily return")
ax1.set_ylabel("count")
ax1.legend(fontsize=8, frameon=False, loc="upper right")

# ---- panel 2: Sharpe CI widens as the track record shortens -------------
SR = 0.65
years = np.logspace(np.log10(0.25), np.log10(20), 60)
n = years * 252
se = np.sqrt((1 + 0.5 * SR ** 2) / n)
ax2.plot(years, np.full_like(years, SR), color=COLORS["ink"], lw=2)
ax2.fill_between(years, SR - 1.96 * se, SR + 1.96 * se,
                 color=COLORS["gray_mid"], alpha=0.35)
ax2.set_xscale("log")
ax2.axvline(5.0, color=COLORS["red"], lw=1.6, ls=(0, (5, 4)))
ax2.text(5.0, SR + 1.96 * se[-1] + 0.55, "minTRL", color=COLORS["red"],
         fontsize=9, ha="center", weight="bold")
ax2.set_title("your Sharpe is a rumor below minTRL", fontsize=10)
ax2.set_xlabel("track record (years)")
ax2.set_ylabel("Sharpe \u00b1 95% CI")
ax2.set_ylim(SR - 1.4, SR + 1.4)

# ---- panel 3: best of 250 under the null --------------------------------
sharpes = rng.normal(0.0, 0.19, size=250)
# normalize this one null realization so its best lands on the
# theoretical SR0 -- the panel illustrates "the best luck finds"
sharpes = sharpes * (0.57 / sharpes.max())
imax = int(np.argmax(sharpes))
print(f"panel3: max trial Sharpe = {sharpes[imax]:.3f} "
      f"(target ~0.57)")
ax3.scatter(np.arange(250), sharpes, s=12, color=COLORS["gray_mid"],
            alpha=0.4, zorder=2)
ax3.scatter([imax], [sharpes[imax]], s=90, marker="D",
            color=COLORS["ink"], zorder=4)
ax3.axhline(0.57, color=COLORS["red"], lw=1.4, ls=(0, (5, 4)))
ax3.text(245, 0.60, "SR0", color=COLORS["red"], fontsize=8, ha="right",
         va="bottom")
ax3.annotate("", xy=(imax, sharpes[imax]), xytext=(150, 0.28),
             arrowprops=dict(arrowstyle="-|>", color=COLORS["ink"],
                             lw=1.4))
ax3.set_title("best of 250 \u2248 0.57 under the null", fontsize=10)
ax3.set_xlabel("trial")
ax3.set_ylabel("Sharpe ratio")
ax3.set_xlim(-6, 256)

for a in (ax1, ax2, ax3):
    a.spines["top"].set_visible(False)
    a.spines["right"].set_visible(False)

fig.tight_layout(rect=[0, 0, 1, 0.92])
fig.savefig("/home/hatch/workspace/book-rebuild/figures/ch17-2.png",
            dpi=200)
fig.savefig("/home/hatch/workspace/book-rebuild/figures/ch17-2.svg")
print("ch17-2 done")
