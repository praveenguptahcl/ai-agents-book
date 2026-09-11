import sys
sys.path.insert(0, "/home/hatch/workspace/book-rebuild/figures")
from _style import *
import numpy as np

fig, ax = new_fig(14, 8)
title(ax, "Figure 22.1 \u2014 The Crash Timeline")

rng = np.random.default_rng(22)
n = 60
# decline 100 -> 95 over first 46 bars, then steeper 95 -> 93.4 during halt
t = np.arange(n)
noise = rng.normal(0, 0.18, n)
seg1 = 100.0 - (5.0 / 45) * t[:46]
seg2 = 95.0 - (1.6 / 13) * np.arange(1, n - 46 + 1)
price = np.concatenate([seg1 + noise[:46], seg2 + noise[46:]])
price = np.clip(price, 93.2, 100.4)

# geometry: time axis 14:32 -> 15:35 mapped x 12..98
x0, x1 = 12, 98
def tx(bar):
    return x0 + (x1 - x0) * bar / (n - 1)
# phase boundaries in minutes: 14:32=0, 14:52=20, 15:03=31, 15:21=49, 15:35=63
def xm(mins):
    return x0 + (x1 - x0) * mins / 63
b_norm, b_rej, b_sil, b_rec = xm(20), xm(31), xm(49), xm(63)
trip_bar = int(np.argmax(price < 95.0))  # first crossing ~ bar 46
trip_x = tx(trip_bar)

lanes = {"market": (78, 97), "broker": (58, 76), "kill": (38, 55), "ledger": (13, 34)}
for lane, (y0, y1) in lanes.items():
    ax.plot([x0, x1], [y1, y1], color=COLORS["gray_mid"], lw=0.8)
lane_labels = {"market": "Market", "broker": "Broker",
               "kill": "Kill switch", "ledger": "Ledger"}
for lane, (y0, y1) in lanes.items():
    ax.text(x0 - 1, (y0 + y1) / 2, lane_labels[lane], ha="right", va="center",
            fontsize=9, weight="bold", color=COLORS["ink"])

# time axis ticks
for mins, lbl in [(0, "14:32"), (20, "14:52"), (31, "15:03"), (49, "15:21"), (63, "15:35")]:
    ax.plot([xm(mins), xm(mins)], [11, 13], color=COLORS["ink"], lw=1)
    ax.text(xm(mins), 9.5, lbl, ha="center", va="top", fontsize=7.5, family=MONO,
            color=COLORS["ink"])

# ---- Lane 1: Market ----
y0, y1 = lanes["market"]
def py(p):
    return y0 + (y1 - y0) * (p - 92.5) / (100.8 - 92.5)
ax.plot([tx(i) for i in range(n)], [py(p) for p in price], color=COLORS["blue"], lw=2)
ax.plot([x0, x1], [py(95), py(95)], color=COLORS["red"], ls="--", lw=1.4)
ax.text(x1 + 0.5, py(95), "\u22125% trip (95.0)", ha="left", va="center",
        fontsize=7.5, color=COLORS["red"])
ax.plot([trip_x, trip_x], [y0, y1], color=COLORS["ink"], lw=1.4)
ax.text(trip_x, y1 - 4,
        "trip bar (~bar %d): scoped PAUSE_INTENTS engages for desk A" % trip_bar,
        ha="center", va="center", fontsize=7.5, color=COLORS["ink"],
        bbox=dict(boxstyle="round,pad=0.3", fc="white", ec=COLORS["gray_mid"]))
# second wave label (during halt): place under the steep segment
ax.text((trip_x + b_rec) / 2, y0 + 1.5, "second wave (during halt)", ha="center",
        va="center", fontsize=7.5, style="italic", color=COLORS["red"])

