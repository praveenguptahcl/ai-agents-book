"""Figure 14.1 — The Operating Pipeline (three lanes + durability underlay)."""
import sys
sys.path.insert(0, "/home/hatch/workspace/book-rebuild/figures")
from _style import *
from matplotlib.patches import Circle

fig, ax = new_fig(13, 8.2)
title(ax, "The Operating Pipeline", y=97.5)

ax.plot([26, 26], [20, 93], color=COLORS["gray_mid"], lw=0.8, ls="--")
ax.plot([60, 60], [20, 93], color=COLORS["gray_mid"], lw=0.8, ls="--")
ax.text(14, 91, "Lane 1 — agent loop", ha="center", va="center", fontsize=8,
        weight="bold", color=COLORS["ink"])
ax.text(43, 91, "Lane 2 — evidence path (spine)", ha="center", va="center",
        fontsize=8, weight="bold", color=COLORS["ink"])
ax.text(79, 91, "Lane 3 — model gateway", ha="center", va="center", fontsize=8,
        weight="bold", color=COLORS["ink"])

# ============ Lane 1: ODAV ============
box(ax, 2, 62, 22, 24, "", face="paper", edge="ink", lw=1.4)
ax.text(13, 83.5, "Agent loop (ODAV)", ha="center", va="center", fontsize=8,
        weight="bold", family=MONO)
chips = [("Observe", 77.5), ("Decide", 72), ("Act", 66.5), ("Verify", 61)]
chip_pos = {}
for clab, cy in chips:
    box(ax, 4.5, cy, 17, 4.6, clab, face="blue_lt", edge="blue", fs=6.5,
        mono=True, lw=1.1)
    chip_pos[clab] = cy + 2.3

# submit() from the loop down into Lane 2's writer
arrow(ax, 13, 62, 40, 66, color="ink", lw=1.2)
ax.text(26, 60.2, "submit() -- non-blocking", ha="center", va="center",
        fontsize=6.2, family=MONO, color=COLORS["ink"],
        bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none",
                  alpha=0.95))

# complete() from Decide chip to the gateway (routed under Lane 2)
ax.plot([22, 26], [chip_pos["Decide"], chip_pos["Decide"]],
        color=COLORS["ink"], lw=1.2)
ax.plot([26, 26], [42, chip_pos["Decide"]], color=COLORS["ink"], lw=1.2)
ax.plot([26, 68], [42, 42], color=COLORS["ink"], lw=1.2)
arrow(ax, 68, 42, 68, 58, color="ink", lw=1.2)
ax.text(46, 42, "complete(task_class, request)", ha="center", va="center",
        fontsize=6.2, family=MONO, color=COLORS["ink"],
        bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="white",
                  alpha=1.0))

# ============ Lane 2: evidence spine ============
box(ax, 28, 66, 30, 16, "", face="paper", edge="ink", lw=2.4)
ax.text(43, 79, "TraceWriter -- bounded queue (10k),\nsingle consumer, seq under lock",
        ha="center", va="center", fontsize=6.6, family=MONO, weight="bold",
        linespacing=1.3)
