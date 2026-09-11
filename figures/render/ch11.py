"""Figure 11.1 — Kill Switch Architecture (full 12x8, with invariants side panel)."""
import sys
sys.path.insert(0, "/home/hatch/workspace/book-rebuild/figures")
from _style import *

fig, ax = new_fig(12, 8)
title(ax, "Kill Switch Architecture", y=97.5)

def b(x, y, w, h, text, face="paper", edge="ink", fs=7, lw=1.4):
    return box(ax, x, y, w, h, text, face=face, edge=edge, fs=fs, mono=True,
               lw=lw)

# ---------------- boxes ----------------
b(2, 74, 16, 11, "Supervisor\nProcess", face="blue_lt", edge="blue")
b(24, 58, 20, 24, "KillSwitch\nlevels\nverified-session\nregistry\naudit log",
  face="red_lt", edge="red", lw=2.0)
b(2, 44, 16, 16, "ActionExecutor\nearly gate +\nguarded broker",
  face="paper", edge="ink")
b(48, 74, 18, 10, "RiskMonitor\ndrawdown ->\nauto-engage", face="amber_lt",
  edge="amber")
b(48, 38, 18, 16, "Paper Broker\ncancel / flatten\nrevoke effects",
  face="paper", edge="ink")
b(2, 18, 16, 14, "Operator\nConsole\ntwo-person engage\nverified sessions",
  face="purple_lt", edge="purple")
b(48, 18, 18, 14, "Audit Log\nappend-only", face="gray_lt", edge="gray")
b(47, 66, 19, 8, "scoped kill\n(tenant, harbor)", face="purple_lt",
  edge="purple", fs=6.5)

def note(x, y, text, color="gray", fs=5.8, ha="center"):
    ax.text(x, y, text, ha=ha, va="center", fontsize=fs, family=MONO,
            color=COLORS[color], wrap=True, linespacing=1.3,
            bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none",
                      alpha=0.92))

# 1. heartbeat: Supervisor -> KillSwitch (green)
arrow(ax, 18, 80, 24, 76, color="green", lw=1.8, label="beat()", fs=6.5)
note(21, 71.5, "freshness 30s;\nsilence => fail closed", "green")

# 2/3/4. gate bus: ActionExecutor bottom -> three lanes up into KillSwitch
ax.plot([10, 10], [40, 44], color=COLORS["ink"], lw=1.2)
ax.plot([10, 39], [40, 40], color=COLORS["ink"], lw=1.2)
arrow(ax, 30, 40, 30, 58, color="red", lw=1.5)
arrow(ax, 34.5, 40, 34.5, 58, color="red", lw=1.5)
arrow(ax, 39, 40, 39, 58, color="gray", lw=1.5)
note(30, 42.5, "submit", "red", fs=5.5)
note(34.5, 45.5, "cancel", "red", fs=5.5)
note(39, 42.5, "reconcile", "gray", fs=5.5)

# 5. send-time guard: ActionExecutor -> Paper Broker, routed around the bus (red)
ax.plot([12, 12], [28, 44], color=COLORS["red"], lw=1.5)
arrow(ax, 12, 28, 47, 28, color="red", lw=1.5,
      label='guarded(broker): check("submit") AT SEND TIME\ncloses the TOCTOU gap',
      fs=5.8, label_pos=0.5)
ax.plot([47, 47], [28, 38], color=COLORS["red"], lw=1.5)

# 6. RiskMonitor -> KillSwitch (red)
arrow(ax, 48, 79, 44, 73, color="red", lw=1.8)
note(48, 86.5, "drawdown >= 3% => engage FLATTEN_HALT", "red")
note(30, 91.5, "verified risk-monitor session;\nre-arm needs human admin",
     "red")

# 7. Operator Console -> KillSwitch (red)
arrow(ax, 18, 32, 28, 58, color="red", lw=1.6, rad=0.2)
note(30, 37.5, "engage L1-L3: 1 session;\nL4: 2 sessions\n(raw strings rejected)",
     "red")

# 8. KillSwitch -> Paper Broker effects (red)
arrow(ax, 44, 62, 52, 54, color="red", lw=1.8, rad=-0.2,
      label="cancel_open_fn / flatten_fn /\nrevoke_keys_fn (once per scope,effect)\neffects audited; failure arms anyway",
      fs=5.8, label_pos=0.45)

# 9. KillSwitch -> Audit Log (gray), routed under Paper Broker
ax.plot([34, 34], [26, 58], color=COLORS["gray"], lw=1.4)
arrow(ax, 34, 26, 48, 26, color="gray", lw=1.4,
      label="append engage/disarm + reasons", fs=6.0, label_pos=0.5)
note(41, 21.5, "-> Evidence Ledger (Ch 14) /\nCompliance (Ch 19)", "gray")

# 10. scoped-kill lane -> ActionExecutor (purple)
ax.plot([66, 68.5], [70, 70], color=COLORS["purple"], lw=1.4)
ax.plot([68.5, 68.5], [31.5, 70], color=COLORS["purple"], lw=1.4)
ax.plot([2, 68.5], [31.5, 31.5], color=COLORS["purple"], lw=1.4)
arrow(ax, 2, 31.5, 2, 50, color="purple", lw=1.4)
note(56, 33.8, "governs only scope-matched actions", "purple")

# ---------------- gate legend (bottom) ----------------
def leg(y, method, rest, mcolor):
    ax.text(3, y, method, ha="left", va="center", fontsize=6, family=MONO,
            color=COLORS[mcolor], weight="bold")
    ax.text(3 + len(method) * 0.42 + 0.8, y, rest, ha="left", va="center",
            fontsize=6, family=MONO, color=COLORS["gray"])

leg(14.5, 'check("submit")',
    "-- BEFORE any ledger write; refused => HaltedError / HeartbeatStale, no phantom state",
    "red")
leg(11.5, 'check("cancel")', "-- allowed at levels 1-3; refused at FULL_STOP",
    "red")
leg(8.5, 'check("reconcile")',
    "-- always allowed: read-only, freezing != resolving", "gray")

# ---------------- invariants side panel ----------------
ax.plot([70, 70], [6, 94], color=COLORS["gray_mid"], lw=0.8, ls="--")
ax.text(84.5, 91, "Invariants", ha="center", va="center", fontsize=10,
        weight="bold", color=COLORS["ink"])
invs = [
    "1. The gate runs before any state mutation.",
    "2. The gate re-runs at send time via the guarded wrapper.",
    "3. The switch boots refusing submits until the first beat.",
    "4. Reconcile and reads are never gated.",
    "5. Re-arm requires strictly greater authority than engagement plus a written reason -- except FULL_STOP, which always needs two distinct admins.",
    "6. A failed side effect is audited, never a reason to stay unarmed.",
    "7. There is no break-glass path around the authority check.",
    "8. Operator identities are verified sessions, never raw strings.",
]
y = 84.5
for inv in invs:
    ax.text(72.5, y, inv, ha="left", va="top", fontsize=6.8, color=COLORS["ink"],
            wrap=True, linespacing=1.45)
    nlines = max(1, len(inv) // 52 + 1)
    y -= nlines * 4.4 + 1.6

caption(ax, "The kill switch is a gate, not a suggestion: every action passes "
            "check() before state mutation and again at send time.",
        y=2.5, fs=8.2)

save(fig, "ch11")
print("ch11 done")
