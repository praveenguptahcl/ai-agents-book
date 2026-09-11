"""Ch6 — Tenant isolation: one process, two tenants, zero leakage.
Three lanes (harbor / shared process / beacon); session-token boxes
feed a require_tenant gate; the gate fans out to three partitioned
stores (split blue/orange, walled) plus submit_as -> Action Executor.
Red dashed defeated attacks end in bold X STOP markers."""
import sys
sys.path.insert(0, "/home/hatch/workspace/book-rebuild/figures")
from _style import *
from matplotlib.patches import Rectangle

fig, ax = new_fig(10, 7.0)
title(ax, "Tenant Isolation: One Process, Two Tenants, Zero Leakage",
      y=98.0, fs=18)


def lane(y0, h, face, label, lcolor):
    box(ax, 2, y0, 96, h, "", face=face, edge="gray_mid", lw=1.0)
    ax.text(4, y0 + h - 1.5, label, ha="left", va="top", fontsize=12.5,
            weight="bold", color=COLORS[lcolor])


lane(80, 14, "blue_lt", "Tenant harbor (momentum desk)", "blue")
lane(56, 22, "gray_lt", "Shared agent process (untrusted by both)", "gray")
lane(32, 20, "orange_lt", "Tenant beacon (dividend desk)", "orange")


def token(x, y):
    box(ax, x, y, 28, 9, "", face="paper", edge="ink", lw=1.6)
    ax.text(x + 14, y + 6.1, "Session token", ha="center", va="center",
            fontsize=11, family=MONO, weight="bold")
    ax.text(x + 14, y + 2.6, "HMAC-signed: tenant_id, scopes, expiry",
            ha="center", va="center", fontsize=8, family=MONO,
            color=COLORS["gray"])


token(13, 80.8)   # harbor session token
token(13, 34.0)   # beacon session token

# --- require_tenant gate in the shared lane ---
box(ax, 42, 60, 26, 12, "", face="paper", edge="ink", lw=2.0)
ax.text(55, 67.6, "require_tenant", ha="center", va="center", fontsize=12,
        family=MONO, weight="bold")
ax.text(55, 62.8, "verify signature + expiry +\nrevocation + scope — on EVERY call",
        ha="center", va="center", fontsize=9, linespacing=1.35)

# solid arrows: each tenant token -> the gate
arrow(ax, 41, 85.3, 47, 72, lw=2.2)
arrow(ax, 41, 38.5, 47, 61, lw=2.2)


# --- three partitioned stores: split halves, bold wall, no cross reads ---
def store(y, label):
    ax.add_patch(Rectangle((70, y), 13.5, 10, facecolor=COLORS["blue_lt"],
                           edgecolor=COLORS["blue"], lw=1.4))
    ax.add_patch(Rectangle((83.5, y), 13.5, 10, facecolor=COLORS["orange_lt"],
                           edgecolor=COLORS["orange"], lw=1.4))
    ax.plot([83.5, 83.5], [y, y + 10], color=COLORS["ink"], lw=3.0)
    ax.text(83.5, y + 12, label, ha="center", va="bottom", fontsize=10.5,
            weight="bold")


store(79, "Namespace (tenant_id, key)")
store(62, "Write-ahead ledger (tenant column)")
store(42, "Audit log (partitioned read)")
ax.text(83.5, 33, "no cross-partition reads", ha="center", va="center",
        fontsize=10, style="italic", color=COLORS["gray"])

# fan-out from the gate to the three stores
arrow(ax, 68, 66, 70, 84, lw=1.8)
arrow(ax, 68, 66, 70, 67, lw=1.8)
arrow(ax, 68, 66, 70, 47, lw=1.8)

# --- fourth arrow: submit_as -> Action Executor ---
box(ax, 42, 12, 28, 10, "", face="paper", edge="ink", lw=1.8)
ax.text(56, 17, "submit_as →\nAction Executor (Ch 10)", ha="center",
        va="center", fontsize=10.5, family=MONO, linespacing=1.4)
arrow(ax, 55, 60, 55, 22, lw=1.8)
ax.text(57.5, 39, "order.tenant_id ==\nsession.tenant_id\nelse TenantMismatch",
        ha="left", va="center", fontsize=9, family=MONO, color=COLORS["gray"],
        linespacing=1.4)


# --- defeated attacks: red dashed, each ends in a bold X STOP ---
def stop2(x, y):
    stop_mark(ax, x, y, s=3.0)
    ax.text(x, y - 3.4, "STOP", ha="center", va="top", fontsize=8.5,
            weight="bold", color=COLORS["red"])


arrow(ax, 8, 70, 39, 66.8, color="red", ls="--", lw=1.8)
stop2(40, 66.5)
ax.text(22, 62.6, "forged token → bad signature", ha="center", va="center",
        fontsize=9, color=COLORS["red"])

arrow(ax, 8, 57.5, 39, 59, color="red", ls="--", lw=1.8)
stop2(40, 59.2)
ax.text(22, 54.6, "edited scopes → bad signature", ha="center", va="center",
        fontsize=9, color=COLORS["red"])

arrow(ax, 28, 17, 38.5, 17, color="red", ls="--", lw=1.8)
stop2(39.5, 17)
ax.text(24, 21.8, "harbor session + beacon order\n→ TenantMismatch",
        ha="center", va="center", fontsize=9, color=COLORS["red"],
        linespacing=1.35)

caption(ax, "The process is shared; the authority is not. "
            "Every arrow into shared state passes the gate.", fs=12.5)

save(fig, "ch06")
print("ch06 done")
