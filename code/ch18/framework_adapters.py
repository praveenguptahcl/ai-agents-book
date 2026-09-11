"""Enforce the book's ODAV discipline on off-the-shelf agent frameworks.

Chapter 18. Most enterprises will not rewrite their stack. They have
LangChain / LlamaIndex / AG2-style tools in production *today* — stringly
typed, trusting their inputs, invisible to the audit trail. This module is
the strangler pattern for agent systems: wrap first, replace gradually.

The adapter enforces five disciplines on every wrapped tool call, in order:

  1. REGISTRATION (Ch 4): an unwrapped tool cannot be called, period.
     Authority comes from the registry, not from the framework.
  2. CONTRACT (Ch 4): raw arguments are validated by a Pydantic schema
     *before* dispatch. The legacy function never sees unvalidated input.
  3. TENANT (Ch 6): the call carries a verified session; the scope check
     runs before the contract check, because authority precedes shape.
  4. APPROVAL (Ch 19 preview): high-risk actions pause for a human.
  5. OUTPUT REVIEW (Ch 12) + EVIDENCE (Ch 9): the tool's output is
     reviewed before it reaches the planner, and every decision — allowed
     or refused — is emitted as an evidence-shaped record.

Design honesty: this module has NO dependency on langchain, llama-index,
or any framework. It wraps framework tools behind injected callables, so
the seams are explicit:

  - ``session_verifier(session, action)`` — the Ch 6 seam. There is NO
    default: an adapter without an authority source refuses every call.
    Failing closed here is the point.
  - ``output_reviewer(text)`` — the Ch 12 seam. The default is a minimal,
    documented heuristic (blocks obvious exfiltration markers). Production
    wires the real DefendedPipeline; the default exists so the module is
    runnable and honest about what it is.

Standard library + pydantic only.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


# ---------------------------------------------------------------------------
# Errors: every refusal is typed, so callers can distinguish them.
# ---------------------------------------------------------------------------

class AdapterError(Exception):
    """Base class for all adapter refusals."""


class UnwrappedToolRefused(AdapterError):
    """The framework tried to call a tool that was never registered."""


class NoAuthoritySource(AdapterError):
    """The adapter has no session verifier configured; all calls refused."""


class ScopeDenied(AdapterError):
    """The session verifier rejected the session for this action."""


class ContractViolation(AdapterError):
    """Raw arguments failed Pydantic validation; the legacy fn was not called."""


class ApprovalRequired(AdapterError):
    """A high-risk action needs a human approval ticket first."""


class ApprovalInvalid(AdapterError):
    """The approval ticket is missing, expired, or for a different action."""


class OutputBlocked(AdapterError):
    """The tool's output failed review; it never reaches the planner."""


class ToolExecutionError(AdapterError):
    """The wrapped legacy function raised; wrapped, never leaked raw."""


# ---------------------------------------------------------------------------
# Risk tiers: the approval policy keys off these, not off vibes.
# ---------------------------------------------------------------------------

class RiskTier(str, Enum):
    READ = "read"              # no external effect; no approval needed
    WRITE = "write"            # reversible external effect; approval required
    IRREVERSIBLE = "irreversible"  # cannot be undone; approval + receipt


# ---------------------------------------------------------------------------
# The legacy tool: what the framework gives you. Stringly typed, trusting.
# ---------------------------------------------------------------------------

@dataclass
class LegacyTool:
    """A tool as an off-the-shelf framework sees it.

    ``fn`` takes whatever the framework hands it — usually strings, dicts,
    or None — and returns whatever it feels like. It has no schema, no
    session, no review. This is the thing we are strangling.
    """
    name: str
    fn: Callable[..., Any]
    description: str = ""


# ---------------------------------------------------------------------------
# The contract: what the adapter demands before the legacy fn may run.
# ---------------------------------------------------------------------------

@dataclass
class ToolRegistration:
    """One wrapped tool: the legacy callable plus the discipline around it.

    ``adapt`` translates the validated contract model into the legacy
    function's calling convention: ``adapt(bound) -> (args, kwargs)``.
    The translation lives in the adapter — never in the framework, never
    in the legacy function — so the seam is visible and reviewable.
    """
    legacy: LegacyTool
    contract: type[BaseModel]          # Pydantic model validating raw args
    risk: RiskTier
    allowed_scopes: frozenset[str] = frozenset()
    adapt: Callable[[BaseModel], tuple[tuple, dict]] = field(
        default_factory=lambda: (lambda m: ((), m.model_dump()))
    )


# ---------------------------------------------------------------------------
# Evidence: every decision, allowed or refused, leaves this shape behind.
# (Shaped for Ch 9's spine; this module does not re-derive the chain.)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EvidenceRecord:
    ts: float
    tenant_id: str
    tool: str
    args_digest: str          # sha256 of canonical args — never raw args
    verdict: str              # allowed | refused:<reason>
    approver: Optional[str] = None


# ---------------------------------------------------------------------------
# Approval tickets: high-risk actions pause here.
# ---------------------------------------------------------------------------

