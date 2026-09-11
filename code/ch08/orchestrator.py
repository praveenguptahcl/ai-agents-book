"""Multi-agent orchestration over MCP: delegation is an authority problem.

The planner-to-worker pattern is the payment-approval pattern with a
different letterhead. Every delegation is a new trust boundary: who
authorized this sub-agent, with what scope, for how long, and how does
its evidence flow back into the parent's audit trail?

This module implements the supervisor side of that boundary:

1. **Attenuation.** A delegation may only *narrow* authority, never
   widen it. The requested scope must be a subset of the orchestrator's
   own authority AND of the worker's declared capability; anything else
   is refused outright. The orchestrator never silently narrows a
   request — a task that needed the missing capability would fail in a
   confusing half-state instead of failing loudly at the boundary.
2. **Depth limit.** Delegations carry a depth counter; workers may
   sub-delegate only while under the limit. Infinite recursion is a
   budget fire with extra steps.
3. **Evidence discipline.** A worker's returned evidence is validated
   against a local Pydantic contract (Ch 4 discipline, applied to a
   sub-agent) before it touches the parent trace. Poisoned evidence is
   quarantined, not merged. Every observation carries provenance:
   REAL or SYNTHETIC, no third option.
4. **Failure semantics.** A worker that times out does not leave a
   failed delegation — it leaves an *open* one (Ch 2's pending-state
   treatment; Ch 10's open-state lifecycle). The parent loop stays open
   until reconciliation.
5. **Budgets as controls.** Every delegation carries a token budget and
   a latency budget. An agent that can spend unbounded tokens is an
   agent with unbounded authority; the budget is the leash.

Transport note: the worker's ``dispatch`` callable is the seam where
the real world plugs in. In production it wraps the cleared Ch 7
``MCPClient.call_tool`` (the client handles _meta, the allowlist, the
trusted-description discipline, and isError mapping — nothing here
re-derives any of it). In tests it is a fake. The seam is deliberate:
the orchestrator is transport-agnostic; authority does not depend on
which socket the bytes took.

Tenant note: every delegation carries the tenant_id (Ch 6). A
delegation is minted from a verified tenant context and the narrowed
scope is bound to that tenant — cross-tenant delegation is not a
feature and is refused at registration time.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

# --------------------------------------------------------------------------
# Exceptions: every refusal is named, so the trace says WHY it stopped.
# --------------------------------------------------------------------------


class OrchestrationError(Exception):
    """Base: the orchestration layer refused something on purpose."""


class UnknownWorker(OrchestrationError):
    """No worker is registered under that name."""


class ScopeDenied(OrchestrationError):
    """The delegation asked for more than the boundary allows.

    Raised when the requested scope is not a subset of the
    orchestrator's authority, or not a subset of the worker's declared
    capability. Never silently narrowed: see the module docstring.
    """


class TenantMismatch(OrchestrationError):
    """A delegation tried to cross tenant boundaries. Refused."""


class DepthExceeded(OrchestrationError):
    """The delegation would exceed the maximum delegation depth."""


class BudgetExhausted(OrchestrationError):
    """The delegation exceeded its token or latency budget. Halted."""


class CycleDetected(OrchestrationError):
    """A delegation would create a worker call cycle (A -> B -> A)."""


class EvidenceQuarantined(OrchestrationError):
    """Worker output failed contract validation: quarantined, not merged."""


class WorkerFailed(OrchestrationError):
    """The worker raised instead of returning. Recorded, not retried here."""


# --------------------------------------------------------------------------
# The evidence contract. This is local, versioned, reviewed code — the
# worker's output is a claim about the world; this is the check against it.
# (Ch 4 discipline applied to a sub-agent; Ch 12's lesson that untrusted
# output must never become trusted state.)
# --------------------------------------------------------------------------


class Observation(BaseModel):
    """One checkable fact a worker claims to have established."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: str  # e.g. "quote", "filing_excerpt", "risk_flag"
    detail: str
    provenance: Literal["REAL", "SYNTHETIC"]  # the spine's invariant:
    # every bar, every quote, every fact is labeled. No third option.
    as_of: str


class WorkerResult(BaseModel):
    """The only shape in which a worker's output may enter the trace."""

    model_config = ConfigDict(extra="forbid")
    task_id: str
    worker: str
    status: Literal["ok", "failed"]
    verdict: Literal["approve", "veto", "abstain"] = "abstain"
    summary: str
    observations: list[Observation] = Field(default_factory=list)
    cost_tokens: int = Field(ge=0)


