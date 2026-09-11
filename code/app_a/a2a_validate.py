"""Appendix A — A2A 1.0 Protocol surface validator (a2a_validate.py).

Validates the *protocol surface* of the Agent2Agent (A2A) protocol v1.0.0
(https://a2a-protocol.org/v1.0.0/specification/) as seen by a CLIENT:
agent cards, message envelopes, artifacts, task lifecycle transitions,
and authentication artifacts.

Verified against the v1.0.0 spec before writing (same bar as Ch 7's MCP
verification). Every rule below names the spec section it comes from;
rules that are the book's own stricter additions are marked [BOOK RULE].

Honesty contract: this validator checks SHAPE and SPEC-DERIVED RULES,
not semantics. A card that passes every check is still just a CLAIM —
see the appendix prose on capability vs authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Task states — spec §4.1.3 (verified against the v1.0.0 spec table).
# ---------------------------------------------------------------------------
class TaskState(str, Enum):
    UNSPECIFIED = "TASK_STATE_UNSPECIFIED"
    SUBMITTED = "TASK_STATE_SUBMITTED"
    WORKING = "TASK_STATE_WORKING"
    COMPLETED = "TASK_STATE_COMPLETED"
    FAILED = "TASK_STATE_FAILED"
    CANCELED = "TASK_STATE_CANCELED"
    INPUT_REQUIRED = "TASK_STATE_INPUT_REQUIRED"
    REJECTED = "TASK_STATE_REJECTED"
    AUTH_REQUIRED = "TASK_STATE_AUTH_REQUIRED"


# Terminal states — spec §4.1.3: "This is a terminal state." for
# completed, failed, canceled, rejected.
TERMINAL_STATES = frozenset({
    TaskState.COMPLETED,
    TaskState.FAILED,
    TaskState.CANCELED,
    TaskState.REJECTED,
})


# The spec names the states and marks terminals, but does NOT define a
# normative transition table. [BOOK RULE] The table below is the book's
# stricter addition: every edge below is the only legal move; terminal
# states are absorbing (a dead task stays dead).
ALLOWED_TRANSITIONS: dict[TaskState, frozenset[TaskState]] = {
    TaskState.SUBMITTED: frozenset({
        TaskState.WORKING, TaskState.INPUT_REQUIRED, TaskState.AUTH_REQUIRED,
        TaskState.REJECTED, TaskState.CANCELED,
    }),
    TaskState.WORKING: frozenset({
        TaskState.INPUT_REQUIRED, TaskState.AUTH_REQUIRED,
        TaskState.COMPLETED, TaskState.FAILED,
        TaskState.REJECTED, TaskState.CANCELED,
    }),
    TaskState.INPUT_REQUIRED: frozenset({
        TaskState.WORKING, TaskState.CANCELED, TaskState.FAILED,
    }),
    TaskState.AUTH_REQUIRED: frozenset({
        TaskState.WORKING, TaskState.CANCELED, TaskState.FAILED,
        TaskState.REJECTED,
    }),
    TaskState.COMPLETED: frozenset(),
    TaskState.FAILED: frozenset(),
    TaskState.CANCELED: frozenset(),
    TaskState.REJECTED: frozenset(),
    TaskState.UNSPECIFIED: frozenset(),  # indeterminate -> never a valid status
}


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RuleViolation:
    rule: str        # e.g. "card.missing_required_field"
    path: str        # JSON path to the offending value
    detail: str      # what failed and why


@dataclass
class ValidationResult:
    ok: bool = True
    violations: list[RuleViolation] = field(default_factory=list)
    warnings: list[RuleViolation] = field(default_factory=list)

    def fail(self, rule: str, path: str, detail: str) -> "ValidationResult":
        self.ok = False
        # §A.1's promise: the validator targets v1.0.0 and says so in
        # every rejection. Warnings are not rejections; they keep quiet.
        self.violations.append(
            RuleViolation(rule, path, f"{detail} (validator targets v1.0.0)"))
        return self

    def warn(self, rule: str, path: str, detail: str) -> "ValidationResult":
        self.warnings.append(RuleViolation(rule, path, detail))
        return self


# ---------------------------------------------------------------------------
# Agent card — spec §4.4.1..§4.4.7, §8.6 (well-known URI).
# ---------------------------------------------------------------------------

# Core bindings named in spec §4.4.6 (open-form string; these three are official).
KNOWN_BINDINGS = frozenset({"JSONRPC", "GRPC", "HTTP+JSON"})

# Spec §4.5.1: a SecurityScheme MUST contain exactly one of these.
SCHEME_KINDS = (
    "apiKeySecurityScheme",
    "httpAuthSecurityScheme",
    "oauth2SecurityScheme",
    "openIdConnectSecurityScheme",
    "mtlsSecurityScheme",
)

# Spec §4.4.1 required fields.
CARD_REQUIRED = (
    "name", "description", "supportedInterfaces", "version",
    "capabilities", "defaultInputModes", "defaultOutputModes", "skills",
)

WELL_KNOWN_PATH = "/.well-known/agent-card.json"  # spec §8.6


def validate_agent_card(card: Any) -> ValidationResult:
    """Validate an A2A AgentCard document (spec §4.4.1)."""
    res = ValidationResult()
    if not isinstance(card, dict):
        return res.fail("card.not_an_object", "$", "AgentCard must be a JSON object")
    for f in CARD_REQUIRED:
        if f not in card:
            res.fail("card.missing_required_field", f"$.{f}",
                     f"spec §4.4.1 requires '{f}'")
    if not isinstance(card.get("supportedInterfaces"), list) or not card.get("supportedInterfaces"):
        res.fail("card.no_interfaces", "$.supportedInterfaces",
                 "at least one AgentInterface is required (§4.4.1)")
    else:
        for i, iface in enumerate(card["supportedInterfaces"]):
            _validate_interface(iface, f"$.supportedInterfaces[{i}]", res)
    if "skills" in card and isinstance(card["skills"], list):
        _validate_skills(card["skills"], card, res)
    if "securitySchemes" in card:
        _validate_security_schemes(card["securitySchemes"], "$.securitySchemes", res)
    # Capability-vs-authority: the extended card is only meaningful
    # behind authentication (§4.4.3). Claiming it without any scheme
    # is a card that promises what it cannot deliver.
    caps = card.get("capabilities") or {}
    if caps.get("extendedAgentCard") and not card.get("securitySchemes"):
        res.fail("card.extended_card_without_auth",
                 "$.capabilities.extendedAgentCard",
                 "extendedAgentCard=true but no securitySchemes are declared: "
                 "the extended card cannot be gated behind authentication it does not define")
    # Signatures: shape-checked, but JWS verification needs the signer's
    # key, which offline validation does not have. Say so honestly.
    if "signatures" in card and isinstance(card["signatures"], list):
        for i, sig in enumerate(card["signatures"]):
            if not (isinstance(sig, dict) and sig.get("protected") and sig.get("signature")):
                res.fail("card.malformed_signature", f"$.signatures[{i}]",
                         "AgentCardSignature requires 'protected' and 'signature' (§4.4.7)")
            else:
                res.warn("card.signature_unverified", f"$.signatures[{i}]",
                         "signature shape is valid but JWS was NOT verified "
                         "(no signer key available to this validator)")
    return res


def _validate_interface(iface: Any, path: str, res: ValidationResult) -> None:
    if not isinstance(iface, dict):
        res.fail("card.interface.not_an_object", path, "AgentInterface must be an object")
        return
    url = iface.get("url", "")
    # Spec §4.4.6: "Must be a valid absolute HTTPS URL in production."
    if not (isinstance(url, str) and url.startswith("https://")):
        res.fail("card.interface.insecure_url", f"{path}.url",
                 f"interface URL must be an absolute HTTPS URL in production (§4.4.6); got {url!r}")
    binding = iface.get("protocolBinding", "")
    if binding not in KNOWN_BINDINGS:
        res.warn("card.interface.unknown_binding", f"{path}.protocolBinding",
                 f"'{binding}' is not one of the spec's core bindings {sorted(KNOWN_BINDINGS)}; "
                 "accepted as an open-form string per §4.4.6")
    if not iface.get("protocolVersion"):
        res.fail("card.interface.missing_protocol_version", f"{path}.protocolVersion",
                 "protocolVersion is required on AgentInterface (§4.4.6)")
    elif not str(iface["protocolVersion"]).startswith("1."):
        # [BOOK RULE] The validator targets v1.0.0. A 0.3.x-era binding
        # speaks a different wire protocol (lowercase method names, older
        # card shape); it is refused loudly, never coerced. Note this is
        # the interface's protocol version, not the card's agent "version"
        # field — the agent's own version is free-form per §4.4.1 and is
        # presence-checked only.
        res.fail("card.interface.unsupported_protocol_version",
                 f"{path}.protocolVersion",
                 f"protocolVersion {iface['protocolVersion']!r} is not a v1.x "
                 "binding; 0.3.x-era agents speak a different wire protocol (§A.1)")


def _validate_skills(skills: list, card: dict, res: ValidationResult) -> None:
    seen: set[str] = set()
    schemes = set((card.get("securitySchemes") or {}).keys())
    for i, skill in enumerate(skills):
        p = f"$.skills[{i}]"
        if not isinstance(skill, dict):
            res.fail("card.skill.not_an_object", p, "AgentSkill must be an object")
            continue
        for f in ("id", "name", "description", "tags"):
            if f not in skill:
                res.fail("card.skill.missing_required_field", f"{p}.{f}",
                         f"spec §4.4.5 requires '{f}' on AgentSkill")
        sid = skill.get("id")
        if sid is not None:
            if sid in seen:
                res.fail("card.skill.duplicate_id", f"{p}.id",
                         f"skill id {sid!r} is declared twice")
            seen.add(sid)
        # A skill that claims protection by a scheme the card never
        # defines is claiming an authority it does not have.
        for j, req in enumerate(skill.get("securityRequirements") or []):
            name = req.get("scheme") if isinstance(req, dict) else req
            if name not in schemes:
                res.fail("card.skill.undefined_security_requirement",
                         f"{p}.securityRequirements[{j}]",
                         f"skill requires scheme {name!r} which is not declared "
                         "in $.securitySchemes: capability without authority")


def _validate_security_schemes(schemes: Any, path: str, res: ValidationResult) -> None:
    if not isinstance(schemes, dict):
        res.fail("card.security_schemes.not_a_map", path,
                 "securitySchemes must be a map of name -> SecurityScheme (§4.4.1)")
        return
    for name, scheme in schemes.items():
        sp = f"{path}.{name}"
        if not isinstance(scheme, dict):
            res.fail("card.security_scheme.not_an_object", sp,
                     "SecurityScheme must be an object (§4.5.1)")
            continue
        present = [k for k in SCHEME_KINDS if k in scheme]
        if len(present) != 1:
            # Spec §4.5.1: MUST contain exactly one of the five kinds.
            res.fail("card.security_scheme.not_exactly_one_kind", sp,
                     f"must contain exactly one of {SCHEME_KINDS}; found {present}")
            continue
        kind = present[0]
        body = scheme[kind]
        if kind == "httpAuthSecurityScheme" and not body.get("scheme"):
            res.fail("card.security_scheme.http_missing_scheme", sp,
                     "HTTPAuthSecurityScheme requires 'scheme' (e.g. 'Bearer') (§4.5.3)")
        if kind == "apiKeySecurityScheme":
            if body.get("location") not in ("query", "header", "cookie"):
                res.fail("card.security_scheme.apikey_bad_location", sp,
                         "APIKeySecurityScheme location must be query|header|cookie (§4.5.2)")
            if not body.get("name"):
                res.fail("card.security_scheme.apikey_missing_name", sp,
                         "APIKeySecurityScheme requires 'name' (§4.5.2)")
        if kind == "openIdConnectSecurityScheme" and not body.get("openIdConnectUrl"):
            res.fail("card.security_scheme.oidc_missing_url", sp,
                     "OpenIdConnectSecurityScheme requires 'openIdConnectUrl' (§4.5.5)")
        if kind == "oauth2SecurityScheme":
            flows = body.get("flows") or {}
            present_flows = [f for f in ("authorizationCode", "clientCredentials",
                                         "implicit", "password", "deviceCode")
                             if flows.get(f)]
            # Spec §4.5.7: MUST contain exactly one flow type.
            if len(present_flows) != 1:
                res.fail("card.security_scheme.oauth2_flows", sp,
                         f"OAuthFlows must contain exactly one flow type (§4.5.7); found {present_flows}")


# ---------------------------------------------------------------------------
# Authentication artifacts — spec §13 / §4.5: the client MUST authenticate
# using one of the schemes declared in AgentCard.securitySchemes.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Credential:
    """What the caller presented for THIS request (client-side view)."""
    scheme_name: str   # must name a scheme in the card's securitySchemes
    verified: bool     # did the caller actually verify it (not just claim it)


def validate_request_auth(card: dict, credential: Optional[Credential]) -> ValidationResult:
    """Check that an A2A request carries the authentication the card demands.

    The three outcomes mirror the three ways auth goes wrong:
      1. the card demands auth and nothing was presented -> reject
      2. something was presented but never verified -> reject (unsigned/
         skipped-auth artifacts are REJECTED, not downgraded)
      3. a verified credential naming a declared scheme -> accept
    """
    res = ValidationResult()
    schemes = (card.get("securitySchemes") or {})
    if not schemes:
        res.warn("auth.open_agent", "$",
                 "card declares no securitySchemes: anyone may call this agent. "
                 "Treat every response as untrusted (§4.5)")
        return res
    if credential is None:
        res.fail("auth.missing_credential", "$",
                 f"card requires authentication via one of {sorted(schemes)}; "
                 "no credential was presented")
        return res
    if credential.scheme_name not in schemes:
        res.fail("auth.undeclared_scheme", "$",
                 f"credential names scheme {credential.scheme_name!r}, which the card "
                 f"does not declare (declared: {sorted(schemes)})")
        return res
    if not credential.verified:
        res.fail("auth.unverified_credential", "$",
                 f"credential for scheme {credential.scheme_name!r} was presented "
                 "but NOT verified: unsigned/skipped-auth artifacts are rejected")
    return res


# ---------------------------------------------------------------------------
# Messages and parts — spec §4.1.4, §4.1.6.
# ---------------------------------------------------------------------------
PART_CONTENT_KEYS = ("text", "raw", "url", "data")  # oneOf — §4.1.6


def validate_message(msg: Any) -> ValidationResult:
    """Validate a Message envelope (spec §4.1.4)."""
    res = ValidationResult()
    if not isinstance(msg, dict):
        return res.fail("message.not_an_object", "$", "Message must be an object")
    if not msg.get("messageId"):
        res.fail("message.missing_message_id", "$.messageId",
                 "messageId is required (§4.1.4)")
    if msg.get("role") not in ("ROLE_USER", "ROLE_AGENT", "ROLE_UNSPECIFIED"):
        res.fail("message.bad_role", "$.role",
                 "role must be ROLE_USER, ROLE_AGENT, or ROLE_UNSPECIFIED (§4.1.5)")
    parts = msg.get("parts")
    if not isinstance(parts, list) or not parts:
        res.fail("message.no_parts", "$.parts",
                 "parts is required and must be non-empty (§4.1.4)")
    else:
        for i, part in enumerate(parts):
            _validate_part(part, f"$.parts[{i}]", res)
    return res


def _validate_part(part: Any, path: str, res: ValidationResult) -> None:
    if not isinstance(part, dict):
        res.fail("part.not_an_object", path, "Part must be an object")
        return
    present = [k for k in PART_CONTENT_KEYS if part.get(k) is not None]
    # Spec §4.1.6: a Part MUST contain exactly one of text/raw/url/data.
    if len(present) != 1:
        res.fail("part.not_exactly_one_content", path,
                 f"Part must contain exactly one of {PART_CONTENT_KEYS}; found {present} (§4.1.6)")


# ---------------------------------------------------------------------------
# Artifacts — spec §4.1.7.
# ---------------------------------------------------------------------------
def validate_artifact(artifact: Any) -> ValidationResult:
    """Validate a task Artifact (spec §4.1.7)."""
    res = ValidationResult()
    if not isinstance(artifact, dict):
        return res.fail("artifact.not_an_object", "$", "Artifact must be an object")
    if not artifact.get("artifactId"):
        res.fail("artifact.missing_artifact_id", "$.artifactId",
                 "artifactId is required and must be unique within the task (§4.1.7)")
    parts = artifact.get("parts")
    if not isinstance(parts, list) or not parts:
        res.fail("artifact.no_parts", "$.parts",
                 "Artifact parts must contain at least one part (§4.1.7)")
    else:
        for i, part in enumerate(parts):
            _validate_part(part, f"$.parts[{i}]", res)
    return res


# ---------------------------------------------------------------------------
# Task lifecycle — spec §4.1.3 (states) + [BOOK RULE] transitions.
# ---------------------------------------------------------------------------
def validate_task_lifecycle(transitions: list[tuple[str, str, str]]) -> ValidationResult:
    """Validate a sequence of (task_id, old_state, new_state) observations.

    The spec defines the states and marks the terminals; the transition
    table is the book's own stricter rule (see ALLOWED_TRANSITIONS).
    Every rejection names the rule violated.
    """
    res = ValidationResult()
    for task_id, old, new in transitions:
        try:
            old_s, new_s = TaskState(old), TaskState(new)
        except ValueError:
            bad = old if old not in TaskState._value2member_map_ else new
            res.fail("task.unknown_state", f"$.tasks.{task_id}",
                     f"{bad!r} is not a TaskState (§4.1.3)")
            continue
        if old_s is TaskState.UNSPECIFIED:
            res.fail("task.unspecified_state", f"$.tasks.{task_id}",
                     "TASK_STATE_UNSPECIFIED is indeterminate and never a valid status (§4.1.3)")
            continue
        if old_s in TERMINAL_STATES:
            # Spec §3.1.1: messages sent to tasks in a terminal state
            # cannot be accepted; [BOOK RULE]: the state itself cannot move.
            res.fail("task.transition_from_terminal", f"$.tasks.{task_id}",
                     f"{old_s.value} is a terminal state (§4.1.3): "
                     f"the transition to {new_s.value} is refused")
            continue
        if new_s not in ALLOWED_TRANSITIONS[old_s]:
            res.fail("task.illegal_transition", f"$.tasks.{task_id}",
                     f"[BOOK RULE] transition {old_s.value} -> {new_s.value} "
                     "is not in the allowed transition table")
    return res
