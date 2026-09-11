"""Ch7 — Stateless MCP exchange (modern era). Three lifelines
(AlphaForge host / MCP client / market-data server); each request
arrow carries an accent-colored _meta chip; responses dashed gray;
Pydantic-validation annotation between messages 2 and 3; no session
box anywhere; closing note: each request carries its own _meta."""
import sys
sys.path.insert(0, "/home/hatch/workspace/book-rebuild/figures")
from _style import *

fig, ax = new_fig(10, 7.2)
title(ax, "Stateless MCP exchange (modern era)", fs=17, y=98.6)

# --- lifelines ---
for x, name in [(19, "AlphaForge host"), (50, "MCP client"),
                (81, "market-data server")]:
    box(ax, x - 13, 88, 26, 6, name, face="paper", edge="ink", fs=12,
        lw=1.6)
    ax.plot([x, x], [17, 87], color=COLORS["gray_mid"], lw=1.2, ls="--")


def meta_chip(cx, y, h, text, fs=8.5):
    box(ax, cx - 13, y, 26, h, text, face="purple_lt", edge="purple",
        fs=fs, mono=True, lw=1.2)


def req(y, label, chip_text=None, chip_fs=8.5, chip_h=6):
    for (x1, x2) in [(19, 50), (50, 81)]:
        arrow(ax, x1, y, x2, y, color="ink", lw=1.8)
        cx = (x1 + x2) / 2
        ax.text(cx, y + 2.2, label, ha="center", va="bottom",
                fontsize=11, family=MONO)
        if chip_text:
            meta_chip(cx, y - 5.5 - chip_h, chip_h, chip_text, fs=chip_fs)


def resp(y, label, label_cx=50, fs=8.5):
    # return path drawn as one continuous dashed line across both hops
    arrow(ax, 81, y, 50, y, color="gray", ls="--", lw=1.5)
    arrow(ax, 50, y, 19, y, color="gray", ls="--", lw=1.5)
    ax.text(label_cx, y - 2.2, label, ha="center", va="top",
            fontsize=fs, family=MONO, color=COLORS["gray"],
            linespacing=1.4,
            bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="none",
                      alpha=0.92))


# --- Message 1: server/discover ---
req(83, "server/discover",
    "_meta\nprotocolVersion · clientInfo ·\nclientCapabilities",
    chip_fs=8, chip_h=6)
resp(70, "resultType: complete · supportedVersions\n"
         "capabilities · serverInfo", fs=8)

# --- Message 2: tools/list ---
req(60, "tools/list", "_meta", chip_fs=9, chip_h=6)
resp(47.5, "tool catalog", fs=9)

# --- annotation: validate against the local contract ---
box(ax, 18, 36.25, 64, 6.5, "", face="amber_lt", edge="amber", lw=1.4)
ax.text(50, 39.5, "client validates listing against local Pydantic contract —\n"
                  "refuse on mismatch, no bytes sent",
        ha="center", va="center", fontsize=10, linespacing=1.4)

# --- Message 3: tools/call get_quote ---
req(30.8, "tools/call get_quote", "_meta + arguments",
    chip_fs=8.5, chip_h=5.5)
resp(21, "content: quote · provenance: SYNTHETIC", label_cx=65.5, fs=9)

# --- closing note: no handshake, no session ---
box(ax, 20, 11, 60, 5.5, "", face="gray_lt", edge="gray_mid", lw=1.0)
ax.text(50, 13.75, "each request carries its own _meta — there is no handshake.",
        ha="center", va="center", fontsize=10.5, style="italic",
        color=COLORS["gray"])

caption(ax, "No sessions, no handshakes — every request is self-describing.",
        fs=12.5)

save(fig, "ch07")
print("ch07 done")
