"""Adversarial tests for the A2A 1.0 surface validator.

Every test is an attack: a card, message, artifact, transition, or
credential that should be refused, and the exact rule that must refuse it.
"""

import pytest

from a2a_validate import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATES,
    Credential,
    TaskState,
    validate_agent_card,
    validate_artifact,
    validate_message,
    validate_request_auth,
    validate_task_lifecycle,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def good_card() -> dict:
    return {
        "name": "Invoice Agent",
        "description": "Extracts structured data from invoices.",
        "version": "1.2.0",
        "supportedInterfaces": [
            {
                "url": "https://invoice.example.com/a2a/v1",
                "protocolBinding": "JSONRPC",
                "protocolVersion": "1.0",
            }
        ],
        "capabilities": {"streaming": True, "pushNotifications": False},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["application/json"],
        "skills": [
            {
                "id": "extract-invoice",
                "name": "Extract invoice",
                "description": "Parse an invoice image into structured fields.",
                "tags": ["finance", "ocr"],
            }
        ],
        "securitySchemes": {
            "bearer": {
                "httpAuthSecurityScheme": {"scheme": "Bearer", "bearerFormat": "JWT"}
            }
        },
        "securityRequirements": [{"scheme": "bearer"}],
    }


def good_message() -> dict:
    return {
        "messageId": "msg-001",
        "role": "ROLE_USER",
        "parts": [{"text": "Extract the total from this invoice."}],
    }


