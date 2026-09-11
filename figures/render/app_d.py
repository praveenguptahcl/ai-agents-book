"""Figure D.1 - The Failure-Semantics Decision Tree (rewrite: single spine)."""
import sys
sys.path.insert(0, "/home/hatch/workspace/book-rebuild/figures")
from _style import *
import textwrap

fig, ax = new_fig(10, 11.8)
ax.set_xlim(0, 100)
ax.set_ylim(0, 118)
title(ax, "Figure D.1 \u2014 The Failure-Semantics Decision Tree", y=114.5)

# root
box(ax, 30, 107, 40, 5, "Something went wrong at the execution boundary.",
    face="gray_lt", edge="ink", fs=7.5)
arrow(ax, 50, 107, 15, 102.5, color="ink", lw=1.6)

# single spine of 7 diamonds (diamond takes CENTER coords)
DXC, DW, DH = 15, 22, 9
dys = [98, 86, 74, 62, 50, 38, 26]
qs = [
    "1. Did you get\nan answer?",
    "2. Did the answer claim\nless than the request?",
    "3. Do two sources\ndisagree?",
    "4. Outcome unknown\nafter retry budget?",
    "5. Claim fails independent\nverification?",
    "6. Did authority\ndie mid-run?",
    "7. Behavior shifted with\nno system change?",
]
for dy, q in zip(dys, qs):
    diamond(ax, DXC, dy, DW, DH, q, fs=7.5)

# spine flow arrows between diamonds
flows = [("yes", 0), ("no", 1), ("no", 2), ("no", 3), ("no", 4), ("no", 5)]
for lbl, i in flows:
    y_top = dys[i] - DH / 2
    y_bot = dys[i + 1] + DH / 2
    arrow(ax, DXC, y_top, DXC, y_bot, color="ink", lw=1.6)
    ax.text(DXC + 2.5, (y_top + y_bot) / 2, lbl, ha="left", va="center",
            fontsize=7, weight="bold")

# terminal boxes (x 30-62), wrapped detect/pattern
TX, TW, TH = 30, 32, 10
terms = [
    # (diamond_idx, branch, title, detect, pattern, ch, face, edge)
    (0, "no", "TIMEOUT",
     "response never arrived within the deadline",
     "same idempotency key, exponential backoff, then hold timeout for reconcile",
     "Ch 10", "amber_lt", "amber"),
    (1, "yes", "PARTIAL COMPLETION",
     "terminal response with filled quantity < requested",
     "record partial as terminal; the remainder is a new proposal with a new key",
     "Ch 10", "blue_lt", "blue"),
    (3, "yes", "AMBIGUOUS COMMIT",
     "timeout row, no distinguishing broker signal",
     "never guess; reconcile by key; run the 2:14am OUTCOME-UNKNOWN playbook",
     "Ch 14", "red_lt", "red"),
    (4, "yes", "TOOL LIES",
     "cross-plane disagreement reconciliation cannot explain",
     "terminal records only from independent sources; quarantine the tool; emit the discrepancy as evidence",
     "Ch 6", "purple_lt", "purple"),
    (5, "yes", "AUTH EXPIRY MID-RUN",
     "401/403 on calls that previously succeeded",
     "non-retryable; stop acting, re-verify the tenant session, resume from the ledger",
     "Ch 6", "orange_lt", "orange"),
    (6, "yes", "MODEL DRIFT",
     "eval regression on the frozen golden set",
     "pin the model, gate changes through evals, shadow before submit, roll back on detection",
     "Ch 15", "gray_lt", "gray"),
]
for di, br, ttitle, detect, pattern, ch, face, edge in terms:
    dy = dys[di]
    ty = dy - TH / 2
    arrow(ax, DXC + DW / 2, dy, TX, dy, color=edge, lw=1.8)
    ax.text(DXC + DW / 2 + 2.2, dy + 1.6, br, ha="left", va="bottom",
            fontsize=7, weight="bold", color=COLORS[edge])
    box(ax, TX, ty, TW, TH, "", face=face, edge=edge, lw=1.5)
    ax.text(TX + TW / 2, ty + TH - 1.8, ttitle, ha="center", va="center",
            fontsize=8, weight="bold")
    ax.text(TX + 1.5, ty + TH - 3.4,
            "\n".join(textwrap.wrap("Detect: " + detect, 40)),
            ha="left", va="top", fontsize=5.8, style="italic")
    ax.text(TX + 1.5, ty + 3.6,
            "\n".join(textwrap.wrap("Pattern: " + pattern, 40)),
            ha="left", va="top", fontsize=5.8)
    ax.text(TX + TW - 1, ty + TH - 1.0, ch, ha="right", va="top",
            fontsize=5.5, style="italic", color=COLORS["gray"])

