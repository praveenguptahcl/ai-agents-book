"""Figure 15.1 -- The eval pipeline (14x6, full-page width)."""
import sys
sys.path.insert(0, "/home/hatch/workspace/book-rebuild/figures")
from _style import *
from matplotlib.patches import Ellipse, Rectangle, Arc, Polygon


def cylinder(ax, cx, y0, w, h, face="blue_lt", edge="blue"):
    eh = h * 0.30
    ax.add_patch(Ellipse((cx, y0), w, eh, facecolor=COLORS[face],
                         edgecolor=COLORS[edge], lw=1.4, zorder=2))
    ax.add_patch(Rectangle((cx - w / 2, y0), w, h, facecolor=COLORS[face],
                           edgecolor=COLORS[edge], lw=1.4, zorder=3))
    # side seams redrawn over the bottom ellipse's top half is automatic;
    # top rim (lighter)
    ax.add_patch(Ellipse((cx, y0 + h), w, eh, facecolor="#F2F7FE",
                         edgecolor=COLORS[edge], lw=1.4, zorder=4))


def padlock(ax, cx, cy, s=1.0, color="amber"):
    ax.add_patch(Circle((cx, cy), 2.1 * s, facecolor="white",
                        edgecolor=COLORS["ink"], lw=1.2, zorder=6))
    ax.add_patch(Arc((cx, cy + 0.9 * s), 1.9 * s, 1.9 * s, theta1=0,
                     theta2=180, edgecolor=COLORS["ink"], lw=1.6, zorder=7))
    ax.add_patch(FancyBboxPatch((cx - 1.15 * s, cy - 1.15 * s), 2.3 * s,
                                2.0 * s, boxstyle="round,pad=0.02",
                                facecolor=COLORS[color],
                                edgecolor=COLORS["ink"], lw=1.2, zorder=7))
    ax.add_patch(Circle((cx, cy - 0.35 * s), 0.32 * s, facecolor="white",
                        edgecolor="none", zorder=8))


def wallet(ax, x, y, w, h):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02",
                                facecolor=COLORS["amber"],
                                edgecolor=COLORS["ink"], lw=1.3))
    ax.plot([x, x + w], [y + h * 0.62, y + h * 0.62],
            color=COLORS["ink"], lw=1.2)
    ax.add_patch(Rectangle((x + w * 0.68, y + h * 0.30), w * 0.22, h * 0.22,
                           facecolor=COLORS["ink"], edgecolor="none"))


def ticket_stub(ax, x, y, w, h, text, fs=6):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.015",
                                facecolor=COLORS["amber_lt"],
                                edgecolor=COLORS["amber"], lw=1.4,
                                linestyle=(0, (4, 3))))
    for px in (x, x + w):
        ax.add_patch(Circle((px, y + h / 2), 0.9, facecolor="white",
                            edgecolor=COLORS["amber"], lw=1.2, zorder=5))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
            fontsize=fs, family=MONO, color=COLORS["ink"])


def human_icon(ax, cx, cy, s=1.0):
    ax.add_patch(Circle((cx, cy + 1.7 * s), 1.6 * s,
                        facecolor=COLORS["gray_mid"],
                        edgecolor=COLORS["ink"], lw=1.2))
    ax.add_patch(Polygon([(cx - 2.6 * s, cy - 1.6 * s),
                          (cx + 2.6 * s, cy - 1.6 * s),
                          (cx + 1.6 * s, cy + 0.6 * s),
                          (cx - 1.6 * s, cy + 0.6 * s)],
                         closed=True, facecolor=COLORS["gray_mid"],
                         edgecolor=COLORS["ink"], lw=1.2))


def turnstile(ax, cx, cy):
    ax.plot([cx, cx], [cy - 5.5, cy + 4.5], color=COLORS["ink"], lw=2.2)
    import math
    for deg in (90, 210, 330):
        r = math.radians(deg)
        ax.plot([cx, cx + 3.2 * math.cos(r)], [cy, cy + 3.2 * math.sin(r)],
                color=COLORS["ink"], lw=2.0)
    ax.add_patch(Circle((cx, cy), 0.7, facecolor=COLORS["ink"],
                        edgecolor="none"))


fig, ax = new_fig(14, 6)
title(ax, "Figure 15.1 \u2014 The eval pipeline")

