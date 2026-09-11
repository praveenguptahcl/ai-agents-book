"""Ch2 — The ODAV loop: circular 4-stage flow with authority gate,
evidence taps, VERIFY->OBSERVE feedback, and a muted-red open-loop inset."""
import sys
sys.path.insert(0, "/home/hatch/workspace/book-rebuild/figures")
from _style import *
from matplotlib.patches import FancyBboxPatch

fig, ax = new_fig(10, 6.5)
title(ax, "The ODAV Loop", fs=18)


def node(cx, cy, w, h, stage, sub, color):
    p = FancyBboxPatch((cx - w / 2, cy - h / 2), w, h,
                       boxstyle="round,pad=0.02",
                       facecolor=COLORS["paper"], edgecolor=COLORS[color],
                       linewidth=2.4)
    ax.add_patch(p)
    ax.text(cx, cy + 2.2, stage, ha="center", va="center", fontsize=14,
            family=MONO, weight="bold", color=COLORS[color])
    ax.text(cx, cy - 2.9, sub, ha="center", va="center", fontsize=10.5,
            color=COLORS["gray"], linespacing=1.45)
    return p


# --- evidence taps (thin, dashed, drawn first so nodes sit on top) ---
for (x1, y1, x2) in [(52, 73, 58), (66, 51, 63), (46, 29, 46), (27, 51, 30)]:
    arrow(ax, x1, y1, x2, 20, color="gray_mid", lw=1.2, ls="--")
box(ax, 25, 12, 42, 7, "audit trail  —  every stage emits evidence",
    face="gray_lt", edge="gray_mid", fs=11)

# --- thick clockwise ring arrows ---
arrow(ax, 56, 74, 60, 64, color="ink", lw=2.8, rad=-0.2)    # OBSERVE -> DECIDE
arrow(ax, 62, 51, 53, 43, color="ink", lw=2.8, rad=-0.2)    # DECIDE -> ACT
arrow(ax, 36, 38, 32, 51, color="ink", lw=2.8, rad=-0.2)    # ACT -> VERIFY
arrow(ax, 27, 65, 36, 75, color="green", lw=2.2, ls="--", rad=0.35)  # VERIFY -> OBSERVE
ax.text(21.5, 72.5, "verified state becomes\nthe next observation",
        ha="center", va="center", fontsize=10, color=COLORS["green"],
        style="italic", linespacing=1.4)

# --- the four stage nodes ---
node(46, 80, 26, 13, "OBSERVE", "Gather state,\nwith provenance & age.", "blue")
node(69, 58, 26, 13, "DECIDE", "Propose an intention —\nnever an order.", "amber")
node(46, 36, 20, 13, "ACT", "External effect through\nthe guarded boundary.", "red")
node(23, 58, 26, 13, "VERIFY", "Read the world back.\nNot closed until it lands.", "green")

# ACT drawn as a narrow gate: doorway posts just inside the box edges
for px in (37.8, 54.2):
    ax.plot([px, px], [30.5, 41.5], color=COLORS["red"], lw=2.0)

# --- authority gate badge on the DECIDE -> ACT arrow ---
box(ax, 60, 44, 12, 7, "AUTHORITY", face="amber_lt", edge="amber",
    fs=10, mono=True, lw=1.6)
ax.text(58.5, 42.5, "verified at action time,\nnot decision time",
        ha="left", va="top", fontsize=9.5, color=COLORS["amber"],
        linespacing=1.35)

# --- stage badges ---
ax.text(89, 58, "LLM lives here\n(non-deterministic)", ha="center", va="center",
        fontsize=9.5, style="italic", color=COLORS["amber"], linespacing=1.35)
ax.text(19, 31.5, "the only stage that\nchanges the world", ha="center",
        va="center", fontsize=9.5, style="italic", color=COLORS["red"],
        linespacing=1.35)

# --- incoming world arrow into OBSERVE ---
arrow(ax, 6, 79, 30, 78.5, color="ink", lw=1.8,
      label="world (quotes, inbox, positions)", fs=10)

# --- muted-red inset: the broken open loop ---
box(ax, 66, 21, 31, 14, "", face="red_lt", edge="red", ls="--", lw=1.4)
ax.text(81.5, 32.2, "Open loop (not a loop)", ha="center", va="center",
        fontsize=10.5, weight="bold", color=COLORS["red"])
ax.text(81.5, 26.6, "OBSERVE → DECIDE → ACT, no VERIFY\n"
                    "commands issued, world assumed obedient\n"
                    "Works in demos; fails in production.",
        ha="center", va="center", fontsize=9, color=COLORS["red"],
        linespacing=1.4)

caption(ax, "Four stages, one gate, zero trust in the middle. "
            "Verification is what makes it a loop.", fs=12.5)

save(fig, "ch02")
print("ch02 done")