# 3b sub-diamond (nested right of diamond 3)
d3y = dys[2]
diamond(ax, 42, d3y, 16, 8, "3b. Changed\nout-of-band?", fs=6.5, edge="orange")
arrow(ax, DXC + DW / 2, d3y, 34, d3y, color="orange", lw=1.8)
ax.text(DXC + DW / 2 + 2.2, d3y + 1.6, "yes", ha="left", va="bottom",
        fontsize=7, weight="bold", color=COLORS["orange"])
# 3b yes -> HUMAN INTERVENTION (right column, upper)
HIY = d3y - 5
box(ax, 66, HIY, 32, 10, "", face="orange_lt", edge="orange", lw=1.5)
ax.text(82, HIY + 8.2, "HUMAN\nINTERVENTION", ha="center", va="center",
        fontsize=7.5, weight="bold")
ax.text(67.5, HIY + 6.2,
        "\n".join(textwrap.wrap("Detect: ledger-vs-world mismatch; broker audit trail names an operator session", 36)),
        ha="left", va="top", fontsize=5.5, style="italic")
ax.text(67.5, HIY + 3.0,
        "\n".join(textwrap.wrap("Pattern: adopt broker truth; the kill-switch gate is the human's instrument", 36)),
        ha="left", va="top", fontsize=5.5)
ax.text(97, HIY + 9.0, "Ch 11", ha="right", va="top",
        fontsize=5.5, style="italic", color=COLORS["gray"])
arrow(ax, 50, d3y, 66, d3y, color="orange", lw=1.8)
ax.text(56, d3y + 1.6, "yes", ha="left", va="bottom",
        fontsize=7, weight="bold", color=COLORS["orange"])
# 3b no -> STALE READ (right column, lower)
SRY = d3y - 17
box(ax, 66, SRY, 32, 10, "", face="blue_lt", edge="blue", lw=1.5)
ax.text(82, SRY + 8.2, "STALE READ", ha="center", va="center",
        fontsize=7.5, weight="bold")
ax.text(67.5, SRY + 6.2,
        "\n".join(textwrap.wrap("Detect: two reads of the same entity return different states", 36)),
        ha="left", va="top", fontsize=5.5, style="italic")
ax.text(67.5, SRY + 3.0,
        "\n".join(textwrap.wrap("Pattern: authoritative source wins; caches adopt, never argue; stamp reads with versions", 36)),
        ha="left", va="top", fontsize=5.5)
ax.text(97, SRY + 9.0, "Ch 10", ha="right", va="top",
        fontsize=5.5, style="italic", color=COLORS["gray"])
ax.annotate("", xy=(82, SRY + 10), xytext=(42, d3y - 4),
            arrowprops=dict(arrowstyle="-|>", color=COLORS["orange"], lw=1.6,
                            mutation_scale=12, shrinkA=1, shrinkB=2,
                            connectionstyle="arc3,rad=-0.2"))
ax.text(47, d3y - 6.2, "no", ha="left", va="center",
        fontsize=7, weight="bold", color=COLORS["orange"])

# diamond 7 no -> UNCLASSIFIED (dashed), loops back to decision 1
d7y = dys[6]
box(ax, TX, 7, TW, 10, "", face="paper", edge="gray", lw=1.4, ls="--")
ax.text(TX + TW / 2, 14.4, "UNCLASSIFIED \u2014 go back to 1", ha="center",
        va="center", fontsize=8, weight="bold")
ax.text(TX + TW / 2, 11.8, "Detect: you missed an entry", ha="center",
        va="center", fontsize=6, style="italic")
ax.text(TX + TW / 2, 9.4, "\u201cI don\u2019t know what happened\u201d is never terminal",
        ha="center", va="center", fontsize=5.8)
arrow(ax, DXC, d7y - DH / 2, DXC, 17, color="ink", lw=1.6)
arrow(ax, DXC, 17, TX, 12, color="ink", lw=1.6)
ax.text(DXC + 2.5, 15.5, "no", ha="left", va="center", fontsize=7, weight="bold")
# loop-back to decision 1 via the clear left margin (orthogonal path)
ax.plot([TX, 2], [12, 12], color=COLORS["ink"], lw=1.6)
ax.plot([2, 2], [12, dys[0]], color=COLORS["ink"], lw=1.6)
arrow(ax, 2, dys[0], DXC - DW / 2 + 1.5, dys[0], color="ink", lw=1.6)
ax.text(17, 13.8, "\u21a9 go back to 1", ha="center", va="bottom", fontsize=7,
        style="italic", color=COLORS["gray"])

# footer thesis
box(ax, 4, 0.5, 92, 4, "Timeouts may retry; ambiguity may never be guessed at. "
    "The broker is the source of truth; the ledger is a cache.",
    face="ink", edge="ink", fs=7)
for t in ax.texts:
    if t.get_text().startswith("Timeouts may"):
        t.set_color("white")
        t.set_style("italic")

save(fig, "app-d")
print("app-d ok")
