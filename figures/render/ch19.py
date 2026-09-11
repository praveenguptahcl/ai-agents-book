"""Figure 19.1 -- ODAV x compliance-framework mapping table (12x8)."""
import sys
sys.path.insert(0, "/home/hatch/workspace/book-rebuild/figures")
from _style import *

fig, ax = new_fig(12, 8)
title(ax, "Figure 19.1 \u2014 ODAV \u00d7 compliance-framework mapping",
      fs=12)

XE = [1, 8, 52, 76, 99]          # column edges
HDR_H, BAND_H, ROW_H = 4.0, 3.6, 3.3

BANDS = [
    ("OBSERVE", "state must be known, bounded, provenance-labeled", [
        ("inputs carry provenance", "Art. 10 / Map 2",
         "Ch 2 REAL-vs-SYNTHETIC labeling", False),
        ("tenant separation", "ISO 42001 A.7 / CC6.1",
         "Ch 6 HMAC tenant sessions", False),
        ("retrieval ACLs", "CC6.1 / Govern 4",
         "Ch 15 ACL-at-index-vs-query", True),
    ]),
    ("DECIDE", "intentions structured, rejectable, attributable", [
        ("outputs constrained to declared actions", "Art. 14",
         "Ch 4 contracts, Ch 5 strict\nschemas, Ch 8 scope attenuation",
         False),
        ("purpose versioned", "ISO 42001 \u00a76 / Map 1",
         "Ch 3 hashed SystemIntent", False),
        ("delegation bounded", "Art. 15 / Measure 2",
         "Ch 8 depth limit,\ncycle guard, budget", True),
    ]),
    ("ACT", "effects pass guarded, reversible, stoppable gates", [
        ("high-risk approval", "Art. 14",
         "Ch 18 payload-bound approval\ntickets, Ch 11 two-admin lift",
         False),
        ("system stoppable", "Art. 14 / ISO 42001 A.8",
         "Ch 11 kill switches", False),
        ("idempotent reconciled execution", "SOC 2 PI1",
         "Ch 10 executor + WAL", False),
        ("boundary protection", "CC6.1 / CC7",
         "Ch 13 SSRF middleware\n+ sandbox", False),
        ("adversarial-input defense", "Art. 15 / Manage 2",
         "Ch 12 injection defense,\nCh 7 MCP description defense", False),
    ]),
    ("VERIFY", "world read back, record tamper-evident, reconstructable", [
        ("automatic logging", "Art. 12",
         "Ch 9 evidence spine,\nCh 14 TraceWriter", False),
        ("tamper-evident logs", "CC7.3 / ISO 42001 A.9",
         "Ch 9 HMAC chain +\nWORM anchoring", False),
        ("systematic evals", "Measure 1\u20133 / ISO 42001 \u00a79",
         "Ch 15/16/17", False),
        ("incident response", "CC7.4 / Govern 6",
         "Ch 14 on-call script,\nCh 11 drills", True),
        ("continuous risk management", "Art. 9 / ISO 42001 \u00a76",
         "Appendix E production gate", True),
    ]),
]

y = 90.0
# ---- column header row -------------------------------------------------
ax.add_patch(FancyBboxPatch((XE[0], y), XE[4] - XE[0], HDR_H,
                            boxstyle="round,pad=0.01",
                            facecolor=COLORS["gray"],
                            edgecolor=COLORS["gray"], lw=1.0))
for j, h in enumerate(["ODAV stage", "Framework demand",
                       "Framework clause", "Book mechanism"]):
    ax.text(XE[j] + 1.0, y + HDR_H / 2, h, va="center", ha="left",
            fontsize=7.5, weight="bold", color="white")
y -= HDR_H

for band_name, band_sub, rows in BANDS:
    # band header row
    ax.add_patch(FancyBboxPatch((XE[0], y - BAND_H), XE[4] - XE[0], BAND_H,
                                boxstyle="round,pad=0.01",
                                facecolor=COLORS["purple_lt"],
                                edgecolor=COLORS["purple"], lw=1.0))
    ax.text(XE[0] + 1.0, y - BAND_H / 2,
            f"{band_name}  \u2014  {band_sub}", va="center", ha="left",
            fontsize=8, weight="bold", color=COLORS["ink"])
    y -= BAND_H
    for demand, clause, mech, gap in rows:
        # row background + gridlines
        ax.add_patch(FancyBboxPatch((XE[0], y - ROW_H), XE[4] - XE[0],
                                    ROW_H, boxstyle="round,pad=0.005",
                                    facecolor="white",
                                    edgecolor=COLORS["gray_mid"], lw=0.7))
        for xe in XE[1:4]:
            ax.plot([xe, xe], [y - ROW_H, y], color=COLORS["gray_mid"],
                    lw=0.7)
        # demand cell (+ gap glyph)
        dx = XE[1] + 1.0
        if gap:
            ax.text(dx, y - ROW_H / 2, "\u25b2", va="center", ha="left",
                    fontsize=8, color=COLORS["amber"], weight="bold")
            dx += 2.6
        ax.text(dx, y - ROW_H / 2, demand, va="center", ha="left",
                fontsize=7, color=COLORS["ink"])
        # clause cell (mono)
        ax.text(XE[2] + 1.0, y - ROW_H / 2, clause, va="center", ha="left",
                fontsize=6.5, family=MONO, color=COLORS["ink"])
        # mechanism cell
        ax.text(XE[3] + 1.0, y - ROW_H / 2, mech, va="center", ha="left",
                fontsize=6.6, color=COLORS["ink"], linespacing=1.25)
        y -= ROW_H

# ---- legend + footer ----------------------------------------------------
ax.text(2, 15.8, "\u25b2", ha="left", va="center", fontsize=9,
        color=COLORS["amber"], weight="bold")
ax.text(4.4, 15.8, "marks the organizational half \u2014 named and owned, "
                    "not hidden.",
        ha="left", va="center", fontsize=7.5, color=COLORS["ink"])
ax.text(2, 10.8,
        "Mechanisms are technical; the named gaps are organizational. "
        "An auditor who sees a gap named and owned trusts the mechanisms "
        "more, not less.",
        ha="left", fontsize=7.5, style="italic", color=COLORS["gray"])

caption(ax, "Figure 19.1 \u2014 Every control the frameworks demand, mapped "
            "to the mechanism that satisfies it \u2014 and the gaps honestly "
            "marked. Compliance as translation.")

save(fig, "ch19")
print("ch19 done")
