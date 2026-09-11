"""Figure 9.1 — The Evidence Routing Pipeline."""
import sys
sys.path.insert(0, "/home/hatch/workspace/book-rebuild/figures")
from _style import *

fig, ax = new_fig(13, 7.8)
title(ax, "The Evidence Routing Pipeline", y=97.5)

# ---------- Sources (left, two rows) ----------
sources_r1 = [("strategy", "intent_record"), ("authority layer", "authority_check"),
              ("tool boundary", "tool_call"), ("broker adapter", "broker_response")]
sources_r2 = [("reconcile sweep", "reconcile_event"), ("provider client", "refusal"),
              ("circuit breaker", "kill_switch")]
sx, sw, sgap = 2, 12.2, 1.6
y1, y2, sh = 66, 52.5, 13
src_centers = []
for i, (nm, ev) in enumerate(sources_r1):
    x = sx + i * (sw + sgap)
    box(ax, x, y1, sw, sh, nm, face="gray_lt", edge="gray", fs=7)
    ax.text(x + sw / 2, y1 + 3.0, ev, ha="center", va="center", fontsize=6.4,
            family=MONO, color=COLORS["blue"])
    src_centers.append((x + sw / 2, y1))
for i, (nm, ev) in enumerate(sources_r2):
    x = sx + i * (sw + sgap)
    box(ax, x, y2, sw, sh, nm, face="gray_lt", edge="gray", fs=7)
    ax.text(x + sw / 2, y2 + 3.0, ev, ha="center", va="center", fontsize=6.4,
            family=MONO, color=COLORS["blue"])
    src_centers.append((x + sw / 2, y2))

# ---------- Router gate (center) ----------
rx, ry, rw, rh = 58, 46, 20, 30
box(ax, rx, ry, rw, rh, "", face="paper", edge="ink", lw=2.6)
ax.text(rx + rw / 2, ry + rh - 4,
        "emit(session,\ntype, payload)", ha="center", va="center", fontsize=7.6,
        family=MONO, weight="bold", color=COLORS["ink"])
ax.text(rx + rw / 2, ry + rh / 2 + 2, "taxonomy check", ha="center",
        va="center", fontsize=7, style="italic", color=COLORS["gray"])
ax.text(rx + rw / 2, ry + 6, "tenant from session,\nnever from string",
        ha="center", va="center", fontsize=6.6, color=COLORS["ink"],
        linespacing=1.3)

for (cx_, cy_) in src_centers:
    arrow(ax, cx_ + sw / 2, cy_ + sh / 2, rx, ry + rh / 2, color="blue",
          lw=1.2, rad=0.05)

# ---------- Sinks (right) ----------
kx, kw = 81, 17.5
box(ax, kx, 62, kw, 16,
        "AuditLog\nappend-only, HMAC-chained\ninfinite retention\ntenant-scoped reads (absence)",
        face="blue_lt", edge="blue", fs=6.2, mono=True, lw=1.6)
box(ax, kx, 46, kw, 14,
        "TraceSink\nring buffer, TRACE_TYPES only\nshort retention",
        face="blue_lt", edge="blue", fs=6.2, mono=True, lw=1.6)
box(ax, kx, 30, kw, 14,
        "EvalDataset\nEVAL_TYPES only\nfrozen deepcopy snapshots\nversioned w/ model ckpts",
        face="blue_lt", edge="blue", fs=6.2, mono=True, lw=1.6)
for sy_ in (70, 53, 37):
    arrow(ax, rx + rw, ry + rh / 2, kx, sy_, color="blue", lw=1.4, rad=0.06)

# forbidden direct path: sources -> sinks UNDER the router, red X
arrow(ax, 35, 39, kx, 39, color="gray_mid", lw=1.1, ls="--", rad=0)
stop_mark(ax, 56, 39, s=3.4)
ax.text(56, 35.5, "no direct source->sink path", ha="center", va="center",
        fontsize=6.4, family=MONO, color=COLORS["red"])
ax.text(68, 42, "unknown types -> audit log flagged\n(fail closed, never dropped)",
        ha="center", va="center", fontsize=6.2, family=MONO,
        color=COLORS["red"])

# ---------- verification loop (bottom) ----------
ax.text(50, 22, "verification loop", ha="center", va="center", fontsize=8,
        weight="bold", color=COLORS["ink"])
ax.text(50, 17.5, "verify_chain() runs on rotation, export, post-incident; "
                  "reports first broken seq",
        ha="center", va="center", fontsize=7, family=MONO, color=COLORS["ink"])
arrow(ax, 30, 12, 70, 12, color="gray", lw=1.3, ls="--",
      label="checkpoint() -> WORM anchor -> truncation detection on mismatch",
      fs=6.8, label_pos=0.5)

caption(ax, "Every event passes through the router's emit() gate; no source "
            "writes any sink directly. The audit log is HMAC-chained and "
            "anchored to WORM; the trace forgets by design.",
        y=2.5, fs=8.2)

save(fig, "ch09")
print("ch09 done")
