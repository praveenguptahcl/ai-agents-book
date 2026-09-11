# Chapter 8 — Multi-Agent Systems: Orchestration over MCP

**Thesis thread:** Capability is what a system *can* do; authority is
what it *may* do. That distinction, which has carried every chapter so
far, gets its hardest test the moment one agent calls another. A
single agent's authority is a boundary you drew once. A team of
agents' authority is a boundary you must re-draw at every delegation —
because every delegation is a new trust boundary, and trust does not
transit.

This chapter is Part III's missing keystone. Agents composed as
capabilities of other agents: the orchestrator-worker pattern, the
topologies it competes with, and the discipline that keeps a team of
agents from becoming a team of confused deputies.

> **Figure 8.1** — Orchestration topology and delegation scope
> (one-line reference; full spec in `figs/ch08-figspec.md`).

---

## 8.1 The second call is the expensive one

Every multi-agent pitch starts with a division of labor that sounds
obvious: the signal agent finds opportunities, the research agent reads
filings, the risk agent checks the math. Three specialists, each better
at its job than one generalist. The pitch is not wrong. It is
incomplete, because it prices the first call and forgets the second.

The first call — one agent doing one task — costs what the invoice
says: tokens in, tokens out, latency of one round trip. The second
call, the delegation, costs everything the invoice hides:

- **The authority question.** Who authorized this sub-agent, with what
  scope, for how long? A delegation without a recorded grant is a
  permission that cannot be audited — and Ch 1 taught us what
  unauditable permissions do at 4:47 on a Friday.
- **The evidence question.** How does the sub-agent's work flow back
  into the parent's audit trail? If the research worker's quote enters
  the trace as trusted fact, you have built a pipeline for laundering
  untrusted input into trusted state — the exact attack Ch 12
  quarantines at the prompt boundary, now arriving through the org
  chart.
- **The failure question.** What happens when the worker dies
  mid-delegation? A single agent that crashes leaves one open loop. A
  supervisor with four dead workers leaves four open loops and a parent
  that must decide what "done" means without them.
- **The money question.** Two agents cost at least twice the tokens,
  plus the supervisor's own overhead: the delegation prompts, the
  adjudication prompts, the retries. An unbounded team is an unbounded
  invoice, and an agent that can spend unbounded tokens is an agent
  with unbounded authority.

None of this is an argument against multi-agent systems. It is the
price of admission, stated honestly, before the architecture. The
skeptical benchmark every team must survive is simple: **does the team
beat the best single agent on the same task, measured on verified
outcomes per dollar, not on vibes?** If the answer is no, the correct
multi-agent architecture is one agent. (This is the first instance of
the book's recurring comparative table — §8.3 — and its recurring
lesson: the least autonomous system that reliably works.)

---

## 8.2 The substrate: production MCP in five paragraphs

The orchestrator in this chapter dispatches over MCP — the protocol
Ch 7 specified correctly — and production use demands five things the
spec leaves to you. This section is deliberately short: it consumes
Ch 7, it does not re-derive it.

**Authentication.** MCP's `_meta` carries client identity, but identity
is a claim, not a proof. In production, the transport underneath is
mutually authenticated (mTLS or equivalent), and the server maps the
transport identity to a tenant before any tool listing is served. An
unauthenticated MCP server on an internal network is a tool-dispensing
machine for anyone who finds the port — the confused deputy of §8.4,
wearing a server badge.

**Reconnection and backoff.** stdio transports die; TCP transports die
louder. The client owns reconnection: exponential backoff with jitter,
a cap on attempts, and — critically — idempotency keys on every
`tools/call` so a retried call after a dropped connection does not
execute twice. (Ch 10's idempotent runner is the other end of this
contract.)

**Multi-server multiplexing.** One host, many clients, many servers:
the market-data server, the fundamentals server, the risk server. The
host multiplexes them and must keep their namespaces apart.

**Namespace collisions.** Two servers can advertise a tool named
`get_quote` with different semantics — one returns a live quote, one
returns yesterday's close labeled as live. The host qualifies every
tool name with its server (`fundamentals.get_quote`), and the local
contract (§7.4) is written against the qualified name. An unqualified
name in a multi-server world is a name you do not control.

**Version drift.** Servers upgrade; their `inputSchema` widens; your
frozen local contract still validates against the old shape. The
client re-runs `server/discover` and `tools/list` on reconnect and
re-validates every contract before the first call. A contract that
validated last Tuesday is a rumor, not a guarantee.

With the substrate stated, the chapter earns its number: orchestration.

---