# ---- outer stage bands -------------------------------------------------
for x0, x1 in [(1.5, 17), (19, 37), (39, 57), (59, 75), (77, 95)]:
    ax.add_patch(FancyBboxPatch((x0, 32), x1 - x0, 48,
                                boxstyle="round,pad=0.015",
                                facecolor=COLORS["gray_lt"],
                                edgecolor=COLORS["gray_mid"], lw=0.9,
                                alpha=0.55))

# ---- Stage 1: frozen golden set ---------------------------------------
cylinder(ax, 9, 56, 9.5, 13)
padlock(ax, 12.8, 68.2, s=0.95)
ax.text(9, 51.6, "FrozenDataset", ha="center", fontsize=7.5, family=MONO)
ax.text(9, 48.2, "content-hash pinned", ha="center", fontsize=6.5,
        color=COLORS["gray"])
ax.text(9, 44.6, "mutation \u2192", ha="center", fontsize=6.5)
ax.text(9, 41.6, "DatasetTamperedError", ha="center", fontsize=6,
        family=MONO, color=COLORS["red"])

# ---- Stage 2: grading --------------------------------------------------
# upper lane: deterministic graders
box(ax, 20.5, 63, 15, 14, "", face="paper", edge="ink", fs=6)
ax.text(28, 73.8, "Deterministic graders", ha="center", fontsize=7,
        weight="bold")
ax.text(28, 70.6, "(seeded, self-checked)", ha="center", fontsize=6,
        color=COLORS["gray"])
for i, name in enumerate(["ExactMatch", "RealBarsOnly", "SchemaConform"]):
    box(ax, 21 + i * 4.9, 64, 4.5, 4.6, name, face="blue_lt", edge="blue",
        fs=5.2, mono=True)
# lower lane: LLM judges
box(ax, 20.5, 46, 15, 14, "", face="paper", edge="ink", fs=6)
wallet(ax, 22, 50.2, 4.6, 4.2)
ax.text(30.4, 56.6, "LLM judges (budgeted)", ha="center", fontsize=7,
        weight="bold")
ax.text(30.4, 53.2, "judge_on:", ha="center", fontsize=6, family=MONO)
ax.text(30.4, 50.2, "explicit case list", ha="center", fontsize=6,
        color=COLORS["gray"])
# $ cost meter accumulating left -> right
mx0, mw, my, mh = 20.5, 15, 40.5, 3.4
ax.add_patch(Rectangle((mx0, my), mw, mh, facecolor="none",
                       edgecolor=COLORS["ink"], lw=1.2))
for i in range(12):
    seg_w = mw / 12
    ax.add_patch(Rectangle((mx0 + i * seg_w + 0.12, my + 0.25),
                           seg_w - 0.24, mh - 0.5,
                           facecolor=COLORS["amber"],
                           alpha=0.15 + 0.85 * (i + 1) / 12,
                           edgecolor="none"))
ax.text(28, 44.9, "\\$ cost accumulates left → right", ha="center",
        fontsize=6, color=COLORS["amber"])
arrow(ax, 28, 40.4, 28, 38.4, color="amber", lw=1.3)
box(ax, 24.5, 33.6, 8, 4.2, "CostLedger", face="amber_lt", edge="amber",
    fs=6.5, mono=True)

# ---- Stage 3: agreement statistics ------------------------------------
diamond(ax, 48, 68, 12, 10, "\u03ba\n(Cohen)", face="paper", edge="ink",
        fs=8)
arrow(ax, 37.4, 60, 41.6, 67.2, label="judge verdicts", fs=6,
      label_pos=0.32)
box(ax, 49.5, 56, 7, 5.2, "agree \u2192\nScoreResult", face="green_lt",
    edge="green", fs=6.3, mono=True)
arrow(ax, 51.5, 63.6, 52.6, 61.4, color="green", lw=1.4)
ticket_stub(ax, 40.5, 54, 7.5, 6, "HumanReviewTicket", fs=5.6)
arrow(ax, 44.6, 63.6, 44, 60.4, color="amber", lw=1.4)
arrow(ax, 44, 53.8, 44, 51.6, color="amber", lw=1.3, label="disagree",
      fs=6)
human_icon(ax, 44, 47.6)
arrow(ax, 46.8, 47.6, 52.4, 55.8, color="amber", lw=1.3, ls="--",
      rad=0.35)
ax.text(48.6, 42.4, "verdict re-enters as ScoreResult", ha="center",
        fontsize=5.5, color=COLORS["amber"],
        bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none",
                  alpha=0.9))
