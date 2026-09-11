"""Figure 8.1 — Orchestration topology and delegation scope (two-panel)."""
import sys
sys.path.insert(0, "/home/hatch/workspace/book-rebuild/figures")
from _style import *
from matplotlib.patches import FancyBboxPatch

fig, ax = new_fig(13, 7)
title(ax, "Orchestration topology and delegation scope", y=97.5)

ax.text(24.5, 93.5, "Three topologies", ha="center", va="center",
        fontsize=10, weight="bold", color=COLORS["ink"])
ax.text(74.5, 93.5, "Attenuation down the chain", ha="center", va="center",
        fontsize=10, weight="bold", color=COLORS["ink"])
ax.plot([49, 49], [6, 92], color=COLORS["gray_mid"], lw=0.8, ls="--")

# ---------------- Left panel: three topologies ----------------
def panel(ax, x, y, w, h, title_, lbl):
    box(ax, x, y, w, h, "", face="paper", edge="gray", lw=1.0)
    ax.text(x + w / 2, y + h - 2.2, title_, ha="center", va="center",
            fontsize=9, weight="bold", family=MONO)
    ax.text(x + w / 2, y + 1.9, lbl, ha="center", va="center",
            fontsize=6.4, style="italic", color=COLORS["gray"], wrap=True,
            linespacing=1.15)

def hatched_node(ax, x, y, w, h, text, hatch, fs=7):
    p = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.01",
                       facecolor=COLORS["gray_lt"], edgecolor=COLORS["ink"],
                       linewidth=1.1, hatch=hatch)
    ax.add_patch(p)
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
            fontsize=fs, family=MONO, color=COLORS["ink"])

def plain_node(ax, x, y, w, h, text, fs=7):
    return box(ax, x, y, w, h, text, face="paper", edge="ink", fs=fs, mono=True)

# (a) Supervisor — hatch ///
panel(ax, 2, 62, 45, 28, "(a) Supervisor",
      "authority centralized; every delegation an explicit grant.")
plain_node(ax, 18.5, 77, 12, 6.5, "Supervisor")
for (wx, wt) in [(4, "Research"), (19.5, "Risk"), (34, "Settle")]:
    hatched_node(ax, wx, 66.5, 10, 5.5, wt, "///", fs=6.5)
    arrow(ax, 24.5, 77, wx + 5, 72, color="blue", lw=1.3, rad=0.12)
    arrow(ax, wx + 5, 72, 24.5, 77, color="blue", lw=1.3, rad=0.12)

# (b) Hierarchical — hatch ...
panel(ax, 2, 33, 45, 27, "(b) Hierarchical",
      "intent degrades per hop; depth limits mandatory.")
plain_node(ax, 19.5, 50.5, 11, 5, "Supervisor")
for (mx_, mt) in [(8, "Mid A"), (28, "Mid B")]:
    hatched_node(ax, mx_, 44, 11, 5, mt, "...", fs=6.5)
    arrow(ax, 25, 50.5, mx_ + 5.5, 49, color="ink", lw=1.2)
for (lx, m) in [(3, 13.5), (14, 13.5), (25, 33.5), (36, 33.5)]:
    hatched_node(ax, lx, 37, 8.5, 4.5, "Leaf", "...", fs=6)
    arrow(ax, m, 44, lx + 4.25, 41.5, color="ink", lw=1.1)

# (c) Peer triangle — hatch \\\ ; red dashed cycle A -> B -> A
panel(ax, 2, 5, 45, 26, "(c) Peer / market",
      "'who said so?' needs a constitution; cycles are the normal case.")
