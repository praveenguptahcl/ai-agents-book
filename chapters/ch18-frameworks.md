# Chapter 18 — Securing Enterprise Frameworks

*Part VI: Accountability. The premise of this chapter is a refusal: you do not get to rewrite the stack.*

## The tool that worked fine

Every trading desk has one. At AlphaForge it was called `dump_positions`, a LangChain-style tool somebody wrote two years ago to answer a simple question — *what are we holding?* — and then everybody forgot about. It worked fine. It returned a little CSV-ish string of symbols and quantities, and the agents pasted it into their context, and the end-of-day summaries quoted it, and nobody thought about it again. Tools that work fine are the ones nobody reviews.

Then a well-meaning contributor added a feature. A `notify` filter: pass a callback URL and the tool would append it to the output, so the agent's summary could include where the numbers were sent. Nobody reviewed that either. It was twelve lines.

Here is the tool, almost exactly as it ran in production:

```python
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
```

One afternoon the research agent — prompted by a poisoned earnings-call transcript, the kind of thing Chapter 12 is about — asked for positions with `notify` set to an attacker-controlled webhook. The tool complied. It always complies; compliance is all it knows. The output, callback URL and all, flowed into the planner's context as trusted tool output, and the planner, doing what planners do, *used* it: subsequent summaries included the attacker's URL as the desk's reporting endpoint. Nobody's positions moved. No money was lost. But for three days the desk's agents cheerfully told anyone who asked that fill reports should go to a server in a country the desk has no office in.

The postmortem was short and familiar: the tool had no schema, so nothing validated the `notify` value. It had no session, so nothing checked which tenant was asking. It had no output review, so the poisoned string reached the planner unexamined. And it had no evidence trail, so reconstructing those three days took a week of log archaeology.

Here is the uncomfortable part: *this tool is normal.* Walk into any enterprise running agents in production today and you will find a dozen of them — LangChain tools, LlamaIndex query engines, AG2 functions — stringly typed, trusting their inputs, invisible to the audit trail, and load-bearing. The world-class response is not to rewrite them all. You will not get the budget, the downtime window, or the political capital, and while you wait the tools keep running. The world-class response is to **wrap them**: put every legacy tool behind an adapter that enforces this book's discipline, and strangle the old code gradually. Wrap first. Replace gradually. Never the other way around.

## The adapter interface

An adapter is a trust boundary disguised as a wrapper. It presents the same face to the framework the framework expects — a callable tool — and a completely different face to the inside: contracts, sessions, approvals, evidence. The interface has nine facets, and each one answers one of the book's standing questions:

| Facet | Question it answers |
|---|---|
| **Agent** | *Which* agent is calling — identity, not a string label (Ch 6) |
| **Model** | Which model proposed this, at what cost (Ch 5, Ch 14) |
| **Tool** | Is this tool registered — does the adapter know it at all |
| **Policy** | What risk tier is this action, and what does the tier require |
| **State** | What the world looked like when the call was authorized (Ch 2) |
| **Run** | Which run this call belongs to, for trace reconstruction (Ch 9, Ch 14) |
| **Trace** | The evidence record this call leaves behind, allowed or refused |
| **Approval** | Whether a human has bound themselves to this exact payload |
| **Evidence** | The digest trail that lets an auditor replay the decision |

Notice what is *not* a facet: the framework. The adapter does not care whether the tool came from LangChain, LlamaIndex, AG2, or a hand-rolled loop. Frameworks are interchangeable; the boundary is not. That is the whole point. If your security depends on which framework you chose, you don't have security — you have a vendor.

The risk tiers are the policy vocabulary. Three tiers, no more; a policy with seventeen tiers is a policy nobody enforces:

```python
class RiskTier(str, Enum):
    READ = "read"              # no external effect; no approval needed
    WRITE = "write"            # reversible external effect; approval required
    IRREVERSIBLE = "irreversible"  # cannot be undone; approval + receipt
```

