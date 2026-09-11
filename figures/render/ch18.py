"""Figure 18.1 -- The adapter as a decorator (vertical sequence, 8x10)."""
import sys
sys.path.insert(0, "/home/hatch/workspace/book-rebuild/figures")
from _style import *
from matplotlib.patches import Ellipse

fig, ax = new_fig(8, 10)
title(ax, "Figure 18.1 \u2014 The adapter as a decorator", fs=12)

CX = [7.5, 19.5, 31.5, 43.5, 55.5, 67.5, 79.5, 91.5]
NAMES = ["Framework", "FrameworkAdapter\n.call()", "Registry +\nContract",
         "Session\nverifier", "Approval\ntickets", "Legacy\nfunction",
         "Output\nreviewer", "Evidence\nsink"]
A = CX[1]    # adapter lifeline x
AX = 21.9    # message start/end x, clear of the gate icons

# ---- participant boxes + lifelines ------------------------------------
for cx, name in zip(CX, NAMES):
    box(ax, cx - 5.5, 84, 11, 7, name, face="paper", edge="ink", fs=6.5)
    bottom = 13 if cx == 91.5 else 9
    ax.plot([cx, cx], [bottom, 83.5], color=COLORS["gray_mid"], lw=1.1,
            ls=(0, (4, 3)), zorder=1)


def msg(x1, x2, y, text, color="green", fs=5.8):
    arrow(ax, x1, y, x2, y, color=color, lw=1.7)
    ax.text((x1 + x2) / 2, y + 2.1, text, ha="center", va="bottom",
            fontsize=fs, family=MONO, color=COLORS[color],
            bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none",
                      alpha=0.96), linespacing=1.3)


def refuse(x1, y, text, note, color="red"):
    """Refusal arrow back to the adapter; label below, note to its right."""
    arrow(ax, x1, y, AX, y, color=color, lw=1.7)
    mx = (x1 + AX) / 2
    ax.text(mx, y - 1.8, text, ha="center", va="top",
            fontsize=5.8, family=MONO, color=COLORS[color],
            bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none",
                      alpha=0.96))
    nx = mx + len(text) * 0.31 + 1.8
    ax.text(nx, y - 1.8, note, ha="left", va="top",
            fontsize=5, color=COLORS["gray"], style="italic",
            bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none",
                      alpha=0.96))


def gate(yy, num):
    # circular on screen: x-units are 1.25x narrower than y-units here
    ax.add_patch(Ellipse((A, yy), 4.75, 3.8, facecolor=COLORS["green"],
                         edgecolor=COLORS["ink"], lw=1.2, zorder=6))
    ax.text(A, yy, num, ha="center", va="center", fontsize=7.5,
            weight="bold", color="white", zorder=7)


# 1. framework -> adapter
msg(CX[0], A, 80, 'call(session,\n"dump_positions", raw_args)')
# 2. adapter -> registry (+miss refusal)
msg(AX, CX[2], 77, 'lookup\n("dump_positions")')
gate(77, "1")
refuse(CX[2], 74.5, "UnwrappedToolRefused",
       "the framework never reaches the legacy function")
# 3. adapter -> session verifier (+denial refusal)
msg(AX, CX[3], 66.1, "verify(session, tool)")
gate(66.1, "2")
refuse(CX[3], 63.6, "ScopeDenied", "authority before shape.")
# 4. adapter -> contract (+violation refusal)
msg(AX, CX[2], 55.2, "model_validate\n(raw_args)")
gate(55.2, "3")
refuse(CX[2], 52.7, "ContractViolation",
       "the legacy function never sees unvalidated input.")
# 5. adapter -> approval tickets (+amber pause)
msg(AX, CX[4], 44.3, "consume ticket\n(bound to args digest)")
gate(44.3, "4")
ax.text(58.5, 44.3, "risk: WRITE /\nIRREVERSIBLE", ha="left", va="center",
        fontsize=5, color=COLORS["amber"], weight="bold",
        bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none",
                  alpha=0.96))
refuse(CX[4], 41.8, "ApprovalRequired",
       "a pause, not a failure \u2014 a human may still approve",
       color="amber")
# 6. adapter -> legacy function
msg(AX, CX[5], 33.4, "adapt(bound)\n\u2192 dispatch")
ax.text((AX + CX[5]) / 2, 31.2,
        "exception \u2192 wrapped ToolExecutionError",
        ha="center", fontsize=5, color=COLORS["gray"], style="italic")
# 7. legacy -> output reviewer (+blocked refusal)
msg(CX[5], CX[6], 28.8, "scan rendered\noutput")
gate(28.8, "5")
refuse(CX[6], 26.2, "OutputBlocked", "the planner never sees it.")
# 8. adapter -> evidence sink (every path)
msg(AX, CX[7], 17.8, "EvidenceRecord\n(every path)")
ax.text(55.5, 14.6, "refusals are evidence too.", ha="center",
        fontsize=6.5, weight="bold", color=COLORS["ink"])
ax.text(55.5, 12.2,
        "allowed / refused:unregistered / refused:scope /\n"
        "refused:contract / refused:approval / refused:output",
        ha="center", fontsize=5, family=MONO, color=COLORS["gray"])

ax.text(50, 6.6,
        "gates:  1 registration   \u00b7   2 authority   \u00b7   "
        "3 contract   \u00b7   4 approval   \u00b7   5 output review",
        ha="center", fontsize=6.5, color=COLORS["gray"], style="italic")

# ---- left bracket -------------------------------------------------------
ax.plot([2.6, 2.6], [16, 79], color=COLORS["ink"], lw=1.6)
ax.plot([2.6, 4.2], [79, 79], color=COLORS["ink"], lw=1.6)
ax.plot([2.6, 4.2], [16, 16], color=COLORS["ink"], lw=1.6)
ax.text(1.5, 47.5, "the framework sees a tool;\nthe inside sees a "
                    "trust boundary.",
        ha="center", va="center", rotation=90, fontsize=7.5,
        style="italic", color=COLORS["ink"], linespacing=2.0)

caption(ax,
        "The adapter\u2019s five checks, in order: registration, authority, "
        "contract, approval, output review. Every path \u2014 allowed or "
        "refused \u2014 emits an evidence record.")

save(fig, "ch18")
print("ch18 done")