hatched_node(ax, 10, 14.5, 9, 5, "A", "\\\\\\", fs=7)
hatched_node(ax, 28, 14.5, 9, 5, "B", "\\\\\\", fs=7)
hatched_node(ax, 19, 8, 9, 5, "C", "\\\\\\", fs=7)
arrow(ax, 19, 18, 28, 18, color="ink", lw=1.2, rad=0.15)
arrow(ax, 28, 16.5, 19, 16.5, color="ink", lw=1.2, rad=0.15)
arrow(ax, 15, 14.5, 21, 13, color="ink", lw=1.2, rad=0.15)
arrow(ax, 22, 13, 17, 14.5, color="ink", lw=1.2, rad=-0.15)
arrow(ax, 32, 14.5, 26, 13, color="ink", lw=1.2, rad=0.15)
arrow(ax, 28, 13, 30, 14.5, color="ink", lw=1.2, rad=-0.15)
# red dashed cycle A -> B -> A: two parallel arcs above A and B
arrow(ax, 12, 20.8, 34, 20.8, color="red", lw=1.7, ls="--", rad=0.5)
arrow(ax, 34, 19.9, 12, 19.9, color="red", lw=1.7, ls="--", rad=0.5)
ax.text(23, 26.2, "CycleDetected names every hop", ha="center", va="bottom",
        fontsize=6.5, family=MONO, color=COLORS["red"],
        bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none", alpha=0.9))

# ---------------- Right panel: attenuation ----------------
ox, oy, ow, oh = 55, 52, 39, 36
mx, my, mw, mh = 60.5, 57.5, 28, 25
ix, iy, iw, ih = 66.5, 63.5, 16, 13

for (rx, ry, rw, rh) in [(ox, oy, ow, oh), (mx, my, mw, mh)]:
    ring = FancyBboxPatch((rx, ry), rw, rh, boxstyle="round,pad=0.01",
                          facecolor=COLORS["amber_lt"], edgecolor="none",
                          alpha=0.85)
    ax.add_patch(ring)
box(ax, ox, oy, ow, oh, "", face="paper", edge="ink", lw=1.6)
ax.text(ox + ow / 2, oy + oh - 2.6,
        "Orchestrator authority\n{market.read, orders.propose, risk.veto}",
        ha="center", va="center", fontsize=7, family=MONO, color=COLORS["ink"])
box(ax, mx, my, mw, mh, "", face="paper", edge="ink", lw=1.4)
ax.text(mx + mw / 2, my + mh - 2.6, "Delegation grant\n{market.read}",
        ha="center", va="center", fontsize=7, family=MONO, color=COLORS["ink"])
box(ax, ix, iy, iw, ih, "Sub-delegation\n{market.read}", face="red_lt",
        edge="red", fs=6.8, mono=True, lw=1.6)
ax.text(ox + 1.5, oy + 7.2, "refused,\nnever\nsilently\nnarrowed",
        ha="left", va="center", fontsize=6.4, style="italic",
        color=COLORS["amber"], wrap=True, linespacing=1.2)
arrow(ax, ix + iw, iy + ih / 2, ix + iw + 6.5, iy + ih / 2 + 4.5, color="red",
      lw=1.8, label="ScopeDenied", fs=7)
stop_mark(ax, ix + iw + 4.2, iy + ih / 2 + 3.0, s=2.4)

# delegation lifecycle strip
ax.text(74.5, 45.5, "One delegation's lifecycle", ha="center", va="center",
        fontsize=9, weight="bold", color=COLORS["ink"])
ty, th = 33, 7
segs = [(52, 8.5, "OPEN", "blue_lt", "blue"),
        (62, 6.5, "ok", "green_lt", "green"),
        (70, 8.0, "failed", "red_lt", "red"),
        (79.5, 6.5, "open", "gray_lt", "gray"),
        (87.5, 9.5, "quarantined", "amber_lt", "amber")]
prev_right = None
for (sx, w, s, f, e) in segs:
    if prev_right is not None:
        arrow(ax, prev_right, ty + th / 2, sx, ty + th / 2, color="gray", lw=1.2)
    box(ax, sx, ty, w, th, s, face=f, edge=e, fs=6.8, mono=True)
    prev_right = sx + w
arrow(ax, 90.5, ty - 0.5, 56, ty - 1.5, color="gray", lw=1.3, ls="--",
      rad=-0.45)
ax.text(73, 26.8, "reconcile()", ha="center", va="bottom", fontsize=7,
        family=MONO, color=COLORS["gray"],
        bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none", alpha=0.9))
ax.text(73, 21.8, "timeout -> reconcile()", ha="center", va="center",
        fontsize=7, family=MONO, color=COLORS["gray"])

caption(ax, "Authority attenuates down the delegation chain and never widens; "
            "every delegation starts open and only verified evidence closes it.",
        y=2.5, fs=8.2)

save(fig, "ch08")
print("ch08 done")