# ---- Lane 2: Broker phase bands ----
y0, y1 = lanes["broker"]
bands = [
    (xm(0), b_norm, "normal\nfills immediately", "green_lt", "green", None),
    (b_norm, b_rej, "rejecting\nanswers, but rejected\nrisk: market-wide halt",
     "amber_lt", "amber", "///"),
    (b_rej, b_sil, "silent\nsubmits time out\nlookups fail\nOUTCOME-UNKNOWN",
     "red_lt", "red", "xxx"),
    (b_sil, b_rec, "recovered\nbroker truth readable again", "green_lt", "green", None),
]
for xa, xb, lbl, face, edge, hatch in bands:
    p = mpatches = None
    rect = plt.Rectangle((xa, y0 + 1), xb - xa, y1 - y0 - 2,
                         facecolor=COLORS[face], edgecolor=COLORS[edge],
                         linewidth=1.2, hatch=hatch)
    ax.add_patch(rect)
    ax.text((xa + xb) / 2, (y0 + y1) / 2, lbl, ha="center", va="center",
            fontsize=7.5, color=COLORS["ink"], wrap=True, linespacing=1.3)
# vertical separators at phase boundaries
for bx in [b_norm, b_rej, b_sil]:
    ax.plot([bx, bx], [y0, y1], color=COLORS["ink"], lw=1.2)

# ---- Lane 3: Kill switch ----
y0, y1 = lanes["kill"]
# desk B thin row (bottom of lane)
rect = plt.Rectangle((xm(0), y0 + 1), xm(63) - xm(0), 4,
                     facecolor=COLORS["blue_lt"], edgecolor=COLORS["blue"], lw=0.8)
ax.add_patch(rect)
ax.text((xm(0) + xm(63)) / 2, y0 + 3, "desk B: trading (uninterrupted)", ha="center",
        va="center", fontsize=6.5, color=COLORS["blue"], style="italic")
# PAUSE_INTENTS block desk A
rect = plt.Rectangle((trip_x, y0 + 8), b_rec - trip_x, y1 - y0 - 9,
                     facecolor=COLORS["ink"], edgecolor=COLORS["ink"], lw=1)
ax.add_patch(rect)
ax.text((trip_x + b_rec) / 2, (y0 + 8 + y1) / 2, "PAUSE_INTENTS\nscope=(tenant, desk-a)",
        ha="center", va="center", fontsize=7.5, family=MONO, color="white", weight="bold")
ax.text(xm(0) + 1, y1 - 2, "idle", ha="left", va="center", fontsize=7,
        color=COLORS["gray"], style="italic")
# FULL_STOP drill marker: orange tick through the kill lane, wrapped label below
drill_x = 88.0
ax.plot([drill_x, drill_x], [y0 + 1, y1], color=COLORS["orange"], lw=1.6)
ax.text(drill_x, y0 - 3.2,
        "FULL_STOP drill (tests 7\u20138):\ntwo-admin engage \u2192\nsingle-admin lift refused \u2192\ntwo-admin lift",
        ha="center", va="top", fontsize=6.5, color=COLORS["orange"],
        bbox=dict(boxstyle="round,pad=0.3", fc="white", ec=COLORS["orange"]))

# ---- Lane 4: Ledger ----
y0, y1 = lanes["ledger"]
rows = [
    ("pre-crash", xm(2), b_norm, "submitted \u2192 filled", "green_lt", "green"),
    ("pre-crash", xm(6), b_norm, "submitted \u2192 filled", "green_lt", "green"),
    ("pre-crash", xm(10), b_norm, "submitted \u2192 filled", "green_lt", "green"),
    ("rejecting", b_norm + 1, b_rej - 1, "submitted \u2192 rejected", "amber_lt", "amber"),
    ("silent", b_rej + 1, b_rec - 1,
     "submitted \u2192 timeout (reconcile_error) \u2192 abandoned", "red_lt", "red"),
]
for i, (grp, xa, xb, lbl, face, edge) in enumerate(rows):
    yy = y0 + 3 + (len(rows) - 1 - i) * 3.8
    rect = plt.Rectangle((xa, yy - 2.4), xb - xa, 4.8,
                         facecolor=COLORS[face], edgecolor=COLORS[edge], lw=1.2)
    ax.add_patch(rect)
    ax.text(xa + 1.5, yy, lbl, ha="left", va="center", fontsize=6.5, family=MONO,
            color=COLORS["ink"])
ax.text(75, 31, "no row ever claims filled\nwithout broker truth", ha="center",
        va="center", fontsize=7, style="italic", color=COLORS["green"],
        bbox=dict(boxstyle="round,pad=0.3", fc=COLORS["green_lt"], ec=COLORS["green"]))

save(fig, "ch22")
print("ch22 ok")
