import sys
sys.path.insert(0, "/home/hatch/workspace/book-rebuild/figures")
from _style import *

# ---------- FIG-A1: three-layer protocol stack ----------
fig, ax = new_fig(10, 8)
title(ax, "Figure A.1 \u2014 The A2A 1.0 Protocol Stack", fs=12)

layers = [
    ("Protocol bindings", "JSON-RPC (PascalCase methods) \u00b7 gRPC \u00b7 HTTP+JSON REST",
     62, "amber_lt", "amber"),
    ("Abstract operations", "Send Message \u00b7 Stream Message \u00b7 Get Task \u00b7 List Tasks \u00b7 Cancel Task \u00b7 Get Agent Card",
     38, "blue_lt", "blue"),
    ("Canonical data model (proto)", "Task \u00b7 Message \u00b7 AgentCard \u00b7 Part \u00b7 Artifact \u00b7 Extension",
     14, "green_lt", "green"),
]
for name, body, y, face, edge in layers:
    box(ax, 8, y, 84, 18, f"{name}\n{body}", face=face, edge=edge, fs=9, mono=False)
    ax.text(10, y + 16.5, name, ha="left", va="top", fontsize=8, weight="bold",
            color=COLORS["ink"])

ax.text(50, 8, "The validator in this appendix checks the bottom layer.\n"
                "Bindings are transport; semantics live in the model.",
        ha="center", va="top", fontsize=8.5, style="italic", color=COLORS["ink"],
        bbox=dict(boxstyle="round,pad=0.5", fc=COLORS["gray_lt"], ec=COLORS["gray"]))
save(fig, "app-a-1")
print("app-a-1 ok")