`dump_positions` is READ. Placing an order is WRITE. Wiring a new bank account for withdrawals is IRREVERSIBLE, and IRREVERSIBLE actions don't just need approval — they need a receipt, a named human, and a timestamp, because "who said so" is the question the auditor will ask and "the agent" is not an answer.

## The five checks, in order

Every wrapped call passes through five checks, and the order is load-bearing. Here is the adapter's core — read it as a procedure, because it *is* the procedure:

```python
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
```

Then the approval check, the dispatch, and the output review:

```python
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
```

Why this order:

1. **Registration before everything.** An unregistered tool is refused before the adapter even asks who is calling. Authority cannot be evaluated for a tool the system does not know, because the registry *is* the system's knowledge of its own capabilities. The framework may invent tool names at will; the adapter may not honor them.
2. **Authority before shape.** The session check runs before contract validation. This is deliberate: validating the arguments of an unauthorized caller leaks information (the shape of the contract, the precision of the error messages) to someone who should not be in the room. "Who said so" precedes "what did they say."
3. **Contract before dispatch.** The legacy function never sees unvalidated input — the book's Chapter 4 discipline, applied rather than re-taught. Note the `adapt` step: the validated model is *translated* into the legacy function's calling convention (`args_json`, in our example) by the adapter, visibly, in one place. The translation seam is where strangler-pattern bugs live, so it is explicit instead of hidden.
4. **Approval before effect.** WRITE and IRREVERSIBLE actions need a live ticket, and the ticket binds to the *digest of the exact payload*. Approving 100 shares of AAPL does not approve 10,000 — the test suite asserts exactly this, because this is the mistake every approval UI makes.
5. **Output review after execution.** The tool ran; its output is still untrusted. This is the Chapter 12 discipline at the framework boundary: the planner never sees raw tool output, only reviewed output.

