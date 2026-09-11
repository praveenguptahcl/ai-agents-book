import sys
sys.path.insert(0, "/home/hatch/workspace/book-rebuild/figures")
from _style import *
from matplotlib.patches import FancyBboxPatch

# ---------- FIG-E: nine-gate certification wall ----------
fig, ax = new_fig(10, 8)
title(ax, "Figure E.1 \u2014 The Nine-Gate Certification Wall", fs=12)

gates = [
    ("1", "Identity", "Ch 3, 6", "identity proof \u2014 keys + principals, asserted"),
    ("2", "Authority", "Ch 6, 18", "authority policy \u2014 principals + scopes, default-deny asserted"),
    ("3", "Contracts", "Ch 4", "tool contracts \u2014 Pydantic schemas, versioned"),
    ("4", "Threat model", "Ch 12", "threat model \u2014 STRIDE, reviewed"),
    ("5", "Eval thresholds", "Ch 15", "eval gates \u2014 \u03ba \u2265 0.6, cost \u2264 1.00, frozen set"),
    ("6", "Rollback", "Ch 11, 14", "rollback plan \u2014 rehearsed, timed"),
    ("7", "Logging", "Ch 9", "evidence log \u2014 hash-chained, verifiable"),
    ("8", "Escalation", "Ch 19", "escalation matrix \u2014 named humans, SLAs"),
    ("9", "Incident owner", "Ch 14", "incident owner \u2014 named, paged, on-call"),
]

# left column: gate rows (x 2-52); extra breathing room after the failing row
for i, (num, name, ch, artifact) in enumerate(gates):
    y = 84 - i * 8.6 - (7 if i >= 2 else 0)
    fail = (num == "2")
    face = "red_lt" if fail else "paper"
    edge = "red" if fail else "gray_mid"
    p = FancyBboxPatch((2, y), 50, 7.6, boxstyle="round,pad=0.01",
                       facecolor=COLORS[face], edgecolor=COLORS[edge],
                       linewidth=2.0 if fail else 1.1)
    ax.add_patch(p)
    checked = "\u2611" if not fail else "\u2610"
    ax.text(4.5, y + 3.8, checked, ha="center", va="center", fontsize=11,
            color=COLORS["red"] if fail else COLORS["green"])
    ax.text(8, y + 5.2, f"{num}. {name}", ha="left", va="center", fontsize=8,
            weight="bold", color=COLORS["ink"])
    ax.text(8, y + 2.2, artifact, ha="left", va="center", fontsize=6.5,
            style="italic", color=COLORS["gray"], family=MONO)
    # chapter chip
    ax.text(50, y + 5.2, ch, ha="right", va="center", fontsize=6.5,
            color=COLORS["blue"],
            bbox=dict(boxstyle="round,pad=0.3", fc=COLORS["blue_lt"],
                      ec=COLORS["blue"]))

# callout B sits in the gap under the failing row (gate 2: y 75.4-83)
ax.text(6, 71.5, "B", ha="center", va="center", fontsize=9, weight="bold",
        color="white", bbox=dict(boxstyle="circle,pad=0.4", fc=COLORS["red"],
                                 ec="none"))
ax.text(11, 71.5, "The remediation names the exact document to write.\nRed-to-green is a work list, not a feeling.",
        ha="left", va="center", fontsize=6.5, style="italic",
        color=COLORS["red"])
arrow(ax, 27, 75.4, 27, 73.6, color="red", lw=1.2)

# ---- right column: verdict panel (x 56-98) ----
box(ax, 56, 58, 42, 30, "", face="gray_lt", edge="ink", fs=8)
ax.text(77, 84, "run_standard(evidence)", ha="center", va="center",
        fontsize=9, family=MONO, color=COLORS["ink"])
ax.text(77, 79.5, "\u2192", ha="center", va="center", fontsize=12,
        color=COLORS["ink"])
ax.text(77, 75, "GateReport", ha="center", va="center", fontsize=9,
        family=MONO, weight="bold", color=COLORS["ink"])
ax.text(77, 70.5, ".ships", ha="center", va="center", fontsize=9, family=MONO,
        color=COLORS["ink"])

# traffic light
for j, (c, lab) in enumerate([("green", "all checked"), ("red", "one unchecked")]):
    cx = 70 + j * 14
    circ = plt.Circle((cx, 64), 3.2, facecolor=COLORS[c], edgecolor=COLORS["ink"],
                      linewidth=1.4)
    ax.add_patch(circ)
    ax.text(cx, 59.5, lab, ha="center", va="top", fontsize=6.5,
            color=COLORS["ink"])

# callout A on the traffic light
ax.text(94, 64, "A", ha="center", va="center", fontsize=9, weight="bold",
        color="white", bbox=dict(boxstyle="circle,pad=0.4", fc=COLORS["ink"],
                                 ec="none"))
ax.text(77, 53, "One unchecked box fails the build. Certification is all-or-nothing\nby design \u2014 a system with eight gates is a system with a hole.",
        ha="center", va="top", fontsize=6.5, style="italic", color=COLORS["ink"])

# rendered verdict block
box(ax, 56, 26, 42, 20, "", face="paper", edge="ink", fs=8, lw=1.6)
ax.text(58, 43, "[x] identity: demonstrated", ha="left", va="center",
        fontsize=7.5, family=MONO, color=COLORS["green"])
ax.text(58, 38.5, "[ ] authority: MISSING: authority policy", ha="left",
        va="center", fontsize=7.5, family=MONO, color=COLORS["red"],
        bbox=dict(boxstyle="round,pad=0.3", fc=COLORS["red_lt"], ec="none"))
ax.text(58, 34, "\u2192 Produce the authority policy\n   (principals + scopes, default-deny).",
        ha="left", va="center", fontsize=7, style="italic", color=COLORS["ink"])
ax.text(58, 29, "STANDARD_VERSION 1.0 \u2014 re-certify on every bump.",
        ha="left", va="center", fontsize=6.5, style="italic",
        color=COLORS["gray"], family=MONO)

# callout C footer
ax.text(77, 20, "C", ha="center", va="center", fontsize=9, weight="bold",
        color="white", bbox=dict(boxstyle="circle,pad=0.4", fc=COLORS["ink"],
                                 ec="none"))
ax.text(77, 15.5, "A claim is not a demonstration.", ha="center", va="center",
        fontsize=8, style="italic", weight="bold", color=COLORS["ink"])

caption(ax, "Figure E.1. The Agent Production Standard v1.0: nine gates, nine artifacts, one verdict.", y=4)

save(fig, "app-e")
print("app-e ok")