ax.text(43, 72.5, "queue full -> agent PAUSES (backpressure), never drops",
        ha="center", va="center", fontsize=5.9, family=MONO,
        color=COLORS["orange"],
        bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none", alpha=0.9))
ax.text(43, 68.5, "consumer dead -> EvidenceWriterDown (loud), never silent",
        ha="center", va="center", fontsize=5.9, family=MONO,
        color=COLORS["red"],
        bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none", alpha=0.9))

box(ax, 28, 54, 30, 10, "EvidenceRouter.emit()\n(Ch 9 -- the single choke point)",
    face="paper", edge="ink", fs=6.6, mono=True, lw=2.0)
arrow(ax, 43, 66, 43, 64, color="ink", lw=1.6)

# fan-out bus on the left of the sinks
ax.plot([24, 28], [59, 59], color=COLORS["blue"], lw=1.4)
ax.plot([24, 24], [27, 59], color=COLORS["blue"], lw=1.4)
arrow(ax, 24, 47.5, 28, 47.5, color="blue", lw=1.4)
arrow(ax, 24, 37, 28, 37, color="blue", lw=1.4)
arrow(ax, 24, 27, 28, 27, color="blue", lw=1.4)

box(ax, 28, 43, 30, 9,
    "Audit log -- HMAC-chained,\neverything, forever", face="blue_lt",
    edge="blue", fs=6.4, mono=True, lw=1.6)
ax.text(50, 44.3, "\u2693 WORM checkpoint anchor", ha="center", va="center",
        fontsize=5.2, family=MONO, color=COLORS["amber"])
box(ax, 28, 33, 30, 8, "Trace sink -- ring buffer,\nlast hour, full fidelity",
    face="blue_lt", edge="blue", fs=6.4, mono=True, lw=1.6)
box(ax, 28, 23, 30, 8, "Eval dataset -- frozen snapshots\nfor the judge (Ch 15)",
    face="blue_lt", edge="blue", fs=6.4, mono=True, lw=1.6)

# return arrow: audit log -> durable runs
ax.plot([8, 32], [43, 43], color=COLORS["gray"], lw=1.3)
arrow(ax, 8, 43, 8, 17, color="gray", lw=1.3,
      label="resume-from-ledger\n(durable runs read here)", fs=6.0,
      label_pos=0.45)

# ============ Lane 3: model gateway ============
box(ax, 62, 58, 22, 28, "", face="paper", edge="ink", lw=1.4)
ax.text(73, 84, "ModelGateway", ha="center", va="center", fontsize=8,
        weight="bold", family=MONO)
for slab, sy in [("route(task -> model)", 77), ("fallback chain", 71),
                 ("cache (keyed by intent hash)", 65),
                 ("cost ledger ($/verified call)", 59)]:
    box(ax, 64, sy, 18, 5, slab, face="gray_lt", edge="gray", fs=5.8,
        mono=True, lw=1.0)

box(ax, 62, 38, 22, 14, "Providers\n(primary -> fallback)", face="paper",
    edge="ink", fs=7, mono=True, lw=1.4)
arrow(ax, 78, 58, 78, 52, color="ink", lw=1.4)

box(ax, 66, 20, 18, 8, "SLO dashboard\nevidence lag, cost/verified\nsignal, \u03ba",
    face="amber_lt", edge="amber", fs=6, mono=True, lw=1.2)
ax.plot([86, 86], [24, 61], color=COLORS["gray"], lw=1.3, ls="--")
arrow(ax, 86, 24, 84, 24, color="gray", lw=1.3, ls="--")

# ============ Underlay: durable runs ============
box(ax, 2, 4, 96, 13, "", face="gray_lt", edge="gray", lw=1.2)
ax.text(50, 14.8, "Durable runs", ha="center", va="center", fontsize=8,
        weight="bold", color=COLORS["ink"])
steps = ["Lease\n(monotonic TTL)", "heartbeat\nrenews",
         "fence: stale token\nwrites REJECTED",
         "checkpoint\n(state, audit seq)",
         "replacement replays\nevidence, not actions"]
sx = 4
for i, s in enumerate(steps):
    box(ax, sx, 6, 16.5, 7.5, s, face="paper", edge="ink", fs=5.6, mono=True,
        lw=1.1)
    if i < 4:
        arrow(ax, sx + 16.5, 9.75, sx + 18.5, 9.75, color="ink", lw=1.2)
    sx += 18.5

# failover clock markers
for cx_, clab in [(12.25, "3:07am"), (88.25, "3:08am")]:
    c = Circle((cx_, 14.9), 1.3, facecolor="white",
               edgecolor=COLORS["ink"], linewidth=1.0)
    ax.add_patch(c)
    ax.text(cx_, 14.9, "\u25d4", ha="center", va="center", fontsize=10,
            color=COLORS["ink"])
    ax.text(cx_, 12.4, clab, ha="center", va="center", fontsize=5.6,
            family=MONO, color=COLORS["ink"])

save(fig, "ch14")
print("ch14 done")
