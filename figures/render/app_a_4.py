import sys
sys.path.insert(0, "/home/hatch/workspace/book-rebuild/figures")
from _style import *

# ---------- FIG-A4: capability vs authority ----------
fig, ax = new_fig(10, 8)
title(ax, "Figure A.4 \u2014 Capability vs Authority", fs=12)

box(ax, 2, 20, 42, 60,
    "The card claims (capability)\n\n\u2022 skill list\n\u2022 declared schemes\n\u2022 signatures",
    face="blue_lt", edge="blue", fs=10)
box(ax, 56, 20, 42, 60,
    "Your side decides (authority)\n\n\u2022 contract validation\n\u2022 verified credentials\n\u2022 output review\n\u2022 human judgment on the counterparty",
    face="green_lt", edge="green", fs=10)

# thick vertical boundary line
ax.plot([50, 50], [16, 84], color=COLORS["ink"], lw=5)
ax.text(50, 86, "the boundary this appendix patrols", ha="center", va="bottom",
        fontsize=8, weight="bold", color=COLORS["ink"],
        bbox=dict(boxstyle="round,pad=0.4", fc="white", ec=COLORS["ink"]))

# thin crossing arrow: validated shape, not trust
ax.annotate("", xy=(56, 44), xytext=(44, 44),
            arrowprops=dict(arrowstyle="-|>", color=COLORS["gray"], lw=1.6,
                            mutation_scale=12, shrinkA=1, shrinkB=3))
ax.text(50, 47, "validated shape, not trust", ha="center", va="bottom",
        fontsize=7.5, style="italic", color=COLORS["gray"],
        bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="none", alpha=0.9))

ax.text(50, 8, "The card is marketing until your side decides otherwise.",
        ha="center", va="center", fontsize=8.5, style="italic", color=COLORS["gray"])

save(fig, "app-a-4")
print("app-a-4 ok")
