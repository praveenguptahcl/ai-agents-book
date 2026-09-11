"""Figure 21.1 - The Signal Validation Pipeline (rewrite: gutter annotations)."""
import sys
sys.path.insert(0, "/home/hatch/workspace/book-rebuild/figures")
from _style import *

fig, ax = new_fig(8, 10)
title(ax, "Figure 21.1 \u2014 The Signal Validation Pipeline", y=96.5)

X0, X1 = 4, 54          # stage boxes
RX0, RX1 = 70, 98       # rejected column
GX0, GX1 = 56, 68       # annotation gutter

stages = [
    (80, "1. PARSE", "raw string \u2192 JSON"),
    (62, "2. SCHEMA-CHECK", "shape: required, types, enum"),
    (44, "3. CONTRACT-GATE", "judgment: ranges, allowlist,\nnotional cap"),
    (26, "4. DEDUPE", "proposal_id seen before?"),
]
for y, t1, t2 in stages:
    box(ax, X0, y, X1 - X0, 14, f"{t1}\n{t2}", face="blue_lt", edge="blue",
        fs=9, lw=1.6)

# down arrows (accept path)
for i in range(3):
    y_top = stages[i][0]
    y_bot = stages[i + 1][0] + 14
    arrow(ax, 29, y_top, 29, y_bot, color="ink", lw=1.8)

# rejected column
box(ax, RX0, 18, RX1 - RX0, 70, "", face="#fdecea", edge="red", lw=1.6)
ax.text((RX0 + RX1) / 2, 84, "REJECTED", ha="center", va="center",
        fontsize=13, weight="bold", color=COLORS["red"])
ax.text((RX0 + RX1) / 2, 80.5, "(named reason, closed set)", ha="center",
        va="center", fontsize=7.5, style="italic", color=COLORS["gray"])

reasons = ["MALFORMED_JSON", "SCHEMA_VIOLATION", "CONTRACT_VIOLATION", "DUPLICATE_ID"]
for (y, _, _), r in zip(stages, reasons):
    cy = y + 7
    arrow(ax, X1, cy, RX0, cy, color="red", lw=1.8)
    ax.text(RX0 + 1.5, cy + 1.2, r, ha="left", va="bottom", fontsize=6.5,
            color=COLORS["red"], family=MONO)

ax.text((RX0 + RX1) / 2, 21.5,
        "Every refusal has a name.\nA rejection without a name is a shrug.",
        ha="center", va="center", fontsize=7.5, style="italic", color=COLORS["red"])

# accepted
box(ax, 14, 10, 30, 8, "ACCEPTED", face="green_lt", edge="green", fs=11, lw=1.8)
arrow(ax, 44, 14, 62, 14, color="green", lw=2.2)
ax.text(53, 15.8, "to the executor (Lab 3)", ha="center", va="bottom",
        fontsize=7, color=COLORS["green"], family=MONO)

# ---- gutter annotations (x 56-68): layer split + two callouts ----
ax.annotate("", xy=(GX0, 58.5), xytext=(GX0, 65.5),
            arrowprops=dict(arrowstyle="<->", color=COLORS["ink"], lw=1.4,
                            shrinkA=1, shrinkB=1))
ax.text(GX0 + 1, 64.5, "the layer split", ha="left", va="center", fontsize=7,
        weight="bold")
ax.text(GX0 + 1, 60.5,
        "stage 2 cannot express\nranges (strict mode);\nstage 3 adds judgment\nthe provider never\nguaranteed.",
        ha="left", va="center", fontsize=6, style="italic", color=COLORS["gray"])

box(ax, GX0, 45, GX1 - GX0, 10,
    "10,000,000 \u00d7 $590\n\u2014 perfectly shaped,\nsemantically absurd.\nOnly the contract\nknows.",
    face="#fff7d6", edge="amber", fs=6, lw=1.2)
box(ax, GX0, 27, GX1 - GX0, 10,
    "retry or replay \u2014\naccepted\nexactly once.",
    face="gray_lt", edge="gray", fs=6, lw=1.2)

save(fig, "ch21")
print("ch21 ok")
