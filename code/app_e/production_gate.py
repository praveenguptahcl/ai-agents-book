"""Agent Production Standard v1.0 — the executable certification gate.

The book's thesis (Intent -> Authority -> Capability -> Action -> Evidence ->
Verification -> Accountability) compressed into nine checks. Each gate demands
EVIDENCE, not claims: the check inspects the artifact itself and fails when the
artifact is absent, empty, or malformed. CI runs run_standard() on the system's
evidence bundle; anything short of all nine demonstrated FAILS the build.

Evidence bundle shape: a dict mapping artifact keys to artifact content::

    {
      "identity":        {"service_name": ..., "version": ..., "owner": ...,
                          "tenant_isolation": {...}},
      "authority":       {"policy_doc": ..., "principals": [...],
                          "default_deny": True},
      "contracts":       [{"tool": ..., "input_schema": {...},
                           "output_schema": {...}}, ...],
      "threat_model":    {"threats": [{"threat": ..., "mitigation": ...,
                                       "residual": ...}], ...},
      "eval_thresholds": {"suite": ..., "thresholds": {...},
                          "regression_gate": True},
      "rollback":        {"runbook": [...], "last_drilled": ...,
                          "rto_minutes": ...},
      "logging":         {"evidence_spine": {...}, "tamper_evident": True},
      "escalation":      {"tiers": [{"risk_band": ..., "approver": ...,
                                    "channel": ...}], ...},
      "incident_owner":  {"name": ..., "contact": ..., "runbook_ref": ...},
    }
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List

STANDARD_VERSION = "1.0"


@dataclass
class GateResult:
    """The verdict for one gate: pass, or exactly what is missing."""

    name: str
    chapter: str  # the book chapter whose machinery satisfies this gate
    passed: bool
    missing: List[str] = field(default_factory=list)
    remediation: str = ""

    def checklist_line(self) -> str:
        mark = "[x]" if self.passed else "[ ]"
        detail = "demonstrated" if self.passed else "MISSING: " + "; ".join(self.missing)
        return f"{mark} {self.name}: {detail}"


@dataclass
class GateReport:
    """The full certification verdict. ships is False unless ALL gates pass."""

    results: List[GateResult]

    @property
    def ships(self) -> bool:
        return all(r.passed for r in self.results)

    def failures(self) -> List[GateResult]:
        return [r for r in self.results if not r.passed]

    def render(self) -> str:
        lines = [f"Agent Production Standard v{STANDARD_VERSION} — certification"]
        lines += [r.checklist_line() for r in self.results]
        if self.ships:
            lines.append("VERDICT: SHIPS — all nine gates demonstrated.")
        else:
            lines.append(f"VERDICT: NO SHIP — {len(self.failures())} gate(s) undemonstrated.")
            for f in self.failures():
                lines.append(f"  -> {f.name}: {f.remediation}")
        return "\n".join(lines)


def _missing_str(mapping: Dict[str, Any], key: str) -> List[str]:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        return [f"'{key}' must be a non-empty string"]
    return []


def _missing_list(mapping: Dict[str, Any], key: str) -> List[str]:
    value = mapping.get(key)
    if not isinstance(value, list) or not value:
        return [f"'{key}' must be a non-empty list"]
    return []


def _gate(name: str, chapter: str, remediation: str, missing: List[str]) -> GateResult:
    return GateResult(
        name=name, chapter=chapter, passed=not missing,
        missing=missing, remediation=remediation if missing else "",
    )


# ---------------------------------------------------------------------------
# The nine gates. Each is a pure function: evidence bundle -> GateResult.
# ---------------------------------------------------------------------------

def check_identity(evidence: Dict[str, Any]) -> GateResult:
    """Gate 1 — IDENTITY (Ch 3, Ch 6). Who is this system, and whose data
    may it touch? Demands the identity document, not the assertion."""
    artifact = evidence.get("identity")
    missing: List[str] = []
    if not isinstance(artifact, dict):
        missing.append("'identity' artifact absent: produce the identity document")
    else:
        for key in ("service_name", "version", "owner"):
            missing += _missing_str(artifact, key)
        isolation = artifact.get("tenant_isolation")
        if not isinstance(isolation, dict) or not isolation.get("mechanism"):
            missing.append("'tenant_isolation.mechanism' must name the isolation mechanism")
    return _gate(
        "identity", "Ch 3, Ch 6", missing=missing,
        remediation="Write the identity document: service name, version, owner, "
                    "and the named tenant-isolation mechanism (Ch 6).",
    )


def check_authority(evidence: Dict[str, Any]) -> GateResult:
    """Gate 2 — AUTHORITY (Ch 6, Ch 18). Who may do what, under which scopes?
    Default-deny is mandatory: an absent policy is not a permissive one."""
    artifact = evidence.get("authority")
    missing: List[str] = []
    if not isinstance(artifact, dict):
        missing.append("'authority' artifact absent: produce the authority policy")
    else:
        missing += _missing_str(artifact, "policy_doc")
        if artifact.get("default_deny") is not True:
            missing.append("'default_deny' must be True: deny-by-default is mandatory")
        principals = artifact.get("principals")
        if not isinstance(principals, list) or not principals:
            missing.append("'principals' must be a non-empty list")
        else:
            for i, p in enumerate(principals):
                if not isinstance(p, dict) or not p.get("name") or not p.get("scopes"):
                    missing.append(f"principals[{i}] must name the principal and its scopes")
    return _gate(
        "authority", "Ch 6, Ch 18", missing=missing,
        remediation="Produce the authority policy: principals, their scopes, and "
                    "default-deny (Ch 6). Wrappers must enforce it (Ch 18).",
    )


def check_contracts(evidence: Dict[str, Any]) -> GateResult:
    """Gate 3 — CONTRACTS (Ch 4). Every tool call the agent can make is
    described by a validated input/output schema. No schema, no call."""
    artifact = evidence.get("contracts")
    missing: List[str] = []
    if not isinstance(artifact, list) or not artifact:
        missing.append("'contracts' must be a non-empty list of tool contracts")
    else:
        for i, c in enumerate(artifact):
            if not isinstance(c, dict) or not c.get("tool"):
                missing.append(f"contracts[{i}] must name its tool")
                continue
            for side in ("input_schema", "output_schema"):
                schema = c.get(side)
                if not isinstance(schema, dict) or "type" not in schema:
                    missing.append(f"contracts[{i}].{side} must be a schema with a 'type'")
    return _gate(
        "contracts", "Ch 4", missing=missing,
        remediation="Write Pydantic/JSON-schema contracts for every tool "
                    "(Ch 4); embed verbatim listings checked by script.",
    )


def check_threat_model(evidence: Dict[str, Any]) -> GateResult:
    """Gate 4 — THREAT MODEL (Ch 12). The named adversaries and what stops
    them. Every threat needs a mitigation; the residual is stated honestly."""
    artifact = evidence.get("threat_model")
    missing: List[str] = []
    if not isinstance(artifact, dict):
        missing.append("'threat_model' artifact absent: produce the threat model")
    else:
        threats = artifact.get("threats")
        if not isinstance(threats, list) or not threats:
            missing.append("'threats' must be a non-empty list")
        else:
            for i, t in enumerate(threats):
                if not isinstance(t, dict):
                    missing.append(f"threats[{i}] must be a threat entry")
                    continue
                for key in ("threat", "mitigation", "residual"):
                    if not t.get(key):
                        missing.append(f"threats[{i}].{key} must be stated")
    return _gate(
        "threat_model", "Ch 12", missing=missing,
        remediation="Produce the threat model: named threats, each with a "
                    "mitigation and an honest residual (Ch 12).",
    )


def check_eval_thresholds(evidence: Dict[str, Any]) -> GateResult:
    """Gate 5 — EVAL THRESHOLDS (Ch 15). The frozen suite, the numeric bars,
    and the regression gate that blocks merges. Opinions don't ship; numbers do."""
    artifact = evidence.get("eval_thresholds")
    missing: List[str] = []
    if not isinstance(artifact, dict):
        missing.append("'eval_thresholds' artifact absent: produce the eval config")
    else:
        missing += _missing_str(artifact, "suite")
        if artifact.get("regression_gate") is not True:
            missing.append("'regression_gate' must be True: evals block the merge")
        thresholds = artifact.get("thresholds")
        if not isinstance(thresholds, dict) or not thresholds:
            missing.append("'thresholds' must be a non-empty mapping of metric -> bar")
        else:
            for metric, bar in thresholds.items():
                if not isinstance(bar, (int, float)) or isinstance(bar, bool):
                    missing.append(f"thresholds['{metric}'] must be a number")
    return _gate(
        "eval_thresholds", "Ch 15", missing=missing,
        remediation="Freeze the golden suite, set numeric bars (kappa, Wilson "
                    "lower bound, cost-per-verified-success), and wire the "
                    "regression gate into CI (Ch 15).",
    )