# ---------------------------------------------------------------------------
# Agent cards
# ---------------------------------------------------------------------------
class TestAgentCards:
    def test_good_card_passes(self):
        res = validate_agent_card(good_card())
        assert res.ok, [v.detail for v in res.violations]

    def test_malformed_card_missing_required_fields(self):
        res = validate_agent_card({"name": "half a card"})
        assert not res.ok
        rules = {v.rule for v in res.violations}
        assert "card.missing_required_field" in rules
        assert "card.no_interfaces" in rules

    def test_card_must_be_an_object(self):
        res = validate_agent_card(["not", "an", "object"])
        assert not res.ok
        assert res.violations[0].rule == "card.not_an_object"

    def test_insecure_interface_url_refused(self):
        card = good_card()
        card["supportedInterfaces"][0]["url"] = "http://invoice.example.com/a2a"
        res = validate_agent_card(card)
        assert not res.ok
        assert any(v.rule == "card.interface.insecure_url" for v in res.violations)

    def test_unknown_binding_is_warning_not_failure(self):
        card = good_card()
        card["supportedInterfaces"][0]["protocolBinding"] = "WEBSOCKET+X"
        res = validate_agent_card(card)
        assert res.ok  # open-form string per spec — accepted
        assert any(w.rule == "card.interface.unknown_binding" for w in res.warnings)

    def test_duplicate_skill_ids_refused(self):
        card = good_card()
        card["skills"].append(dict(card["skills"][0]))
        res = validate_agent_card(card)
        assert not res.ok
        assert any(v.rule == "card.skill.duplicate_id" for v in res.violations)

    def test_skill_claims_undefined_security_scheme(self):
        """Capability vs authority: a skill that claims protection by a
        scheme the card never defines is flagged."""
        card = good_card()
        card["skills"][0]["securityRequirements"] = [{"scheme": "ghost-oidc"}]
        res = validate_agent_card(card)
        assert not res.ok
        assert any(v.rule == "card.skill.undefined_security_requirement"
                   for v in res.violations)

    def test_extended_card_without_auth_refused(self):
        card = good_card()
        del card["securitySchemes"]
        del card["securityRequirements"]
        card["capabilities"]["extendedAgentCard"] = True
        res = validate_agent_card(card)
        assert not res.ok
        assert any(v.rule == "card.extended_card_without_auth" for v in res.violations)

    def test_security_scheme_must_have_exactly_one_kind(self):
        card = good_card()
        card["securitySchemes"]["broken"] = {
            "httpAuthSecurityScheme": {"scheme": "Bearer"},
            "mtlsSecurityScheme": {},
        }
        res = validate_agent_card(card)
        assert not res.ok
        assert any(v.rule == "card.security_scheme.not_exactly_one_kind"
                   for v in res.violations)

    def test_security_scheme_with_no_kind_refused(self):
        card = good_card()
        card["securitySchemes"]["empty"] = {"description": "nothing here"}
        res = validate_agent_card(card)
        assert not res.ok
        assert any(v.rule == "card.security_scheme.not_exactly_one_kind"
                   for v in res.violations)

    def test_rejections_name_the_targeted_protocol_version(self):
        # §A.1 promises the validator "says so in every rejection".
        card = good_card()
        del card["description"]
        res = validate_agent_card(card)
        assert not res.ok
        assert res.violations
        assert all("(validator targets v1.0.0)" in v.detail
                   for v in res.violations)

    def test_03x_era_protocol_version_refused(self):
        # A 0.3.x-era binding speaks a different wire protocol; the
        # v1.0.0 validator refuses it loudly, naming its target.
        card = good_card()
        card["supportedInterfaces"][0]["protocolVersion"] = "0.3.0"
        res = validate_agent_card(card)
        assert not res.ok
        assert any(v.rule == "card.interface.unsupported_protocol_version"
                   for v in res.violations)
        assert any("(validator targets v1.0.0)" in v.detail
                   for v in res.violations)

    def test_apikey_scheme_bad_location(self):
        card = good_card()
        card["securitySchemes"]["k"] = {
            "apiKeySecurityScheme": {"location": "carrier-pigeon", "name": "x-key"}
        }
        res = validate_agent_card(card)
        assert not res.ok
        assert any(v.rule == "card.security_scheme.apikey_bad_location"
                   for v in res.violations)

    def test_http_scheme_missing_scheme_refused(self):
        card = good_card()
        card["securitySchemes"]["h"] = {"httpAuthSecurityScheme": {}}
        res = validate_agent_card(card)
        assert not res.ok
        assert any(v.rule == "card.security_scheme.http_missing_scheme"
                   for v in res.violations)

    def test_apikey_scheme_missing_name_refused(self):
        card = good_card()
        card["securitySchemes"]["k"] = {
            "apiKeySecurityScheme": {"location": "header"}
        }
        res = validate_agent_card(card)
        assert not res.ok
        assert any(v.rule == "card.security_scheme.apikey_missing_name"
                   for v in res.violations)

    def test_oidc_scheme_missing_url_refused(self):
        card = good_card()
        card["securitySchemes"]["o"] = {"openIdConnectSecurityScheme": {}}
        res = validate_agent_card(card)
        assert not res.ok
        assert any(v.rule == "card.security_scheme.oidc_missing_url"
                   for v in res.violations)

    def test_oauth2_scheme_bad_flows_refused(self):
        # Exactly one flow type: zero flows is as illegal as two.
        bad = [
            {},
            {"authorizationCode": {"authorizationUrl": "https://x"},
             "clientCredentials": {"tokenUrl": "https://x"}},
        ]
        for flows in bad:
            card = good_card()
            card["securitySchemes"]["o2"] = {
                "oauth2SecurityScheme": {"flows": flows}
            }
            res = validate_agent_card(card)
            assert not res.ok, flows
            assert any(v.rule == "card.security_scheme.oauth2_flows"
                       for v in res.violations), flows
        # Exactly one flow type passes.
        card = good_card()
        card["securitySchemes"]["o2"] = {
            "oauth2SecurityScheme": {
                "flows": {"clientCredentials": {"tokenUrl": "https://x"}}
            }
        }
        assert validate_agent_card(card).ok

    def test_malformed_signature_refused(self):
        card = good_card()
        card["signatures"] = [{"header": {}}]  # missing protected + signature
        res = validate_agent_card(card)
        assert not res.ok
        assert any(v.rule == "card.malformed_signature" for v in res.violations)

    def test_shaped_signature_warns_unverified(self):
        """Honest residual: shape checks pass, but JWS is NOT verified
        without the signer's key — and the validator says so."""
        card = good_card()
        card["signatures"] = [{"protected": "eyJhbGciOiJSUzI1NiJ9",
                               "signature": "aGVsbG8"}]
        res = validate_agent_card(card)
        assert res.ok
        assert any(w.rule == "card.signature_unverified" for w in res.warnings)


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
class TestRequestAuth:
    def test_verified_declared_credential_accepted(self):
        res = validate_request_auth(good_card(), Credential("bearer", verified=True))
        assert res.ok

    def test_missing_credential_rejected(self):
        res = validate_request_auth(good_card(), None)
        assert not res.ok
        assert res.violations[0].rule == "auth.missing_credential"

    def test_unverified_credential_rejected(self):
        """The unsigned/skipped-auth case: presented but never verified
        is REJECTED, not downgraded."""
        res = validate_request_auth(good_card(), Credential("bearer", verified=False))
        assert not res.ok
        assert res.violations[0].rule == "auth.unverified_credential"

    def test_undeclared_scheme_rejected(self):
        res = validate_request_auth(good_card(), Credential("ghost-oidc", verified=True))
        assert not res.ok
        assert res.violations[0].rule == "auth.undeclared_scheme"

    def test_open_agent_warns_but_accepts(self):
        card = good_card()
        del card["securitySchemes"]
        res = validate_request_auth(card, None)
        assert res.ok
        assert any(w.rule == "auth.open_agent" for w in res.warnings)