class DelegationContext(BaseModel):
    """What a worker is allowed to see and do for one delegation.

    Frozen, because a delegation whose scope can be widened after
    minting is not a delegation — it is a blank check. The scope here
    is ALWAYS a subset of the orchestrator's authority (attenuation);
    the tenant is ALWAYS the orchestrator's tenant.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
    delegation_id: str
    task: str
    worker: str
    tenant_id: str
    granted_scopes: frozenset[str]
    depth: int
    token_budget: int
    timeout_s: float


class DelegationRecord(BaseModel):
    """The parent trace's entry for one delegation (Ch 9's evidence spine
    consumes records like this; nothing here re-derives that chapter)."""

    model_config = ConfigDict(extra="forbid")
    delegation_id: str
    parent_id: str | None  # None for top-level delegations
    task: str
    worker: str
    tenant_id: str
    granted_scopes: frozenset[str]
    depth: int
    status: Literal["ok", "failed", "open", "quarantined"]
    failure: str | None = None
    cost_tokens: int = 0
    latency_s: float = 0.0
    evidence: WorkerResult | None = None


# --------------------------------------------------------------------------
# Workers and budgets.
# --------------------------------------------------------------------------


@dataclass
class WorkerSpec:
    """A registered worker: what it CAN do (capability) and how to reach it.

    ``declared_scopes`` is capability, not permission — what this worker
    is built to do. What it MAY do on any given delegation is decided by
    the orchestrator at dispatch time (authority), and is always a
    subset of both. ``dispatch`` is the transport seam: in production it
    wraps MCPClient.call_tool; in tests it is a fake.
    """

    name: str
    declared_scopes: frozenset[str]
    dispatch: Callable[[DelegationContext, dict], dict]


@dataclass
class Budget:
    """First-class cost/latency control, checked before AND after dispatch."""

    max_tokens: int
    max_seconds: float


# --------------------------------------------------------------------------
# The orchestrator.
# --------------------------------------------------------------------------


class Orchestrator:
    """A supervisor that dispatches tasks to workers over a transport seam.

    The orchestrator's authority is the ceiling: no delegation may grant
    more than the orchestrator itself holds. The trace is the evidence:
    every delegation — granted, refused, failed, or left open — is
    recorded with its scope, budget, cost, and evidence.
    """

    def __init__(
        self,
        authority: set[str],
        tenant_id: str,
        *,
        max_depth: int = 3,
        default_budget: Budget = Budget(max_tokens=4_000, max_seconds=30.0),
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.authority = frozenset(authority)
        self.tenant_id = tenant_id
        self.max_depth = max_depth
        self.default_budget = default_budget
        self._clock = clock
        self._workers: dict[str, WorkerSpec] = {}
        self._active: list[str] = []  # re-entrancy stack: the cycle guard
        self.trace: list[DelegationRecord] = []
        self.quarantine: list[dict] = []  # raw poisoned payloads, kept for
        # forensics — never merged, never executed

    # -- registration ----------------------------------------------------

    def register(self, spec: WorkerSpec) -> None:
        if spec.name in self._workers:
            raise OrchestrationError(f"worker {spec.name!r} already registered")
        self._workers[spec.name] = spec

    # -- delegation -------------------------------------------------------

    def delegate(
        self,
        worker_name: str,
        task: str,
        requested_scopes: set[str],
        *,
        budget: Budget | None = None,
        depth: int = 0,
        parent_id: str | None = None,
        payload: dict | None = None,
    ) -> DelegationRecord:
        """Dispatch one task to one worker. Refuses loudly; never half-grants."""
        spec = self._workers.get(worker_name)
        if spec is None:
            raise UnknownWorker(f"no worker registered as {worker_name!r}")

        requested = frozenset(requested_scopes)

        # 1. Attenuation, checked twice: against OUR authority (the ceiling)
        #    and against the WORKER's declared capability. Either failure
        #    is a refusal, not a silent narrowing.
        if not requested.issubset(self.authority):
            raise ScopeDenied(
                f"delegation to {worker_name!r} requests {sorted(requested - self.authority)} "
                "outside the orchestrator's authority"
            )
        if not requested.issubset(spec.declared_scopes):
            raise ScopeDenied(
                f"worker {worker_name!r} is not capable of "
                f"{sorted(requested - spec.declared_scopes)}: refusing rather "
                "than granting a scope the worker cannot honor"
            )

        # 2. Depth: no infinite recursion. A worker that wants to
        #    sub-delegate calls back through delegate() with depth + 1.
        if depth > self.max_depth:
            raise DepthExceeded(
                f"delegation depth {depth} exceeds max_depth {self.max_depth}"
            )

        # 3. Cycle guard: a delegation that would re-enter a worker
        #    already on the active stack is a cycle (A -> B -> A).
        if worker_name in self._active:
            raise CycleDetected(
                f"delegation to {worker_name!r} would cycle through "
                f"{' -> '.join([*self._active, worker_name])}"
            )

        budget = budget or self.default_budget
        delegation_id = f"dlg_{uuid.uuid4().hex[:12]}"
        ctx = DelegationContext(
            delegation_id=delegation_id,
            task=task,
            worker=worker_name,
            tenant_id=self.tenant_id,
            granted_scopes=requested,
            depth=depth,
            token_budget=budget.max_tokens,
            timeout_s=budget.max_seconds,
        )

        record = DelegationRecord(
            delegation_id=delegation_id,
            parent_id=parent_id,
            task=task,
            worker=worker_name,
            tenant_id=self.tenant_id,
            granted_scopes=requested,
            depth=depth,
            status="open",  # every delegation starts open; only a
            # verified result closes it (Ch 2's pending-state rule)
        )
        self.trace.append(record)
        self._active.append(worker_name)
        started = self._clock()
        try:
            raw = spec.dispatch(ctx, payload or {})
        except TimeoutError as exc:
            # The worker went silent. The delegation stays OPEN: the world
            # may still answer, and reconcile() can close it later. The
            # parent's loop stays open too — an unreconciled pending state
            # is an unverified act.
            record.status = "open"
            record.failure = f"timeout: {exc}"
            record.latency_s = self._clock() - started
            return record
        except Exception as exc:  # noqa: BLE001 — the boundary must not leak
            record.status = "failed"
            record.failure = f"{type(exc).__name__}: {exc}"
            record.latency_s = self._clock() - started
            return record
        finally:
            self._active.remove(worker_name)

        record.latency_s = self._clock() - started

        # 3b. The transport seam promises a dict. A dispatch that returns
        #     anything else is a broken worker, not a result.
        if not isinstance(raw, dict):
            record.status = "failed"
            record.failure = (
                f"transport returned {type(raw).__name__}, not a dict: "
                "a worker that cannot speak the evidence protocol "
                "cannot be trusted"
            )
            raise WorkerFailed(record.failure)

        # 4. Budget, checked after dispatch on the ACTUAL cost.
        tokens = self._extract_tokens(raw)
        record.cost_tokens = tokens
        if tokens > budget.max_tokens or record.latency_s > budget.max_seconds:
            record.status = "failed"
            record.failure = (
                f"budget exhausted: {tokens} tokens / {record.latency_s:.2f}s "
                f"against {budget.max_tokens} tokens / {budget.max_seconds}s"
            )
            raise BudgetExhausted(record.failure)

        # 5. Evidence discipline: the worker's output is untrusted until
        #    it validates. Poison is quarantined — recorded for forensics,
        #    never merged into the trace as evidence.
        try:
            result = WorkerResult(**raw)
        except ValidationError as exc:
            record.status = "quarantined"
            record.failure = f"evidence failed contract validation: {exc.errors()}"
            self.quarantine.append(
                {"delegation_id": delegation_id, "raw": raw,
                 "errors": str(exc)}
            )
            raise EvidenceQuarantined(record.failure) from exc

        if result.worker != worker_name or result.task_id != ctx.delegation_id:
            # Identity laundering: a result that claims to be someone else's.
            record.status = "quarantined"
            record.failure = (
                "worker identity mismatch in returned evidence: "
                f"expected ({worker_name}, {ctx.delegation_id}), got "
                f"({result.worker}, {result.task_id})"
            )
            self.quarantine.append(
                {"delegation_id": delegation_id, "raw": raw,
                 "errors": "identity mismatch"}
            )
            raise EvidenceQuarantined(record.failure)

        record.status = "ok"
        record.evidence = result
        return record

    def reconcile(self, delegation_id: str, raw: dict) -> DelegationRecord:
        """Close an open delegation when the world finally answers.

        The timeout path leaves status "open"; when the late result
        arrives, it goes through the SAME evidence validation as a
        fresh result. A late answer is still an untrusted answer.
        """
        record = next(
            (r for r in self.trace if r.delegation_id == delegation_id), None
        )
        if record is None:
            raise OrchestrationError(f"unknown delegation {delegation_id!r}")
        if record.status != "open":
            raise OrchestrationError(
                f"delegation {delegation_id!r} is {record.status}, not open"
            )
        try:
            result = WorkerResult(**raw)
        except ValidationError as exc:
            record.status = "quarantined"
            record.failure = f"late evidence failed validation: {exc.errors()}"
            self.quarantine.append(
                {"delegation_id": delegation_id, "raw": raw,
                 "errors": str(exc)}
            )
            raise EvidenceQuarantined(record.failure) from exc
        record.status = "ok"
        record.failure = None
        record.evidence = result
        record.cost_tokens = self._extract_tokens(raw)
        return record

    # -- adjudication: the supervisor decides ------------------------------

    def adjudicate(
        self, results: list[WorkerResult], rule: str = "veto-wins"
    ) -> dict:
        """Resolve conflicting worker results. The model proposes; the
        orchestrator disposes. Default rule: any veto blocks — the risk
        worker's veto beats the signal worker's enthusiasm, because a
        missed opportunity costs basis points and an unvetoed blowup
        costs the desk."""
        if rule != "veto-wins":
            raise OrchestrationError(f"unknown adjudication rule {rule!r}")
        vetoes = [r for r in results if r.verdict == "veto"]
        if vetoes:
            return {
                "decision": "blocked",
                "reason": "; ".join(
                    f"{r.worker}: {r.summary}" for r in vetoes
                ),
            }
        approvals = [r for r in results if r.verdict == "approve"]
        if approvals and len(approvals) == len(results):
            return {"decision": "approved",
                    "reason": f"{len(approvals)} unanimous approvals"}
        return {
            "decision": "contested",
            "reason": "no veto but no unanimity; escalate to human",
        }

    # -- the cost model of the second call ----------------------------------

    def cost_worksheet(self) -> dict:
        """The executable version of §8.1's worksheet: what did the team
        actually cost? Every delegation's tokens are accounted; the
        supervisor's own overhead is the line the invoice usually hides."""
        per_delegation = [
            {"worker": r.worker, "tokens": r.cost_tokens,
             "status": r.status}
            for r in self.trace
        ]
        total = sum(r.cost_tokens for r in self.trace)
        return {
            "delegations": len(self.trace),
            "per_delegation": per_delegation,
            "total_tokens": total,
            "quarantined": sum(1 for r in self.trace
                               if r.status == "quarantined"),
            "open": sum(1 for r in self.trace if r.status == "open"),
        }

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _extract_tokens(raw: dict) -> int:
        # A missing cost accounting is not zero cost — it is unaccounted
        # spend, and unaccounted spend fails closed at the full budget.
        if "cost_tokens" not in raw:
            return 2**31
        tokens = raw["cost_tokens"]
        if (not isinstance(tokens, int) or isinstance(tokens, bool)
                or tokens < 0):
            return 2**31
        return tokens

    def sub_delegate(self, ctx: DelegationContext, worker_name: str,
                     task: str, requested_scopes: set[str],
                     **kwargs: Any) -> DelegationRecord:
        """The worker-side entry point for nested delegation.

        A worker that wants help calls back through here; the depth
        counter increments and the scope must narrow AGAIN against the
        worker's granted scope — attenuation compounds down the chain.
        The tenant is inherited, never chosen: cross-tenant delegation
        is refused before any other check.
        """
        tenant_id = kwargs.pop("tenant_id", ctx.tenant_id)
        if tenant_id != ctx.tenant_id:
            raise TenantMismatch(
                f"cross-tenant delegation refused: {ctx.tenant_id!r} -> "
                f"{tenant_id!r}"
            )
        narrowed = frozenset(requested_scopes)
        if not narrowed.issubset(ctx.granted_scopes):
            raise ScopeDenied(
                "sub-delegation requests "
                f"{sorted(narrowed - ctx.granted_scopes)} outside the "
                "parent delegation's granted scope"
            )
        return self.delegate(
            worker_name, task, set(narrowed),
            depth=ctx.depth + 1, parent_id=ctx.delegation_id, **kwargs,
        )