@dataclass
class ApprovalTicket:
    ticket_id: str
    tool: str
    args_digest: str
    requested_by: str
    requested_at: float
    expires_at: float
    approver: Optional[str] = None


# ---------------------------------------------------------------------------
# The default output reviewer: minimal, documented, honest about its limits.
# ---------------------------------------------------------------------------

_EXFIL_MARKERS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"https?://[^\s'\"]*(webhook|exfil|attacker)[^\s'\"]*", re.I),
    re.compile(r"\bUNAPPROVED_ENDPOINT\b"),
)


def _default_output_reviewer(text: str) -> Optional[str]:
    """Return a reason string if the output must be blocked, else None.

    This is a *demonstration* reviewer, not a security boundary: it catches
    obvious exfiltration markers so the module is runnable standalone.
    Production deployments replace it with Ch 12's DefendedPipeline.
    """
    for marker in _EXFIL_MARKERS:
        if marker.search(text):
            return f"output matched exfiltration marker: {marker.pattern[:40]}"
    return None


# ---------------------------------------------------------------------------
# The adapter.
# ---------------------------------------------------------------------------

class FrameworkAdapter:
    """Wrap framework tools in the book's discipline.

    The five checks run in a fixed order on every call:

      1. registered?          (no registry entry -> UnwrappedToolRefused)
      2. authority?           (session_verifier -> ScopeDenied; none configured
                               -> NoAuthoritySource)
      3. contract?            (Pydantic validation -> ContractViolation)
      4. approval?            (WRITE/IRREVERSIBLE need a live ticket ->
                               ApprovalRequired)
      5. output review        (reviewer flags output -> OutputBlocked)

    Only then does the legacy function run, and its result is reviewed
    before it is returned. Every path emits an EvidenceRecord.
    """

    APPROVAL_TTL_S = 600.0

    def __init__(
        self,
        session_verifier: Optional[Callable[[Any, str], str]] = None,
        output_reviewer: Callable[[str], Optional[str]] = _default_output_reviewer,
    ) -> None:
        """Create an adapter.

        ``session_verifier(session, action)`` must return the tenant id for a
        valid session or raise ScopeDenied. If it is None, the adapter refuses
        every call — an adapter must never invent authority.
        """
        self._registry: dict[str, ToolRegistration] = {}
        self._session_verifier = session_verifier
        self._output_reviewer = output_reviewer
        self._tickets: dict[str, ApprovalTicket] = {}
        self.evidence: list[EvidenceRecord] = []

    # -- registration ----------------------------------------------------

    def register(
        self,
        legacy: LegacyTool,
        contract: type[BaseModel],
        risk: RiskTier,
        allowed_scopes: frozenset[str] = frozenset(),
        adapt: Optional[Callable[[BaseModel], tuple[tuple, dict]]] = None,
    ) -> None:
        if not (isinstance(contract, type) and issubclass(contract, BaseModel)):
            raise TypeError("contract must be a Pydantic BaseModel subclass")
        self._registry[legacy.name] = ToolRegistration(
            legacy=legacy, contract=contract, risk=risk,
            allowed_scopes=allowed_scopes,
            adapt=adapt or (lambda m: ((), m.model_dump())),
        )

    # -- approvals -------------------------------------------------------

    def request_approval(self, session: Any, tool: str, raw_args: Any,
                         requested_by: str) -> str:
        """Open an approval ticket. Returns the ticket id.

        The ticket binds to the *digest* of the proposed arguments: approving
        one payload does not approve a different payload. Session and
        arguments are validated HERE, at request time — an approval ticket
        must never be issued to an unauthenticated caller or for a payload
        that fails the contract, or the queue becomes a forgery factory.
        """
        reg = self._registry.get(tool)
        if reg is None:
            raise UnwrappedToolRefused(f"tool not registered: {tool!r}")
        if self._session_verifier is None:
            raise NoAuthoritySource("no session verifier configured")
        try:
            self._session_verifier(session, tool)
        except Exception as exc:
            raise ScopeDenied(f"session verifier failed: {exc}") from exc

        try:
            reg.contract.model_validate(raw_args)
        except ValidationError as exc:
            raise ContractViolation(
                f"arguments failed contract for {tool!r}: {exc.errors()}"
            ) from exc

        digest = _digest(raw_args)
        ticket_id = uuid.uuid4().hex
        now = time.time()
        self._tickets[ticket_id] = ApprovalTicket(
            ticket_id=ticket_id, tool=tool, args_digest=digest,
            requested_by=requested_by, requested_at=now,
            expires_at=now + self.APPROVAL_TTL_S,
        )
        return ticket_id

    def approve(self, ticket_id: str, approver: str) -> None:
        ticket = self._tickets.get(ticket_id)
        if ticket is None:
            raise ApprovalInvalid("unknown approval ticket")
        if time.time() > ticket.expires_at:
            del self._tickets[ticket_id]
            raise ApprovalInvalid("approval ticket expired")
        ticket.approver = approver

    def _consume_ticket(self, tool: str, digest: str) -> Optional[str]:
        """Find a live, approved ticket bound to this exact (tool, digest)."""
        for ticket_id, ticket in list(self._tickets.items()):
            if time.time() > ticket.expires_at:
                del self._tickets[ticket_id]
                continue
            if ticket.approver and ticket.tool == tool \
                    and ticket.args_digest == digest:
                del self._tickets[ticket_id]   # single use
                return ticket.approver
        return None

    # -- the guarded call -------------------------------------------------

    def call(self, session: Any, tool: str, raw_args: Any) -> Any:
        """Run a framework tool call through all five checks."""
        reg = self._registry.get(tool)
        if reg is None:
            self._record("unknown", tool, raw_args, "refused:unregistered")
            raise UnwrappedToolRefused(
                f"tool {tool!r} is not registered; the framework may not "
                "call tools the adapter has not wrapped"
            )

        if self._session_verifier is None:
            self._record("unknown", tool, raw_args, "refused:no-authority")
            raise NoAuthoritySource(
                "no session verifier configured; refusing all calls"
            )
        try:
            tenant_id = self._session_verifier(session, tool)
        except ScopeDenied:
            self._record("unknown", tool, raw_args, "refused:scope")
            raise
        except Exception as exc:  # a verifier that crashes denies, loudly
            self._record("unknown", tool, raw_args, "refused:verifier-error")
            raise ScopeDenied(f"session verifier failed: {exc}") from exc

        try:
            bound = reg.contract.model_validate(raw_args)
        except ValidationError as exc:
            self._record(tenant_id, tool, raw_args, "refused:contract")
            raise ContractViolation(
                f"arguments failed contract for {tool!r}: {exc.errors()}"
            ) from exc

        digest = _digest(raw_args)
        approver: Optional[str] = None
        if reg.risk in (RiskTier.WRITE, RiskTier.IRREVERSIBLE):
            approver = self._consume_ticket(tool, digest)
            if approver is None:
                self._record(tenant_id, tool, raw_args, "refused:approval")
                raise ApprovalRequired(
                    f"{tool!r} is {reg.risk.value}; request_approval() first"
                )

        try:
            args, kwargs = reg.adapt(bound)
            result = reg.legacy.fn(*args, **kwargs)
        except AdapterError:
            raise
        except Exception as exc:
            self._record(tenant_id, tool, raw_args, "refused:tool-error",
                         approver)
            raise ToolExecutionError(f"wrapped tool {tool!r} raised") from exc

        rendered = result if isinstance(result, str) else json.dumps(
            result, sort_keys=True, default=str)
        block_reason = self._output_reviewer(rendered)
        if block_reason is not None:
            self._record(tenant_id, tool, raw_args, "refused:output",
                         approver)
            raise OutputBlocked(
                f"output of {tool!r} failed review: {block_reason}"
            )

        self._record(tenant_id, tool, raw_args, "allowed", approver)
        return result

    # -- evidence ----------------------------------------------------------

    def _record(self, tenant_id: str, tool: str, raw_args: Any,
                verdict: str, approver: Optional[str] = None) -> None:
        self.evidence.append(EvidenceRecord(
            ts=time.time(),
            tenant_id=tenant_id,
            tool=tool,
            args_digest=_digest(raw_args),
            verdict=verdict,
            approver=approver,
        ))