And on *every* path — allowed, refused, crashed — an `EvidenceRecord` is appended: timestamp, tenant, tool, the SHA-256 digest of the arguments (never the raw arguments; secrets don't belong in the audit trail either), the verdict, the approver. The evidence trail is complete precisely because the refusals are recorded too. An auditor who can only see what was allowed cannot distinguish "nothing bad was attempted" from "the logging was off."

## Why the adapter is the most dangerous code you own

Here is the theory, and it is worth stating bluntly: **the adapter is security-critical code that looks like plumbing.** It sees every argument and every output. It decides what runs and what doesn't. It is written once, usually in a hurry, by whoever drew the strangler-pattern straw — and then it becomes the single point through which all agent authority flows.

That makes it both the highest-leverage and the highest-risk component in the system. A bug in a tool is a bug in one capability. A bug in the adapter is a bug in *every* capability. The confused-deputy problem — Chapter 12's territory — lives here in its purest form: the adapter acts with the union of all the authority it mediates, and if it can be tricked into misattributing a request, it will spend somebody else's authority with a straight face.

This is why the adapter in this chapter is small (under 400 lines), dependency-free (stdlib + Pydantic), and tested like it is guilty (22 adversarial tests). The rule: **the code that enforces the boundary must be simpler than the code it constrains.** If your adapter needs its own framework, you have built a second system to secure the first, and you now need a third.

It is also why the adapter fails closed at every seam it does not control:

- No session verifier configured? `NoAuthoritySource` — refuse everything. An adapter must never invent authority.
- The verifier crashes? That is a denial, not a pass. ("A verifier that crashes denies, loudly.")
- The output reviewer is, by default, a minimal documented heuristic — and the module says so in its docstring, plainly: production wires the real pipeline. A default that pretended to be a security boundary would be worse than no default, because it would be trusted.

## The worked example: strangling `dump_positions`

Wrapping the desk's legacy tool takes four steps: define the contract the tool never had, register it with its risk tier, provide the translation into its calling convention, and hand the adapter an authority source. The contract:

```python
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
```

The registration, with the translation seam made explicit — the validated
model is translated into the legacy tool's `args_json` calling convention by
the adapter's `adapt` callable, visibly, in one place rather than hidden in
the framework or the legacy function. The translation seam is where
strangler-pattern bugs live, so it is explicit instead of hidden. (The exact
registration call is exercised in the test suite's `make_adapter` fixture.)

Now replay the incident. The poisoned transcript tells the agent to request positions with `notify` set to the attacker's webhook. Before the adapter, the tool complied. After:

- `ContractViolation`: `notify` must start with `https://desk.internal/`. The legacy function is never called — the test asserts the spying stand-in saw zero invocations. The refusal is recorded as evidence.
- With an approved desk endpoint, the call proceeds, the output is reviewed, and the record shows `allowed`.

The incident class is closed at the contract, which is where it should have been closed two years ago. Nothing about the legacy function changed. That is the strangler pattern: the old code keeps running, inside a boundary it cannot see.

## Approval gates: binding a human to a payload

Approvals are where the machine asks the human to spend *their* authority, and the design has to assume the human is tired, distracted, and approving their fortieth ticket of the day. Three properties make the gate trustworthy anyway:

1. **Payload binding.** The ticket is bound to the SHA-256 digest of the exact arguments. The approver reviews *this* payload, not a description of it.
2. **Single use.** A consumed ticket is deleted. Approvals do not linger as ambient authority.
3. **Expiry.** Six hundred seconds, then the ticket dies unapproved. Stale approvals are how "yes, I approved that last week" becomes an incident.

```python
    def request_approval(self, session: Any, tool: str, raw_args: Any,
                         requested_by: str) -> str:
        """Open an approval ticket. Returns the ticket id.

        The ticket binds to the *digest* of the proposed arguments: approving
        one payload does not approve a different payload.
        """
        reg = self._registry.get(tool)
        if reg is None:
            raise UnwrappedToolRefused(f"tool not registered: {tool!r}")
        digest = _digest(raw_args)
        ticket_id = uuid.uuid4().hex
        now = time.time()
        self._tickets[ticket_id] = ApprovalTicket(
            ticket_id=ticket_id, tool=tool, args_digest=digest,
            requested_by=requested_by, requested_at=now,
            expires_at=now + self.APPROVAL_TTL_S,
        )
        return ticket_id
```

Note what the approval does *not* do: it does not re-check the contract or the session at approval time. Those were checked at request time and are checked again at dispatch time — the ticket carries the digest, and `_consume_ticket` matches it against the live call. There is no time-of-check-to-time-of-use gap because the check and the use are the same lookup.

The deeper question — *when* should a human be in the loop, and how do you design the escalation so it doesn't decay into rubber-stamping — belongs to Chapter 19. The adapter provides the mechanism; the next chapter provides the policy. Mechanism before policy, always: you cannot have an honest conversation about approval UX until the approvals are real.

## The same loop, in every framework

The adapter pattern is framework-agnostic by construction, but enterprises will ask the concrete question: *how does this map to the framework we already bought?* The answer is that every major framework already has the interception points; they are just not wired to a discipline. Conceptually:

- **OpenAI Agents SDK** organizes work around agents, handoffs between them, and *guardrails* — input guardrails that inspect what enters, output guardrails that inspect what leaves. The adapter is the guardrail given teeth: instead of advisory checks, the five-check `call()` sequence, with registration as the handoff policy. A handoff the adapter hasn't registered is a handoff that doesn't happen.
- **Anthropic's tool-use loop** is the cleanest conceptual fit: the model emits `tool_use` blocks, the harness executes them, `tool_result` blocks flow back. The adapter sits exactly at the harness — between `tool_use` and execution (checks one through four) and between execution and `tool_result` (check five). If you control the harness, you control the agent, regardless of what the model proposes.
- **LangGraph** models the agent as a graph of nodes and edges, and its human-in-the-loop story is the `interrupt`: a node can pause the graph and wait for a human before continuing. The adapter's approval gate is the interrupt with a memory — the ticket binds the resumption to the exact payload that was approved, so the graph cannot resume with different arguments than the human saw.

No framework-specific APIs are invoked here, deliberately. Framework APIs churn; the interception *points* — before dispatch, before effect, after execution — are stable because they are where the authority flows, not where the vendor put the hooks. When you evaluate a framework (and the next section is the checklist), you are really asking: *does it let me stand at those three points?*

## Framework risk assessment: the buyer's checklist

Before adopting — or continuing to run — any agent framework, check these four things. They are ordered by how quietly each one fails:

1. **Tool-call interception.** Can you interpose on every tool invocation — yours, the framework's built-in tools, and tools added later by plugins? A framework with an interception point you can't hook is a framework whose tools you don't control. Check: does the framework document a single choke point for tool execution, or do tools run wherever they were defined?
2. **Prompt visibility.** Can you see — and pin — the exact system prompt and tool descriptions the model receives? Chapter 12 showed why tool descriptions are a trust surface. A framework that lets plugins silently rewrite prompts has given every plugin author write access to your agent's instructions.
3. **State access.** What can a tool read and write outside its arguments? Conversation history, credentials in the environment, the filesystem, other tenants' data? The adapter's session check is meaningless if the tool can reach around it into shared state. Least privilege applies to tools exactly as it applies to people.
4. **Network control.** Can tools make arbitrary network calls, or do they go through a boundary you control (Chapter 13)? An agent framework with unmediated network access is a distributed system with no firewall rules.

If the answer to any of these is "no" or "we're not sure," the framework is not disqualified — but the adapter around it must be correspondingly thicker, and the residual risk goes into the register honestly. Chapter 19 turns this checklist into procurement language.

## The framework choice is the autonomy choice

The standing comparative table, this chapter's instance. The rows are the same five systems; the columns are what changes when you choose how much framework does for you:

| | Deterministic workflow | Single agent (wrapped) | Multi-agent (Ch 8, wrapped) | Human |
|---|---|---|---|---|
| **Reliability** | Highest — no model in the loop | High — model proposes, adapter disposes | Medium — delegation compounds error | Variable — the rubber-stamp decay |
| **Cost** | Trivial | Per-call model + review cost | Multiplicative (Ch 8's second-call worksheet) | Dominant — salary × attention |
| **Latency** | Milliseconds | Seconds | Seconds × depth | Minutes to hours |
| **Flexibility** | None — does one thing | High within the contract | Highest — new topologies, new risks | Unbounded, unpriced |
| **Security** | Auditable line by line | The adapter is the boundary | Each delegation is a new boundary | Social engineering surface |
| **Debuggability** | Replay the inputs | Replay the evidence trail | Replay the delegation tree | Ask what they remember |
| **Human burden** | Zero at runtime | Approval queue for WRITE+ | Approval × agents | Everything, always |

The recurring lesson of this book, in this chapter's words: **the least autonomous system that reliably works.** The adapter exists to make "single agent, wrapped" reliable enough that you don't reach for the multi-agent topology — or the human — until the task actually requires it. Every step rightward in that table is a step that must be *earned* by the task, not defaulted into by the framework.

## Handoff

The frameworks are wrapped. Every tool the enterprise already runs now passes through registration, authority, contract, approval, and output review — and leaves evidence either way. The machinery of accountability is in place.

But machinery is not accountability. Accountability is what happens when the auditor arrives, the buyer asks for the questionnaire, the regulator names the article number, and the system has to be *decommissioned* — keys revoked, data deleted, the model sunset, the exit criteria met. Chapter 19 translates everything this book built into the language those conversations are held in: compliance mappings, SLAs, human-oversight design, procurement, and the off-ramp.

*Figure: the adapter as a decorator — framework tool in, five checks, legacy function, reviewed output out. Full spec: `figs/ch18-figspec.md`.*