## 8.3 Three topologies, one table

Multi-agent systems come in three shapes, and the shape decides where
authority lives.

**Supervisor (orchestrator-worker).** One agent dispatches, workers
execute, the supervisor adjudicates. Authority is centralized: every
delegation is an explicit grant, every result returns to one
decision-maker. This is the pattern this chapter implements, because
it is the pattern where the authority accounting is tractable. Its
failure mode is the supervisor itself — a compromised or confused
supervisor is a single point of authority failure, which is why its
own scope is the ceiling (§8.5) and why Ch 11's kill switches sit above
it, not inside it.

**Hierarchical.** Supervisors supervise supervisors. The org chart
gains depth; each level attenuates authority further (§8.4). The
failure mode is telephone: intent degrades with every hop, and
debugging requires the full chain. Depth limits (§8.5) are not
optional here — they are the only thing between a hierarchy and a
fork bomb.

**Peer / market.** Agents negotiate as equals: bidding, contracting,
voting. No one is in charge, which means no one can answer Maya's
second question — *who said so?* Peer topologies need a constitution
(usually a smart contract or a shared ledger) to make authority
legible, and they need cycle detection as a first-class feature,
because A delegating to B delegating to A is the normal case, not the
edge case. This chapter's cycle guard (§8.7) is the minimal version of
that discipline.

The comparative table, which recurs in Ch 14 and Ch 18:

| Dimension | Deterministic workflow | Single agent | Multi-agent team | Human team |
|---|---|---|---|---|
| Reliability | Highest (no judgment calls) | Medium (one mind, one failure) | Medium-high *if* adjudicated | Variable (fatigue, turnover) |
| Cost | Lowest | One inference bill | N bills + supervisor overhead | Salaries |
| Latency | Lowest | One round trip | Slowest (fan-out + adjudicate) | Slowest of all |
| Flexibility | Lowest (brittle to novelty) | High | Highest (specialists) | Highest |
| Security surface | Smallest | One authority boundary | One boundary *per delegation* | Social engineering |
| Debuggability | Trivial (replay the log) | Hard (one opaque mind) | Hardest (N opaque minds + interactions) | Postmortems |
| Human burden | None | Oversight of one | Oversight of the supervisor | Management |

Read the table the way the book keeps insisting: **start at the left
and move right only when the left column cannot do the job.** A
deterministic workflow that handles the task is not unambitious — it
is the most reliable system you can build. The team is the last
resort, not the first demo.

---

## 8.4 The attenuation principle

Here is the chapter's central claim, stated as a law:

> **Every hop down the delegation chain narrows authority. A
> delegation may grant a subset of what the granter holds — never a
> superset, never a lateral move, never "the same, plus this one
> thing."**

This is the attenuation principle, and it is the multi-agent version
of Ch 6's tenant sessions: a narrowed HMAC session, minted for one
delegation, bound to one tenant, carrying the granted scope in signed
bytes. The orchestrator in §8.5 never hands a worker its own session.
It mints a smaller one.

Attenuation exists because of the **confused deputy between agents**.
The classic confused deputy is a program tricked into misusing its
authority on behalf of a less-privileged caller. Between agents, the
deputy multiplies: the research worker, holding a read scope, is asked
by a compromised peer to "just check" something that requires a write
scope — and the worker, being helpful, complies, because nothing in
its context marks the request as beyond its grant. The defense is the
same as Ch 4's tool contracts and Ch 9's evidence discipline, applied
one level up:

- **Contracts at the agent boundary.** A worker's output is validated
  against a local Pydantic contract before it enters the parent trace
  — the server's description was untrusted in Ch 7, and the worker's
  summary is untrusted here. Same law, different letterhead.
