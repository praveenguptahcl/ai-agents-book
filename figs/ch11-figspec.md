# FIG spec — Chapter 11: Kill Switch Architecture

**Placement:** end of Chapter 11, full-page width.
**Title:** "Kill Switch Architecture"

**Boxes:** Supervisor Process, KillSwitch (levels + verified-session registry + audit log), ActionExecutor (early gate + guarded broker), RiskMonitor (drawdown → auto-engage), Paper Broker (cancel/flatten/revoke effects), Operator Console (two-person engage with verified sessions).

**Arrows:**
- Supervisor Process ──(beat(), every few seconds)──▶ KillSwitch [freshness window 30s; silence ⇒ fail closed]
- ActionExecutor ──(check("submit") BEFORE any ledger write)──▶ KillSwitch [refused ⇒ HaltedError/HeartbeatStale, no phantom state]
- ActionExecutor ──(guarded(broker): check("submit") AT SEND TIME)──▶ Paper Broker [closes the TOCTOU gap]
- ActionExecutor ──(check("cancel") before cancel_all)──▶ KillSwitch [allowed at levels 1-3; refused at FULL_STOP]
- ActionExecutor ──(check("reconcile") during sweeps)──▶ KillSwitch [always allowed: read-only, freezing ≠ resolving]
- RiskMonitor ──(drawdown ≥ 3% ⇒ engage FLATTEN_HALT as verified risk-monitor session)──▶ KillSwitch [re-arm needs human admin]
- Operator Console ──(engage L1-L3: one verified session; L4: two distinct verified sessions)──▶ KillSwitch [raw strings rejected]
- KillSwitch ──(cancel_open_fn / flatten_fn / revoke_keys_fn, once per (scope, effect))──▶ Paper Broker [effects audited; failure arms anyway]
- KillSwitch ──(append engage/disarm + reasons)──▶ Audit Log ──▶ Evidence Ledger (Ch 14) / Compliance (Ch 19)
- Scoped-kill lane: (tenant, harbor) kill box beside the global KillSwitch, arrow to ActionExecutor labeled "governs only scope-matched actions"

**Invariants (caption or side panel):** (1) the gate runs before any state mutation; (2) the gate re-runs at send time via the guarded wrapper; (3) the switch boots refusing submits until the first beat; (4) reconcile and reads are never gated; (5) re-arm requires strictly greater authority than engagement plus a written reason — except FULL_STOP, which always needs two distinct admins; (6) a failed side effect is audited, never a reason to stay unarmed; (7) there is no break-glass path around the authority check; (8) operator identities are verified sessions, never raw strings.

**Style:** clean technical architecture diagram; red for the kill paths, green for the heartbeat, gray for read-only reconcile flows; monospace labels.
