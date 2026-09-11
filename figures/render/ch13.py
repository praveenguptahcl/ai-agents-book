"""Figure 13.1 — The two boundaries: SSRF (A) and the sandbox cell (B)."""
import sys
sys.path.insert(0, "/home/hatch/workspace/book-rebuild/figures")
from _style import *
from matplotlib.patches import Ellipse

fig, ax = new_fig(13, 7.4)
title(ax, "The two boundaries", y=97.5)
ax.plot([50, 50], [8, 92], color=COLORS["gray_mid"], lw=0.8, ls="--")

# ================= Panel A: SSRF =================
ax.text(25, 92, "A. SSRF against the market-data tool", ha="center",
        va="center", fontsize=10, weight="bold", color=COLORS["ink"])
box(ax, 2, 68, 20, 20, "quote tool\nallowlist:\napi.polygon.io\napi.alphavantage.co",
    face="blue_lt", edge="blue", fs=7, mono=True, lw=1.6)

# gate icon (tall enough to intercept all four paths)
box(ax, 30, 36, 14, 28, "GATE\naddress,\nnot name", face="amber_lt",
    edge="amber", fs=6.5, mono=True, lw=1.8)

attacks = [
    (62, "169.254.169.254\ndirect fetch",
     "resolved-address check:\nlink-local refused"),
    (54, "quotes.vendor.example\nDNS rebinding -> 10.0.0.5",
     "resolve-then-check on EVERY request:\nthe name is not the address"),
    (46, "allowlisted hop -> 302 ->\nmetadata endpoint",
     "manual per-hop re-gating:\nredirect laundering stopped"),
    (38, "resolve -> connect\nTOCTOU window",
     "named residual: resolved_ips\nfeed connection pinning"),
]
for y, mech, defense in attacks:
    arrow(ax, 1.5, y, 30, y, color="red", lw=1.6)
    ax.text(15.5, y + 2.6, mech, ha="center", va="center", fontsize=6.2,
            family=MONO, color=COLORS["red"], linespacing=1.25,
            bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="white",
                      alpha=1.0))
    ax.text(15.5, y - 2.8, defense, ha="center", va="center", fontsize=5.8,
            style="italic", color=COLORS["green"], linespacing=1.25,
            bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="white",
                      alpha=1.0))
stop_mark(ax, 27.5, 50, s=2.6)

# allowed path: tool -> gate (green)
arrow(ax, 22, 72, 34, 63, color="green", lw=1.6)
ax.text(37, 30.5, "allowed: only allowlisted hosts,\nre-gated on every hop",
        ha="center", va="center", fontsize=6.6, color=COLORS["green"],
        style="italic", linespacing=1.3)

ax.text(25, 12, '"The gate checks the address, not the name -- on every hop."',
        ha="center", va="center", fontsize=8, style="italic",
        color=COLORS["gray"], wrap=True)

# ================= Panel B: sandbox cell =================
ax.text(75, 92, "B. The sandbox cell", ha="center", va="center", fontsize=10,
        weight="bold", color=COLORS["ink"])
box(ax, 52, 30, 44, 52, "", face="paper", edge="ink", lw=1.8)
ax.text(74, 79, "worktree", ha="center", va="center", fontsize=9,
        weight="bold", family=MONO)
box(ax, 65, 62, 18, 12, "research\nagent", face="gray_lt", edge="gray",
    fs=7.5, mono=True)

# two keys on two separate rings (ellipses corrected for data aspect)
for kx, klab, ksub, kdesc in [
        (60, "run_bash", "process cell",
         "argv-only, allowlist,\ntimeout, output cap,\nscrubbed env"),
        (88, "apply_patch", "file cell",
         "propose -> review -> apply;\nno absolute paths, no ..,\nno symlink components")]:
    e = Ellipse((kx, 48), 11, 6.3, facecolor="none",
                edgecolor=COLORS["amber"], linewidth=1.8)
    ax.add_patch(e)
    ax.text(kx, 48, klab, ha="center", va="center", fontsize=6,
            family=MONO, weight="bold", color=COLORS["ink"])
    ax.text(kx, 43.5, ksub, ha="center", va="center", fontsize=5.6,
            style="italic", color=COLORS["gray"])
    ax.text(kx, 55.5, kdesc, ha="center", va="center", fontsize=5.4,
            color=COLORS["ink"], linespacing=1.3)

# allowed effects (green)
arrow(ax, 65, 68, 60, 54, color="green", lw=1.5, rad=0.12)
arrow(ax, 78, 62, 86, 54, color="green", lw=1.5, rad=-0.12)
ax.text(57, 66, "may run listed\ncommands", ha="center", va="center",
        fontsize=5.8, color=COLORS["green"], style="italic", linespacing=1.25)
ax.text(91, 66, "may modify in-tree\nfiles only after\na review verdict",
        ha="center", va="center", fontsize=5.8, color=COLORS["green"],
        style="italic", linespacing=1.25)

# refusals (red X)
refusals = [
    (60, "curl\nnot allowlisted"),
    (71, "patch to\n/etc/cron.d"),
    (82, "symlink out\nof the tree"),
    (91, "unreviewed\npatch"),
]
for rx, rt in refusals:
    stop_mark(ax, rx, 36.5, s=2.4)
    ax.text(rx, 32.5, rt, ha="center", va="center", fontsize=5.8,
            family=MONO, color=COLORS["red"], linespacing=1.25)

ax.text(75, 12, '"Two authorities, two keys. The agent never holds the cell\'s '
                'configuration."',
        ha="center", va="center", fontsize=8, style="italic",
        color=COLORS["gray"], wrap=True)

save(fig, "ch13")
print("ch13 done")
