import sys
sys.path.insert(0, "/home/hatch/workspace/book-rebuild/figures")
from _style import *

fig, ax = new_fig(14, 7)
title(ax, "Figure 20.1 \u2014 The Morning Pipeline")

# ============ LANE 1: MCP quote server ============
box(ax, 1, 70, 13, 12, "alphaforge-market-data\nMCP server", face="blue_lt",
    edge="blue", fs=8, mono=True)
box(ax, 1, 55, 13, 12, "get_quote\n(tool card)", face="blue_lt", edge="blue",
    fs=8.5, mono=True)
arrow(ax, 7.5, 67, 7.5, 70, color="blue", lw=1.4)
ax.text(7.5, 49, "every field present\nprovenance: SYNTHETIC", ha="center",
        va="top", fontsize=7, family=MONO, color=COLORS["green"],
        bbox=dict(boxstyle="round,pad=0.3", fc=COLORS["green_lt"], ec=COLORS["green"]))
ax.text(7.5, 42, "the real wire\nalways arrives labeled", ha="center", va="top",
        fontsize=6.5, style="italic", color=COLORS["gray"])

# JSON-RPC arrow: tool card -> FETCH (diagonal, avoids green arrow + attacks)
arrow(ax, 14, 61, 24, 86, color="ink", lw=1.5)
ax.text(19, 68, "JSON-RPC tools/call \u2192 quote dict", ha="center", va="center",
        fontsize=6.5, family=MONO, color=COLORS["ink"],
        bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none", alpha=0.9))

# ============ LANE 2: the lab (chevron stack) ============
def chevron(ax, x, y, w, h, text, face, edge, fs=8, big=False):
    tip = 4 if big else 3
    pts = [(x, y + h), (x + w - tip, y + h), (x + w, y + h / 2),
           (x + w - tip, y), (x, y)]
    ax.add_patch(plt.Polygon(pts, closed=True, facecolor=COLORS.get(face, face),
                             edgecolor=COLORS.get(edge, edge), linewidth=1.6))
    ax.text(x + (w - tip) / 2, y + h / 2, text, ha="center", va="center",
            fontsize=fs, weight="bold" if big else "normal",
            color=COLORS["ink"])

chevron(ax, 24, 84, 15, 9, "FETCH", "gray_lt", "gray", fs=8)
chevron(ax, 21, 64, 21, 16, "", "amber_lt", "amber", big=True)
ax.text(30, 77, "VALIDATE", ha="center", va="center", fontsize=9.5, weight="bold",
        color=COLORS["ink"])
chevron(ax, 24, 54, 15, 10, "LABEL", "gray_lt", "gray", fs=7.5)
chevron(ax, 24, 40, 15, 10, "ROUTE", "gray_lt", "gray", fs=7.5)
chevron(ax, 24, 26, 15, 10, "ACK", "gray_lt", "gray", fs=7.5)
# small connectors between chevrons
for y1, y2 in [(84, 80), (54, 50), (40, 36)]:
    arrow(ax, 31.5, y1, 31.5, y2, color="ink", lw=1.2)

# valid path: exits THROUGH the gate to the evidence spine
arrow(ax, 21, 72, 46, 72, color="green", lw=2.2,
      label="valid quote \u2192 tool_call", fs=7, label_pos=0.18)

# ---- adversarial battery: 4 red arrows strike VALIDATE from below,
#      flanking the narrower lower chevrons ----
for x in (21.5, 23, 40, 41.5):
    arrow(ax, x, 22, x, 64, color="red", lw=1.5, ls="--")
stop_mark(ax, 21.5, 61, s=1.8, color="red")
stop_mark(ax, 40, 61, s=1.8, color="red")

attacks = [
    (19.5, 14, "no provenance", "STOP UnlabeledData"),
    (26.5, 8, "stale quote", "flag \"stale\": True"),
    (36.5, 14, "untrusted source", "STOP UntrustedSource"),
    (44, 8, "scrambled (3,1,2)", "\u2192 (1,2,3) reordered"),
]
for x, y, name, disp in attacks:
    ax.text(x, y + 1.6, name, ha="center", va="center", fontsize=6,
            style="italic", color=COLORS["red"])
    ax.text(x, y - 1.6, disp, ha="center", va="center", fontsize=6,
            family=MONO, color=COLORS["red"])

# ============ LANE 3: evidence spine ============
ax.text(51.5, 93, "the receipt:\nseq + entry_hash", ha="center", va="top",
        fontsize=7.5, weight="bold", color=COLORS["green"],
        bbox=dict(boxstyle="round,pad=0.3", fc=COLORS["green_lt"], ec=COLORS["green"]))
for i, (y, hl) in enumerate([(76, True), (61, False), (46, False), (31, False)]):
    seq = 4 - i
    box(ax, 46, y, 11, 11, f"seq={seq}\nentry_hash\n\u2193 prev hash",
        face="green_lt" if hl else "paper", edge="green" if hl else "ink",
        fs=7.5, mono=True, lw=2.2 if hl else 1.4)
    if i < 3:
        arrow(ax, 51.5, y, 51.5, y - 4, color="ink", lw=1.2)

# ============ LANE 4: signal agent ============
box(ax, 61, 66, 13, 15, "signal agent", face="purple_lt", edge="purple", fs=9)
arrow(ax, 57, 80, 61, 80, color="green", lw=1.8)
ax.text(59, 83.5, "signals read only\nvalidated evidence", ha="center",
        va="bottom", fontsize=6.5, color=COLORS["green"],
        bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none", alpha=0.9))

# the canonical failure: direct lane1 -> lane4, crossed out
ax.annotate("", xy=(61, 70), xytext=(14, 58),
            arrowprops=dict(arrowstyle="-|>", color=COLORS["red"], lw=1.8,
                            ls=(0, (5, 4)), mutation_scale=14, shrinkA=1, shrinkB=3))
stop_mark(ax, 44, 63.5, s=2.4, color="red")
ax.text(44, 57.5, "the canonical failure:\na signal that read unlabeled data",
        ha="center", va="top", fontsize=6.5, style="italic", color=COLORS["red"],
        bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="none", alpha=0.92))

# ============ LANE 5: the guarantee ============
box(ax, 78, 52, 21, 26,
    "THE GUARANTEE\n\nEvery entry in this log survived\nvalidation \u2014 the only way in\nwas through the pipeline.",
    face="green_lt", edge="green", fs=7.5)
ax.text(88.5, 44, "router.verify()", ha="center", va="center", fontsize=9,
        family=MONO, color=COLORS["green"],
        bbox=dict(boxstyle="round,pad=0.4", fc="white", ec=COLORS["green"]))
ax.text(93.5, 40, "\u2713", ha="center", va="center", fontsize=16,
        color=COLORS["green"], weight="bold")
ax.text(93.5, 35, "clean", ha="center", va="center", fontsize=8,
        color=COLORS["green"], weight="bold")

# lane labels
for x, lbl in [(7.5, "L1 \u00b7 quote server"), (31.5, "L2 \u00b7 the lab"),
                (51.5, "L3 \u00b7 evidence"), (67.5, "L4 \u00b7 signals"),
                (88.5, "L5 \u00b7 guarantee")]:
    ax.text(x, 2.5, lbl, ha="center", va="bottom", fontsize=7.5, weight="bold",
            color=COLORS["gray"])

save(fig, "ch20")
print("ch20 ok")
