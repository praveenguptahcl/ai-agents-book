"""Figure 12.1 — Injection Defense Pipeline (sequence diagram)."""
import sys
sys.path.insert(0, "/home/hatch/workspace/book-rebuild/figures")
from _style import *

fig, ax = new_fig(12, 8.6)
title(ax, "Prompt Injection Defense Pipeline", y=99)

parts = ["World\n(tools/feeds)", "Provenance\nTagger", "Planner\n(LLM)",
         "Schema Gate", "Intent\nReviewer", "Action Plane"]
px = [8, 25, 42, 59, 76, 93]
for x, p in zip(px, parts):
    box(ax, x - 7, 89.5, 14, 5.5, p, face="gray_lt", edge="ink", fs=7, mono=True)
    ax.plot([x, x], [8, 89.5], color=COLORS["gray_mid"], lw=0.9, ls="--")

def msg(x1, x2, y, text, color="ink", ls="-", lw=1.5, fs=6.4, rad=0.0):
    arrow(ax, x1, y, x2, y, color=color, lw=lw, ls=ls, rad=rad)
    mx = (x1 + x2) / 2
    ax.text(mx, y + 1.6, text, ha="center", va="bottom", fontsize=fs,
            family=MONO, color=COLORS.get(color, color), wrap=True,
            bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none",
                      alpha=0.92), linespacing=1.25)

W, T, P, S, R, A = px

# ---------- top flow: attack path (red), y 78-87 ----------
ax.text(50, 87.5, "attack path", ha="center", va="center", fontsize=7.5,
        weight="bold", color=COLORS["red"])
msg(W, T, 83, 'quote: "SYSTEM OVERRIDE"\nattacker-controlled text',
    color="red", fs=6.4)
msg(T, P, 78, "quarantined, not cleaned\nrandomized delimiter id, sanitized literals",
    color="red", fs=6.2)
msg(P, S, 73, '{"action": "liquidate", ...}\nmodel obeyed the injection',
    color="red", ls="--", fs=6.2)
msg(S, P, 68, 'STOP -- "liquidate" not in vocabulary;\nbroker never contacted',
    color="red", fs=6.2)

# ---------- bottom flow: contained path (green/red), y 50-63 ----------
ax.text(50, 65, "contained path", ha="center", va="center", fontsize=7.5,
        weight="bold", color=COLORS["green"])
msg(W, T, 60.5, "tainted news note", color="green", fs=6.4)
msg(T, P, 55.5, "bannered prompt", color="green", fs=6.4)
msg(P, S, 50.5, "propose_signal short NVDA\ninjection survived the gate",
    color="green", ls="--", fs=6.2)
msg(S, R, 45.5, "valid-shaped proposal", color="green", fs=6.4)
msg(R, P, 40.5, 'STOP -- tripwire: "note to AI assistants"\nin mcp:market_news; failing closed to hold',
    color="red", fs=6.2)

# ---------- notes ----------
ax.text(76, 33, "Unicode-smuggled variant: tripwire misses by design\n"
                "(homoglyphs); the smuggled SHORT dies at the long-only\n"
                "mandate only by coincidence of sides -- a smuggled\n"
                "LONG inside the mandate is the documented residual (see \u00a712.7).",
        ha="center", va="center", fontsize=6.6, color=COLORS["ink"],
        wrap=True, linespacing=1.4,
        bbox=dict(boxstyle="round,pad=0.4", fc=COLORS["amber_lt"],
                  ec=COLORS["amber"], alpha=0.9))
ax.text(50, 20, "Data-plane lie (no imperative): passes all three layers -- "
                "fought with independent verification, not input filters.",
        ha="center", va="center", fontsize=7, style="italic",
        color=COLORS["gray"], wrap=True)

caption(ax, "Three layers, three independent kill conditions. The attack must "
            "defeat all of them; the defense needs only one.",
        y=3, fs=8.4)

save(fig, "ch12")
print("ch12 done")