def check_rollback(evidence: Dict[str, Any]) -> GateResult:
    """Gate 6 — ROLLBACK (Ch 11, Ch 14). The way back, drilled. A runbook
    nobody has rehearsed is a rumor, not a control."""
    artifact = evidence.get("rollback")
    missing: List[str] = []
    if not isinstance(artifact, dict):
        missing.append("'rollback' artifact absent: produce the rollback runbook")
    else:
        missing += _missing_list(artifact, "runbook")
        if isinstance(artifact.get("runbook"), list):
            for i, step in enumerate(artifact["runbook"]):
                if not isinstance(step, str) or not step.strip():
                    missing.append(f"runbook[{i}] must be a concrete step")
        missing += _missing_str(artifact, "last_drilled")
        if artifact.get("rto_minutes") is None:
            missing.append("'rto_minutes' must state the recovery-time objective")
    return _gate(
        "rollback", "Ch 11, Ch 14", missing=missing,
        remediation="Write the rollback runbook as concrete steps, drill it, "
                    "and record the date and RTO (Ch 11, Ch 14).",
    )


def check_logging(evidence: Dict[str, Any]) -> GateResult:
    """Gate 7 — LOGGING (Ch 9). The tamper-evident evidence spine: every
    action leaves a hash-chained record, retained long enough to matter."""
    artifact = evidence.get("logging")
    missing: List[str] = []
    if not isinstance(artifact, dict):
        missing.append("'logging' artifact absent: produce the evidence-spine config")
    else:
        if artifact.get("tamper_evident") is not True:
            missing.append("'tamper_evident' must be True: hash-chained records")
        spine = artifact.get("evidence_spine")
        if not isinstance(spine, dict):
            missing.append("'evidence_spine' config absent")
        else:
            missing += _missing_str(spine, "hash_algorithm")
            missing += _missing_str(spine, "sink")
            retention = spine.get("retention_days")
            if not isinstance(retention, int) or isinstance(retention, bool) or retention < 30:
                missing.append("'retention_days' must be an integer >= 30")
    return _gate(
        "logging", "Ch 9", missing=missing,
        remediation="Configure the HMAC/hash-chained evidence spine with a named "
                    "sink and >= 30 days retention (Ch 9).",
    )