# feedback: ticket -> judge lane (routed through the inter-stage gap at x=18)
ax.plot([41, 38, 38, 18, 18], [53.8, 53.8, 26, 26, 53],
        color=COLORS["amber"], lw=1.4, ls=(0, (4, 3)))
arrow(ax, 18, 53, 20.3, 53, color="amber", lw=1.4, ls="--")
ax.text(28, 27.8, "disagreement patterns \u2192 rubric review", ha="center",
        fontsize=6, color=COLORS["amber"],
        bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none",
                  alpha=0.9))

# ---- Stage 4: report ---------------------------------------------------
ax.text(67, 75.2, "EvalReport", ha="center", fontsize=8.5, weight="bold")
ax.text(67, 71.2, "pass rate + Wilson interval +\ncost-per-verified-success",
        ha="center", fontsize=6.3, color=COLORS["gray"])


def xmap(v):
    return 60.5 + (v - 0.6) / 0.4 * 10.0


for yy, pt, lo, hi, nn in [(62, 0.92, 0.65, 0.99, "n=12"),
                           (57, 0.915, 0.90, 0.93, "n=1200")]:
    ax.plot([xmap(lo), xmap(hi)], [yy, yy], color=COLORS["gray"], lw=2.6)
    for xx in (xmap(lo), xmap(hi)):
        ax.plot([xx, xx], [yy - 0.9, yy + 0.9], color=COLORS["gray"], lw=2.2)
    ax.add_patch(Circle((xmap(pt), yy), 0.85, facecolor=COLORS["ink"],
                        edgecolor="none", zorder=5))
    ax.text(72.2, yy, nn, va="center", fontsize=6, family=MONO)
for tv in (0.6, 0.7, 0.8, 0.9, 1.0):
    ax.plot([xmap(tv), xmap(tv)], [54.6, 55.6], color=COLORS["gray"], lw=1)
    ax.text(xmap(tv), 53.2, f"{tv:.1f}", ha="center", fontsize=5.5,
            family=MONO, color=COLORS["gray"])
ax.text(66, 49.6, "Wilson interval", ha="center", fontsize=6.5,
        style="italic", color=COLORS["gray"])

# ---- Stage 5: CI gate --------------------------------------------------
turnstile(ax, 86, 73.5)
ax.text(86, 66.8, "CI gate", ha="center", fontsize=8.5, weight="bold")
ax.text(86, 62.6, "Wilson lower \u2265 0.90", ha="center", fontsize=6.3,
        family=MONO)
ax.text(86, 59.4, "cost/verified ≤ \\$0.05", ha="center", fontsize=6.3,
        family=MONO)
box(ax, 78.5, 44, 6.5, 7, "merge", face="green_lt", edge="green", fs=7.5)
box(ax, 87.5, 44, 6.5, 7, "blocked", face="red_lt", edge="red", fs=7.5)
arrow(ax, 84, 57, 81.75, 51.5, color="green", lw=1.6)
arrow(ax, 88, 57, 90.75, 51.5, color="red", lw=1.6)
ax.text(90.75, 40.6, "RegressionError /\nCostGateExceededError",
        ha="center", fontsize=5.3, family=MONO, color=COLORS["red"])

# ---- inter-stage arrows -------------------------------------------------
for xa, xb in [(17.2, 18.8), (37.2, 38.8), (57.2, 58.8), (75.2, 76.8)]:
    arrow(ax, xa, 66, xb, 66, lw=1.8)

# ---- feedback loop: gate -> golden set (contamination defense) ---------
arrow(ax, 89, 80.5, 89, 88.5, color="gray", lw=1.4, ls="--")
arrow(ax, 89, 88.5, 9, 88.5, color="gray", lw=1.4, ls="--",
      label="rotate: versioned datasets, archived runs", fs=6.5)
arrow(ax, 9, 88.5, 9, 79.5, color="gray", lw=1.4, ls="--")

# ---- bottom strip: Chapter 16 consumes this -----------------------------
box(ax, 1.5, 4.5, 97, 8, "", face="gray_lt", edge="gray_mid", fs=7,
    lw=1.0)
ax.text(3.2, 8.5, "Chapter 16 consumes this:", fontsize=8, weight="bold",
        va="center", ha="left")
ax.text(27.5, 8.5,
        "walk_forward imports graders → scores each fold "
        "→ PSR/DSR (Ch 17)",
        fontsize=7.5, va="center", ha="left", family=MONO)

save(fig, "ch15-1")
print("ch15-1 done")