# ---------------------------------------------------------------------------
# Messages and parts
# ---------------------------------------------------------------------------
class TestMessages:
    def test_good_message_passes(self):
        assert validate_message(good_message()).ok

    def test_missing_message_id(self):
        msg = good_message()
        del msg["messageId"]
        res = validate_message(msg)
        assert not res.ok
        assert any(v.rule == "message.missing_message_id" for v in res.violations)

    def test_bad_role(self):
        msg = good_message()
        msg["role"] = "ROLE_OVERLORD"
        res = validate_message(msg)
        assert not res.ok
        assert any(v.rule == "message.bad_role" for v in res.violations)

    def test_part_with_two_content_keys_refused(self):
        """Spec §4.1.6: a Part MUST contain exactly one of text/raw/url/data."""
        msg = good_message()
        msg["parts"] = [{"text": "hi", "data": {"x": 1}}]
        res = validate_message(msg)
        assert not res.ok
        assert any(v.rule == "part.not_exactly_one_content" for v in res.violations)

    def test_part_with_no_content_refused(self):
        msg = good_message()
        msg["parts"] = [{"metadata": {}}]
        res = validate_message(msg)
        assert not res.ok
        assert any(v.rule == "part.not_exactly_one_content" for v in res.violations)

    def test_empty_parts_refused(self):
        msg = good_message()
        msg["parts"] = []
        res = validate_message(msg)
        assert not res.ok
        assert any(v.rule == "message.no_parts" for v in res.violations)


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------
class TestArtifacts:
    def test_good_artifact_passes(self):
        a = {"artifactId": "art-1", "name": "report",
             "parts": [{"data": {"total": 42}}]}
        assert validate_artifact(a).ok

    def test_artifact_without_parts_refused(self):
        res = validate_artifact({"artifactId": "art-1", "parts": []})
        assert not res.ok
        assert any(v.rule == "artifact.no_parts" for v in res.violations)

    def test_artifact_without_id_refused(self):
        res = validate_artifact({"parts": [{"text": "x"}]})
        assert not res.ok
        assert any(v.rule == "artifact.missing_artifact_id" for v in res.violations)


# ---------------------------------------------------------------------------
# Task lifecycle
# ---------------------------------------------------------------------------
class TestTaskLifecycle:
    def test_happy_path_passes(self):
        transitions = [
            ("t1", "TASK_STATE_SUBMITTED", "TASK_STATE_WORKING"),
            ("t1", "TASK_STATE_WORKING", "TASK_STATE_INPUT_REQUIRED"),
            ("t1", "TASK_STATE_INPUT_REQUIRED", "TASK_STATE_WORKING"),
            ("t1", "TASK_STATE_WORKING", "TASK_STATE_COMPLETED"),
        ]
        assert validate_task_lifecycle(transitions).ok

    def test_illegal_transition_refused(self):
        """A task cannot go from SUBMITTED straight to COMPLETED."""
        res = validate_task_lifecycle(
            [("t1", "TASK_STATE_SUBMITTED", "TASK_STATE_COMPLETED")])
        assert not res.ok
        assert res.violations[0].rule == "task.illegal_transition"

    def test_completed_task_cannot_resurrect(self):
        """Terminal states are absorbing: completed -> working is refused."""
        res = validate_task_lifecycle(
            [("t1", "TASK_STATE_COMPLETED", "TASK_STATE_WORKING")])
        assert not res.ok
        assert res.violations[0].rule == "task.transition_from_terminal"

    def test_failed_task_cannot_resurrect(self):
        res = validate_task_lifecycle(
            [("t1", "TASK_STATE_FAILED", "TASK_STATE_WORKING")])
        assert not res.ok
        assert res.violations[0].rule == "task.transition_from_terminal"

    def test_unknown_state_refused(self):
        res = validate_task_lifecycle(
            [("t1", "TASK_STATE_SUBMITTED", "TASK_STATE_HOPEFUL")])
        assert not res.ok
        assert res.violations[0].rule == "task.unknown_state"

    def test_unspecified_state_never_valid(self):
        res = validate_task_lifecycle(
            [("t1", "TASK_STATE_UNSPECIFIED", "TASK_STATE_WORKING")])
        assert not res.ok
        assert res.violations[0].rule == "task.unspecified_state"

    def test_auth_required_resume_path(self):
        transitions = [
            ("t1", "TASK_STATE_SUBMITTED", "TASK_STATE_AUTH_REQUIRED"),
            ("t1", "TASK_STATE_AUTH_REQUIRED", "TASK_STATE_WORKING"),
            ("t1", "TASK_STATE_WORKING", "TASK_STATE_COMPLETED"),
        ]
        assert validate_task_lifecycle(transitions).ok

    def test_terminal_states_refuse_every_transition(self):
        # The old version of this test asserted TERMINAL_STATES equals
        # its own literal — it verified the assignment operator. This one
        # exercises behavior: no task leaves a terminal state, ever, not
        # even to itself.
        for state in (TaskState.COMPLETED, TaskState.FAILED,
                      TaskState.CANCELED, TaskState.REJECTED):
            for target in TaskState:
                res = validate_task_lifecycle(
                    [("t", state.value, target.value)])
                assert not res.ok, (state, target)
                assert res.violations[0].rule == "task.transition_from_terminal"

    def test_every_nonterminal_state_has_at_least_one_exit(self):
        for state, exits in ALLOWED_TRANSITIONS.items():
            if state in TERMINAL_STATES or state is TaskState.UNSPECIFIED:
                assert not exits
            else:
                assert exits, f"{state} is a dead end but not terminal"
