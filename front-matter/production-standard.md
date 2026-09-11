# Agent Production Standard v1.0

*No agent system ships until all nine gates are demonstrated. A claim is not a demonstration — each gate demands the artifact.*

| # | Gate | Demonstrate | Artifact |
|---|------|-------------|----------|
| 1 | **Identity** (Ch 3, 6) | Service name, version, owner, named tenant-isolation mechanism | identity document |
| 2 | **Authority** (Ch 6, 18) | Principals + scopes, default-deny asserted | authority policy |
| 3 | **Contracts** (Ch 4) | Typed input/output schema per tool | tool contracts |
| 4 | **Threat model** (Ch 12) | Named threats, each with mitigation + honest residual | threat model |
| 5 | **Eval thresholds** (Ch 15) | Frozen golden suite, numeric bars, regression gate in CI | eval config |
| 6 | **Rollback** (Ch 11, 14) | Concrete steps, drilled — drill date recorded, RTO stated | rollback runbook |
| 7 | **Logging** (Ch 9) | Hash-chained evidence spine, named sink, ≥ 30 days retention | spine config |
| 8 | **Escalation** (Ch 19) | Risk tiers, named approver + channel per tier | escalation policy |
| 9 | **Incident owner** (Ch 14) | One named human, contact, runbook reference | owner record |

**The rule:** for each gate, produce the artifact — do not describe it. Any gate undemonstrated fails the build (`production_gate.py`, Appendix E). Certification is a timestamp, not a tattoo: re-certify on every version bump.
