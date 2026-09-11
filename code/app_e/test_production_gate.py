"""Adversarial tests for the Agent Production Standard gate.

The suite attacks the gate itself: every gate is tested with a system missing
exactly that gate (nine negative fixtures), a fully-evidenced system (one
positive), and systems that FAKE evidence (claim the gate with empty or
placeholder artifacts) — because "we have a policy" is not a policy.
"""

import copy

import pytest

from production_gate import (
    STANDARD_VERSION,
    GateReport,
    check_authority,
    run_standard,
)


def full_evidence():
    """A system with all nine gates genuinely demonstrated."""
    return {
        "identity": {
            "service_name": "wealthforge-desk-agent",
            "version": "2.4.1",
            "owner": "desk-engineering",
            "tenant_isolation": {
                "mechanism": "tenant-bound session tokens (Ch 6)",
                "session_binding": "HMAC-SHA256",
            },
        },
        "authority": {
            "policy_doc": "policies/authority-v7.md",
            "default_deny": True,
            "principals": [
                {"name": "signal-agent", "scopes": ["market-data:read", "signals:propose"]},
                {"name": "executor", "scopes": ["orders:submit", "orders:cancel"]},
            ],
        },
        "contracts": [
            {
                "tool": "submit_order",
                "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}}},
                "output_schema": {"type": "object", "properties": {"order_id": {"type": "string"}}},
            },
        ],
        "threat_model": {
            "threats": [
                {
                    "threat": "prompt injection via earnings-call transcript",
                    "mitigation": "Ch 12 output review on all tool results",
                    "residual": "novel exfiltration phrasing; monitored",
                },
            ],
        },
        "eval_thresholds": {
            "suite": "golden-v12",
            "regression_gate": True,
            "thresholds": {
                "kappa_min": 0.6,
                "wilson_lower_bound_min": 0.8,
                "cost_per_verified_success_max": 4.20,
            },
        },
        "rollback": {
            "runbook": [
                "Freeze new intents via scoped kill (tenant desk).",
                "Drain in-flight orders to terminal states.",
                "Restore model checkpoint v-previous from pinned registry.",
            ],
            "last_drilled": "2026-08-30",
            "rto_minutes": 30,
        },
        "logging": {
            "tamper_evident": True,
            "evidence_spine": {
                "hash_algorithm": "HMAC-SHA256",
                "sink": "append-only evidence store",
                "retention_days": 365,
            },
        },
        "escalation": {
            "tiers": [
                {"risk_band": "expected_loss < $10k", "approver": "desk lead",
                 "channel": "ops channel"},
                {"risk_band": "expected_loss >= $10k", "approver": "risk officer",
                 "channel": "paged escalation"},
            ],
        },
        "incident_owner": {
            "name": "Maya Chen",
            "contact": "on-call rotation alpha",
            "runbook_ref": "runbooks/outcome-unknown.md",
        },
    }


# ---------------------------------------------------------------------------
# The positive case: all nine demonstrated.
# ---------------------------------------------------------------------------

def test_fully_evidenced_system_ships():
    report = run_standard(full_evidence())
    assert isinstance(report, GateReport)
    assert report.ships is True
    assert report.failures() == []
    assert len(report.results) == 9
    rendered = report.render()
    assert "VERDICT: SHIPS" in rendered
    assert rendered.count("[x]") == 9


def test_standard_version_pinned():
    assert STANDARD_VERSION == "1.0"


# ---------------------------------------------------------------------------
# Nine negative fixtures: each system is missing exactly one gate, and only
# that gate must fail. The gate under test must name the missing artifact.
# ---------------------------------------------------------------------------

def _drop(evidence, key):
    evidence = copy.deepcopy(evidence)
    del evidence[key]
    return evidence


def test_missing_identity_fails_only_identity():
    report = run_standard(_drop(full_evidence(), "identity"))
    assert report.ships is False
    failed = {f.name for f in report.failures()}
    assert failed == {"identity"}
    assert "identity" in report.failures()[0].remediation


def test_missing_authority_fails_only_authority():
    report = run_standard(_drop(full_evidence(), "authority"))
    assert report.ships is False
    assert {f.name for f in report.failures()} == {"authority"}


def test_missing_contracts_fails_only_contracts():
    report = run_standard(_drop(full_evidence(), "contracts"))
    assert report.ships is False
    assert {f.name for f in report.failures()} == {"contracts"}


def test_missing_threat_model_fails_only_threat_model():
    report = run_standard(_drop(full_evidence(), "threat_model"))
    assert report.ships is False
    assert {f.name for f in report.failures()} == {"threat_model"}


def test_missing_eval_thresholds_fails_only_eval_thresholds():
    report = run_standard(_drop(full_evidence(), "eval_thresholds"))
    assert report.ships is False
    assert {f.name for f in report.failures()} == {"eval_thresholds"}


def test_missing_rollback_fails_only_rollback():
    report = run_standard(_drop(full_evidence(), "rollback"))
    assert report.ships is False
    assert {f.name for f in report.failures()} == {"rollback"}


