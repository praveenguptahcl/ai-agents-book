# Gemini Review — Ch 11: Kill Switches
- **Model:** Pro Extended (Gemini 3.1 Pro class)
- **Date:** 2026-09-11
- **Verdict:** PASS-WITH-FIXES
- **Files reviewed:** ch11-kill-switches.md, killswitch.py, test_killswitch.py (all attached and cited)

## Full verbatim review

Verdict & General Impression

PASS-WITH-FIXES. The architecture is structurally sound for frameworks like AlphaForge or WealthForge, and the "stop button must not ask permission" philosophy is dead-on. However, there are critical bypass paths in the authority logic and a classic race condition in the executor binding that would fail a formal verification check.

### Architectural & Authority Findings

**Critical: Re-arm logic bypasses the two-person rule.** If two operators (rank 1) engage a FULL_STOP (level 4), the engager_rank is recorded as 1. A single risk officer (rank 2) can subsequently disarm it because they hold strictly greater rank. A Level 4 kill must always require two admins to lift, regardless of the rank of the engagers.

**High: The two-person rule is API theater.** The engage() method accepts a list of string IDs. A single attacker with access to the execution plane can submit ["admin-ruth", "admin-sam"] to spoof consensus. Unless identities are cryptographically bound via session tokens in the ingress gateway, this is not a true two-person control.

**Medium: Missing taxonomy scope.** The four levels are globally escalating. In a multi-agent framework, you need per-strategy or per-tenant scopes. Halting the entire firm because one dividend-capture agent looped is too blunt an instrument.

### Code & Execution Findings

**Critical: TOCTOU race in executor binding.** You state the check runs before the write-ahead ledger row is created. In an async environment, checking killswitch.check("submit") before the network call creates a Time-of-Check to Time-of-Use race. An order can pass the gate, yield the thread, and be sent to Robinhood or Alpaca after the kill engages. The kill switch must wrap the actual network client to truly stop the action plane.

**Medium: Chaos drills test the mock.** The test_kill_during_open_order_leaves_ledger_consistent drill relies on FakeExecutor. It verifies that the mock correctly updates its own internal dictionary. It does not prove the production ledger degrades gracefully under live network conditions.

### Prose to Cut

Cut the repetition in the Chaos Drills section. The extended explanation of "freezing is not resolving" is unnecessary. You already made this exact point clearly in the "Four levels of kill" section.

How do you plan to handle cryptographic token validation for the OperatorRegistry to prevent spoofing in the final production implementation?