def _digest(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, default=str,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


# ---------------------------------------------------------------------------
# The worked example: the desk's legacy finance tool.
#
# This is what "worked fine" looks like in production: a LangChain-style
# tool with no schema, stringly-typed arguments, and total trust in its
# inputs — and, on a bad day, in its outputs.
# ---------------------------------------------------------------------------

def legacy_dump_positions(args_json: str = "{}") -> str:
    """Legacy finance tool: dump the desk's positions as CSV-ish text.

    Takes an optional JSON blob of filters. Returns a string. Trusts
    everything. This is the tool the adapter is strangling.
    """
    try:
        filters = json.loads(args_json) if args_json else {}
    except Exception:
        filters = {}
    rows = [
        "symbol,qty,side",
        "AAPL,1200,long",
        "MSFT,800,long",
        "NVDA,-400,short",
    ]
    out = "\n".join(rows)
    # The incident: a "helpful" new code path appends a callback URL when a
    # filter key is present. Nobody reviewed it. The string goes wherever
    # the planner pastes it.
    if filters.get("notify"):
        out += f"\ncallback:{filters['notify']}"
    return out


class DumpPositionsArgs(BaseModel):
    """The contract the legacy tool never had."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    notify: Optional[str] = Field(
        default=None,
        description="Callback URL, if any. Must be an approved desk "
                    "endpoint; anything else is refused at the contract, "
                    "before the legacy function ever runs.",
    )

    @field_validator("notify")
    @classmethod
    def _notify_must_be_desk_endpoint(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not v.startswith("https://desk.internal/"):
            raise ValueError(
                "notify must be an approved desk endpoint "
                "(https://desk.internal/…)"
            )
        return v