def test_missing_logging_fails_only_logging():
    report = run_standard(_drop(full_evidence(), "logging"))
    assert report.ships is False
    assert {f.name for f in report.failures()} == {"logging"}


def test_missing_escalation_fails_only_escalation():
    report = run_standard(_drop(full_evidence(), "escalation"))
    assert report.ships is False
    assert {f.name for f in report.failures()} == {"escalation"}


def test_missing_incident_owner_fails_only_incident_owner():
    report = run_standard(_drop(full_evidence(), "incident_owner"))
    assert report.ships is False
    assert {f.name for f in report.failures()} == {"incident_owner"}


def test_empty_evidence_fails_all_nine():
    report = run_standard({})
    assert report.ships is False
    assert len(report.failures()) == 9
    rendered = report.render()
    assert "VERDICT: NO SHIP" in rendered
    assert rendered.count("[ ]") == 9


# ---------------------------------------------------------------------------
# Fake evidence: claims the gate, ships no artifact. The evidence-demand
# check must catch each forgery.
# ---------------------------------------------------------------------------

def test_fake_identity_placeholder_fails():
    evidence = _drop(full_evidence(), "identity")
    evidence["identity"] = {"service_name": "TBD", "version": "", "owner": "   "}
    report = run_standard(evidence)
    assert {f.name for f in report.failures()} == {"identity"}


def test_fake_authority_without_default_deny_fails():
    """'We have a policy' with default-allow is worse than no policy: it is
    a promise that misleads the reviewer."""
    evidence = full_evidence()
    evidence["authority"]["default_deny"] = False
    result = check_authority(evidence)
    assert result.passed is False
    assert any("default_deny" in m for m in result.missing)


def test_fake_authority_scopeless_principal_fails():
    evidence = full_evidence()
    evidence["authority"]["principals"] = [{"name": "everything-agent"}]
    report = run_standard(evidence)
    assert {f.name for f in report.failures()} == {"authority"}


def test_fake_contracts_typeless_schema_fails():
    evidence = full_evidence()
    evidence["contracts"] = [{"tool": "submit_order",
                              "input_schema": {"anything": "goes"},
                              "output_schema": {"type": "object"}}]
    report = run_standard(evidence)
    assert {f.name for f in report.failures()} == {"contracts"}


def test_fake_threat_model_without_residual_fails():
    """A threat model that never admits a residual is marketing."""
    evidence = full_evidence()
    evidence["threat_model"]["threats"] = [
        {"threat": "injection", "mitigation": "we handle it", "residual": ""}
    ]
    report = run_standard(evidence)
    assert {f.name for f in report.failures()} == {"threat_model"}


def test_fake_eval_thresholds_non_numeric_bar_fails():
    evidence = full_evidence()
    evidence["eval_thresholds"]["thresholds"]["kappa_min"] = "high"
    report = run_standard(evidence)
    assert {f.name for f in report.failures()} == {"eval_thresholds"}


def test_fake_eval_regression_gate_off_fails():
    evidence = full_evidence()
    evidence["eval_thresholds"]["regression_gate"] = False
    report = run_standard(evidence)
    assert {f.name for f in report.failures()} == {"eval_thresholds"}


def test_fake_rollback_never_drilled_fails():
    evidence = full_evidence()
    evidence["rollback"]["last_drilled"] = ""
    report = run_standard(evidence)
    assert {f.name for f in report.failures()} == {"rollback"}


def test_fake_logging_short_retention_fails():
    evidence = full_evidence()
    evidence["logging"]["evidence_spine"]["retention_days"] = 7
    report = run_standard(evidence)
    assert {f.name for f in report.failures()} == {"logging"}


def test_fake_logging_tamper_evident_off_fails():
    evidence = full_evidence()
    evidence["logging"]["tamper_evident"] = False
    report = run_standard(evidence)
    assert {f.name for f in report.failures()} == {"logging"}


def test_fake_escalation_anonymous_approver_fails():
    evidence = full_evidence()
    evidence["escalation"]["tiers"] = [{"risk_band": "big", "approver": "",
                                        "channel": "somewhere"}]
    report = run_standard(evidence)
    assert {f.name for f in report.failures()} == {"escalation"}


def test_fake_incident_owner_no_runbook_fails():
    evidence = full_evidence()
    evidence["incident_owner"]["runbook_ref"] = None
    report = run_standard(evidence)
    assert {f.name for f in report.failures()} == {"incident_owner"}


# ---------------------------------------------------------------------------
# Remediation quality: every failure must tell the engineer exactly what to
# produce. A gate that fails silently is a gate that never gets fixed.
# ---------------------------------------------------------------------------

def test_every_failure_names_a_remediation():
    report = run_standard({})
    for failure in report.failures():
        assert failure.remediation, f"gate '{failure.name}' fails without remediation"
        assert failure.missing, f"gate '{failure.name}' fails without naming the gap"
