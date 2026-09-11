import sys
sys.path.insert(0, "/home/hatch/workspace/book-rebuild/figures")
from _style import *

# ---------- FIG-A2: task state machine ----------
fig, ax = new_fig(12, 8)
title(ax, "Figure A.2 \u2014 The Task Lifecycle, With Teeth", fs=12)

# node layout: active cluster (left/center), terminal (right), unspecified grayed
nodes = {
    "submitted":      (28, 78, 15, 9, "paper", 1.4),
    "working":        (28, 55, 15, 9, "blue_lt", 1.6),
    "input-required": (28, 32, 15, 9, "paper", 1.4),
    "auth-required":  (28, 11, 15, 9, "paper", 1.4),
    "completed":      (76, 78, 15, 9, "green_lt", 2.6),
    "failed":         (76, 58, 15, 9, "red_lt", 2.6),
    "canceled":       (76, 38, 15, 9, "amber_lt", 2.6),
    "rejected":       (76, 18, 15, 9, "gray_lt", 2.6),
    "unspecified":    (6, 55, 13, 9, "gray_lt", 1.0),
}
for name, (x, y, w, h, face, lw) in nodes.items():
    if name == "unspecified":
        p = box(ax, x, y, w, h, name, face=face, edge="gray_mid", fs=7,
                mono=True, lw=lw)
        ax.text(x + w / 2, y + h / 2 - 0.5, "\u2715", ha="center", va="center",
                fontsize=26, color=COLORS["red"], alpha=0.55, weight="bold")
    else:
        box(ax, x, y, w, h, name, face=face, edge="ink", fs=7.5, mono=True, lw=lw)

edges = [
    ("submitted", "working", "ink"),
    ("working", "input-required", "ink"),
    ("working", "auth-required", "ink"),
    ("input-required", "working", "ink"),
    ("auth-required", "working", "ink"),
    ("working", "completed", "green"),
    ("working", "failed", "red"),
    ("working", "canceled", "amber"),
    ("submitted", "rejected", "ink"),
    ("working", "rejected", "ink"),
    ("input-required", "canceled", "ink"),
    ("auth-required", "canceled", "ink"),
]

def center(name):
    x, y, w, h, *_ = nodes[name]
    return x + w / 2, y + h / 2

for a, b, color in edges:
    x1, y1 = center(a); x2, y2 = center(b)
    rad = 0.15 if (a, b) in [("working", "input-required"), ("input-required", "working"),
                              ("working", "auth-required"), ("auth-required", "working")] else 0.0
    arrow(ax, x1, y1, x2, y2, color=color, lw=1.5, rad=rad)

# cluster labels
ax.text(35.5, 92, "active", ha="center", va="center", fontsize=9, weight="bold",
        color=COLORS["blue"])
ax.text(83.5, 92, "terminal \u2014 no outgoing edges", ha="center", va="center",
        fontsize=9, weight="bold", color=COLORS["ink"])

# red dashed struck-through illegal edges
xa, ya = center("completed"); xb, yb = center("working")
ax.annotate("", xy=(xb, yb + 1.5), xytext=(xa, ya - 1.5),
            arrowprops=dict(arrowstyle="-|>", color=COLORS["red"], lw=1.8,
                            ls=(0, (5, 4)), mutation_scale=14, shrinkA=1, shrinkB=3,
                            connectionstyle="arc3,rad=0.35"))
ax.text(55, 74, "resurrection refused", ha="center", va="center", fontsize=6.5,
        style="italic", color=COLORS["red"],
        bbox=dict(boxstyle="round,pad=0.3", fc=COLORS["red_lt"], ec="none"))
stop_mark(ax, 59, 69.5, s=2.0, color="red")

xa, ya = center("submitted"); xb, yb = center("completed")
ax.annotate("", xy=(76, 87), xytext=(43, 87),
            arrowprops=dict(arrowstyle="-|>", color=COLORS["red"], lw=1.8,
                            ls=(0, (5, 4)), mutation_scale=14, shrinkA=1, shrinkB=3,
                            connectionstyle="arc3,rad=-0.15"))
ax.text(59.5, 91, "skip refused", ha="center", va="center", fontsize=6.5,
        style="italic", color=COLORS["red"],
        bbox=dict(boxstyle="round,pad=0.3", fc=COLORS["red_lt"], ec="none"))

caption(ax, "Figure A.2. Terminal states are absorbing. The transition table is the book\u2019s rule.")
save(fig, "app-a-2")
print("app-a-2 ok")
