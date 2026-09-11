import sys
sys.path.insert(0, "/home/hatch/workspace/book-rebuild/figures")
from _style import *

# ---------- FIG-A3: auth flowchart ----------
fig, ax = new_fig(8, 10)
title(ax, "Figure A.3 \u2014 The Auth Decision (validate_request_auth)", fs=11)

# diamonds down the middle (x 6..46), terminal column on the right (x 54..98)
d1y, d2y, d3y, d4y = 80, 60, 40, 20
diamond(ax, 26, d1y, 40, 14, "Card declares\nschemes?", face="blue_lt", edge="blue")
diamond(ax, 26, d2y, 40, 14, "Credential\npresented?", face="blue_lt", edge="blue")
diamond(ax, 26, d3y, 40, 14, "Scheme\ndeclared?", face="blue_lt", edge="blue")
diamond(ax, 26, d4y, 40, 14, "Verified?", face="blue_lt", edge="blue")

# No from diamond 1 -> warning
arrow(ax, 46, d1y, 54, d1y, color="amber", lw=1.6)
box(ax, 54, d1y - 6, 42, 12,
    "open agent:\ntreat every response as untrusted", face="amber_lt", edge="amber", fs=7)
ax.text(75, d1y + 2.6, "no", ha="center", va="bottom", fontsize=7.5, weight="bold",
        color=COLORS["amber"])
ax.text(26, d1y + 8, "yes", ha="center", va="bottom", fontsize=7.5, weight="bold",
        color=COLORS["ink"])
arrow(ax, 26, d1y - 7, 26, d2y + 7, color="ink", lw=1.6)

# diamond 2 -> reject auth.missing_credential
ax.text(46.5, d2y, "no \u2192", ha="left", va="center", fontsize=7.5, weight="bold",
        color=COLORS["red"])
arrow(ax, 46, d2y, 54, d2y, color="red", lw=1.6)
box(ax, 54, d2y - 6, 42, 12, "REJECT\nauth.missing_credential", face="red_lt",
    edge="red", fs=7.5, mono=True)
arrow(ax, 26, d2y - 7, 26, d3y + 7, color="ink", lw=1.6)
ax.text(26, d2y - 8, "yes", ha="center", va="top", fontsize=7.5, weight="bold",
        color=COLORS["ink"])

# diamond 3 -> reject auth.undeclared_scheme
ax.text(46.5, d3y, "no \u2192", ha="left", va="center", fontsize=7.5, weight="bold",
        color=COLORS["red"])
arrow(ax, 46, d3y, 54, d3y, color="red", lw=1.6)
box(ax, 54, d3y - 6, 42, 12, "REJECT\nauth.undeclared_scheme", face="red_lt",
    edge="red", fs=7.5, mono=True)
arrow(ax, 26, d3y - 7, 26, d4y + 7, color="ink", lw=1.6)
ax.text(26, d3y - 8, "yes", ha="center", va="top", fontsize=7.5, weight="bold",
        color=COLORS["ink"])

# diamond 4: no -> reject auth.unverified_credential (highlighted)
ax.text(46.5, d4y, "no \u2192", ha="left", va="center", fontsize=7.5, weight="bold",
        color=COLORS["red"])
arrow(ax, 46, d4y, 54, d4y, color="red", lw=1.6)
box(ax, 54, d4y - 8, 42, 16, "REJECT\nauth.unverified_credential\npresented \u2260 verified",
    face="red_lt", edge="red", fs=7.5, mono=True, lw=2.2)
arrow(ax, 26, d4y - 7, 26, 6, color="green", lw=2.0)
ax.text(26, d4y - 8, "yes", ha="center", va="top", fontsize=7.5, weight="bold",
        color=COLORS["green"])
box(ax, 8, 2, 36, 9, "ACCEPT", face="green_lt", edge="green", fs=10)

save(fig, "app-a-3")
print("app-a-3 ok")