- **Evidence at the agent boundary.** Observations carry provenance
  (REAL or SYNTHETIC — the spine's invariant, no third option), and
  poisoned evidence is quarantined, never merged. Ch 12's lesson, now
  enforced between colleagues instead of at the prompt edge.
- **Identity at the agent boundary.** A result that claims to come
  from a different worker than the one dispatched is identity
  laundering, and it is quarantined on sight.

One more rule, and it is the one teams get wrong most often: **the
orchestrator never silently narrows a request.** If a delegation asks
for more than the boundary allows, the answer is a refusal, not a
smaller grant. A task that needed the missing capability would fail in
a confusing half-state — three workers done, one silently
unauthorized — instead of failing loudly at the boundary where the
fix is obvious. Fail closed, at every hop.

---

## 8.5 The orchestrator

The module is `code/ch08/orchestrator.py`. Its design starts from a
refusal to be plumbing: the transport is a seam (in production, the
cleared Ch 7 `MCPClient.call_tool`; in tests, a fake), and everything
the module *is* lives in the five checks of `delegate()`.

Registration is the easy part — a name, a declared capability, a
dispatch function:

```python
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
```

The `DelegationContext` is the narrowed grant — frozen, because a
delegation whose scope can be widened after minting is a blank check:

```python
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
```

Note the tenant field: the delegation inherits the orchestrator's
tenant (Ch 6) — it is never chosen by the worker, and a sub-delegation
that names a different tenant is refused before any other check. There
is no cross-tenant delegation feature, because there must not be.

Then `delegate()`, the heart of the module. Five checks, in order —
and the order is the pedagogy:

1. **Attenuation, checked twice.** The requested scope must be a
   subset of the orchestrator's authority (the ceiling) *and* a subset
   of the worker's declared capability. Either failure raises
   `ScopeDenied`. No silent narrowing — ever.
2. **Depth.** The delegation counter must stay under `max_depth`.
   `DepthExceeded` otherwise. Hierarchies without depth limits are
   fork bombs with good intentions.
3. **Cycle guard.** If the worker is already on the active delegation
   stack, the delegation would create a cycle (A → B → A) and is
   refused with the cycle path in the error. Peer topologies live or
   die on this check.
4. **Budget, on the actual cost.** After dispatch, the real token
   spend and real latency are measured against the delegation's
   budget. Exhaustion raises `BudgetExhausted` — the runaway is
   halted, and the trace says exactly which budget broke.
5. **Evidence validation.** The worker's output is validated against
   `WorkerResult` before it touches the trace (§8.6).

Every delegation starts with status `"open"` and only a verified
result closes it — Ch 2's pending-state rule, enforced in code. The
trace records grants, refusals, failures, and open loops alike,
because the audit trail that only records successes is a marketing
document.

---

## 8.6 Evidence across the boundary

A worker's output is untrusted input wearing a colleague's name
badge. The evidence contract treats it accordingly:

```python
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
```

Three quarantines, each tested:

- **Shape poison.** An extra field (`execute_now: true` smuggled into
  the result), a wrong type, an invented provenance — `extra="forbid"`
  and the `Literal` types reject them, the payload goes to
  `orchestrator.quarantine` for forensics, and the trace records
  `"quarantined"`, never `"ok"`. The poison is kept — incident
  responders need the murder weapon — but it is never merged and
  never executed.
- **Identity laundering.** A result whose `worker` or `task_id` does
  not match the delegation that produced it is quarantined on sight.
  In a multi-worker world, "I am the risk worker" is a claim, and
  claims are checked.
- **Unaccounted spend.** A result with no `cost_tokens` — or a
  non-integer, or a negative — is treated as having spent its entire
  budget. A worker that cannot account for its own cost has spent too
  much. This is the cost discipline of §8.8, enforced at the evidence
  boundary rather than in a dashboard.

The merged evidence lands in a `DelegationRecord` — the parent trace's
entry, shaped for Ch 9's evidence spine to consume without
re-derivation. (That non-overlap contract is load-bearing: Ch 9 built
the spine; this chapter feeds it.)

---

## 8.7 Failure semantics

Single-agent failure modes are well understood: the model errs, the
tool fails, the loop retries. Team failure modes are combinatorial,
and they need names before they need handling. The module implements
four:

**Timeout → open, not failed.** A worker that goes silent leaves the
delegation `"open"`. The world may still answer — the filing may
still arrive, the quote may still print — and `reconcile()` closes
the loop when it does, running the *same* evidence validation as a
fresh result. A late answer is still an untrusted answer. This is Ch
2's pending-state treatment and Ch 10's open-state lifecycle,
composed: the parent's loop stays open until the world confirms, and
"unreconciled" is a first-class status the on-call runbook (Ch 14)
can see.

```python
    def reconcile(self, delegation_id: str, raw: dict) -> DelegationRecord:
        """Close an open delegation when the world finally answers.

        The timeout path leaves status "open"; when the late result
        arrives, it goes through the SAME evidence validation as a
        fresh result. A late answer is still an untrusted answer.
        """
```

**Crash → recorded, not retried here.** A worker that raises gets
status `"failed"` with the exception type in the record. Retry policy
belongs to the supervisor's policy layer (and Ch 10's executor), not
to the delegation primitive — the primitive's job is to tell the
truth about what happened.

**Partial completion → the supervisor decides.** When three workers
return and one is still open, the delegation set is incomplete, and
incompleteness is a decision, not a default. That decision is
`adjudicate()`:

```python
    def adjudicate(
        self, results: list[WorkerResult], rule: str = "veto-wins"
    ) -> dict:
        """Resolve conflicting worker results. The model proposes; the
        orchestrator disposes. Default rule: any veto blocks — the risk
        worker's veto beats the signal worker's enthusiasm, because a
        missed opportunity costs basis points and an unvetoed blowup
        costs the desk."""
```

The default rule is `veto-wins`: any veto blocks the action, unanimity
approves, and anything in between is `"contested"` — which escalates
to a human (Ch 19's risk-based escalation owns that handoff). The
rule is explicit and replaceable, because "the supervisor decided" is
only an acceptable answer when the decision procedure is written
down.

**Cycles → refused with the path.** The re-entrancy stack makes A →
B → A a `CycleDetected` naming every hop. In a peer topology this is
not an edge case; it is Tuesday.

---

## 8.8 Cost and latency as first-class controls

Budgets are not accounting. They are authority: a delegation's token
budget and latency budget are the leash, checked before dispatch (is
this delegation even allowed to start?) and after (what did it
actually cost?). The module's `Budget` is deliberately boring — two
numbers — because boring is auditable.

The worksheet makes the cost model of the second call executable:

```python
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
```

The test suite asserts the arithmetic — three delegations at 100/200/300
tokens total exactly 600, with quarantined and open counts broken out —
because a cost model that is not asserted is a wish. The operational
rule this seeds for Ch 14: **kill the runaway before it bills you.**
A delegation that exhausts its budget is halted mid-flight, not
invoiced post-mortem. The latency budget does the same work for the
clock that the token budget does for the wallet — a worker that burns
45 seconds against a 30-second budget is halted even if its tokens
were fine, because latency is the availability budget of everyone
waiting downstream.

---

## 8.9 The trading desk

AlphaForge's signal agent runs a supervisor over two workers, and the
org chart is drawn in scopes:

- **research** — declared capability `{"market.read"}`. It reads the
  fundamentals MCP server (Ch 7's client, qualified names, trusted
  descriptions). It may never propose orders: a delegation granting
  it `orders.propose` is refused at *both* checks — outside the
  worker's capability and, in the desk's configuration, outside what
  the supervisor will grant a reader.
- **risk** — declared capability `{"risk.read", "risk.veto"}`. It can
  veto but never execute. Its veto wins adjudication (§8.7), because
  the desk would rather miss a winner than wear a blowup.

A morning's run: the signal agent delegates "pull NVDA fundamentals"
to research (scope `{"market.read"}`, SYNTHETIC quotes labeled as
such — the fixture honesty from Ch 7's client carries through the
delegation), delegates "check desk drawdown" to risk, adjudicates
veto-wins, and only then — with two validated `WorkerResult`s in the
trace — does the signal become a proposal for Ch 4's contracts and
Ch 10's executor. The team never touches an order. It produces
*evidence*, and evidence is what the rest of the spine consumes.

Note what the desk does not do: the workers never talk to each other
directly. All traffic goes through the supervisor's `delegate()`,
which is what makes the trace complete and the cycle guard sound.
Peer-to-peer whispering between workers is how evidence laundering
happens off the books.

---

## 8.10 What the orchestrator is not

It is not plumbing. The transport — MCP, stdio, TCP, carrier pigeon —
is a seam, and the module is deliberately transport-agnostic, because
authority must not depend on which socket the bytes took. It is not a
framework: it has no planner, no memory, no model. It is the
authority-accounting layer that every framework needs and none
provides.

And it is not the end of the story for agent-to-agent communication.
The handoff protocol between *organizations'* agents — the
counterparty's agent talking to yours — is the A2A protocol of
Appendix A, and §8.5's delegation record is shaped so a cross-organizational
handoff can carry the same fields (task, scope, provenance, cost)
across that boundary. Within the walls: attenuation. Across the
walls: attested handoff. Same spine, wider world.

---

## Handoff to Chapter 9

The delegations are resolved — granted, refused, failed, reconciled,
or quarantined, and every one of them recorded. What remains is the
question Maya asked third, the one the whole spine exists to answer:
*how would we know if it misbehaved?*

The trace this chapter built is a list of claims. Chapter 9 turns
claims into evidence: the taxonomy of what gets recorded, the
HMAC-chained spine that makes the record tamper-evident, and the
routing that gets each piece of evidence to the consumer — human,
evaluator, or auditor — that needs it. The orchestrator fed the
spine. Now we build the spine to hold it.