def check_escalation(evidence: Dict[str, Any]) -> GateResult:
    """Gate 8 — ESCALATION (Ch 19). Risk-tiered human approval with named
    approvers and channels. 'Someone will look at it' is not a tier."""
    artifact = evidence.get("escalation")
    missing: List[str] = []
    if not isinstance(artifact, dict):
        missing.append("'escalation' artifact absent: produce the escalation policy")
    else:
        tiers = artifact.get("tiers")
        if not isinstance(tiers, list) or not tiers:
            missing.append("'tiers' must be a non-empty list of risk tiers")
        else:
            for i, t in enumerate(tiers):
                if not isinstance(t, dict):
                    missing.append(f"tiers[{i}] must be a risk-tier entry")
                    continue
                for key in ("risk_band", "approver", "channel"):
                    if not t.get(key):
                        missing.append(f"tiers[{i}].{key} must be named")
    return _gate(
        "escalation", "Ch 19", missing=missing,
        remediation="Define risk tiers with a named approver and channel per "
                    "tier; design the approval UX (Ch 19, Appendix C).",
    )


def check_incident_owner(evidence: Dict[str, Any]) -> GateResult:
    """Gate 9 — INCIDENT OWNER (Ch 14). One named human, reachable, with the
    runbook in hand. Accountability that can't be paged is decoration."""
    artifact = evidence.get("incident_owner")
    missing: List[str] = []
    if not isinstance(artifact, dict):
        missing.append("'incident_owner' artifact absent: name the incident owner")
    else:
        for key in ("name", "contact", "runbook_ref"):
            missing += _missing_str(artifact, key)
    return _gate(
        "incident_owner", "Ch 14", missing=missing,
        remediation="Name the incident owner with contact and runbook reference "
                    "(Ch 14's on-call script).",
    )


GATES: List[Callable[[Dict[str, Any]], GateResult]] = [
    check_identity,
    check_authority,
    check_contracts,
    check_threat_model,
    check_eval_thresholds,
    check_rollback,
    check_logging,
    check_escalation,
    check_incident_owner,
]


def run_standard(evidence: Dict[str, Any]) -> GateReport:
    """Run all nine gates over the evidence bundle. CI calls this; the build
    fails unless report.ships is True."""
    return GateReport(results=[gate(evidence) for gate in GATES])
