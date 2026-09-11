# Appendix A — The A2A 1.0 Protocol: A Client-Side Validator

*Cross-reference seam: §8.8 of Chapter 8 sends cross-organizational
handoffs here. Within the walls of one organization, Ch 8's orchestrator
attenuates authority itself; across the walls — your agent talking to a
counterparty's agent — the A2A protocol is the wire, and this appendix is
the checklist for trusting what comes off it.*

---

## A.1 Why a protocol validator

Chapters 7 through 18 built a machine for running agents you control.
Appendix A covers the agents you do not. The Agent2Agent (A2A) protocol,
v1.0.0 — verified against the official specification at
`a2a-protocol.org/v1.0.0/specification/` before a word of this appendix was
written — is the open standard for communication between independent,
potentially opaque agent systems: discovery of capabilities, negotiation
of interaction modalities, collaborative task management, and information
exchange *without needing access to each other's internal state, memory,
or tools*.

That last clause is the whole point, and the whole danger. A2A lets a
counterparty's agent do work for you while its internals stay opaque. The
protocol gives you a card that *describes* the agent, a lifecycle for the
task, and hooks for authentication. It does not give you the agent's
honesty. This appendix's validator (`a2a_validate.py`) checks the
protocol surface — shape, required fields, state legality, and auth
presence — so that when something is wrong, it is wrong *loudly*, before
you send a single message. Thirty-six adversarial tests ship with it.

One version note matters before we begin. A2A v1.0.0 made the Protocol
Buffer file (`a2a.proto`) the single normative definition, with JSON-RPC
method names in PascalCase (`SendMessage`, `SendStreamingMessage`,
`GetTask`, `CancelTask`) and the agent card served from the well-known
URI `/.well-known/agent-card.json`. If you are working with a 0.3.x-era
agent, expect lowercase methods (`message/send`) and the older card
shape — the validator targets v1.0.0 and says so in every rejection.

## A.2 The trust model: what A2A guarantees and what it does not

Read the spec's own language carefully. A2A's goals are interoperability,
collaboration, discovery, flexibility, security, and asynchrony. Its
guiding principles include *opaque execution*: agents collaborate on
declared capabilities and exchanged information, without sharing internal
thoughts, plans, or tool implementations.

Here is the trust model that follows, stated plainly:

**What A2A guarantees.** Discovery: an agent publishes a card at a
standard location describing its identity, skills, interfaces, and
authentication requirements, and clients can fetch it before any
conversation. Lifecycle semantics: a task moves through named states, and
the spec marks which states are terminal (completed, failed, canceled,
rejected) and which are interrupted (input-required, auth-required) —
messages sent to terminal tasks cannot be accepted. Authentication hooks:
the card declares security schemes (API key, HTTP auth, OAuth 2.0, OpenID
Connect, mTLS — a SecurityScheme must contain exactly one of these), and
the client must authenticate using one of the declared schemes.

**What A2A does not guarantee.** It does not authorize *actions* — a
credential proves who you are talking to, not what they may do. It does
not verify skill claims — the card's skills are self-declared
descriptions, and the spec calls them "largely a descriptive concept."
It does not secure *discovery itself* — the card is fetched over HTTPS
from a well-known URI, but nothing in the protocol binds the card to the
agent's identity until you verify a signature or pin the endpoint (§8.6
gives caching guidance; it does not give you trust). A card served from
a hijacked domain is a valid card for the wrong agent.
It does not vouch for message content — a structurally valid message can
carry a malicious payload. And it does not define legal state
transitions beyond marking terminals; what may move where is left to
implementations.

That last paragraph is Chapter 12 at protocol scale: a valid message can
still be a malicious one. Transport security is not authorization, and a
passing card check is not a trust decision. The validator below exists so
you can fail *fast* on protocol violations; the book's other machinery —
contracts (Ch 4), output review (Ch 12), tenant isolation (Ch 6) — is
what you apply to the content that survives.

## A.3 The agent card: claims before conversation

The card is the first thing you see and the least trustworthy thing you
will handle: a self-describing manifest published by the party you are
about to trust. Spec §4.4.1 requires eight fields — `name`,
`description`, `supportedInterfaces`, `version`, `capabilities`,
`defaultInputModes`, `defaultOutputModes`, and `skills` — and the
validator refuses cards missing any of them, naming each absent field:

```python
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
```

That listing is the states table of §4.1.3, verified verbatim from the
spec — including `TASK_STATE_AUTH_REQUIRED`, the interrupted state that
0.3.x-era teaching often omits. The brief's shorthand ("submitted →
working → completed/failed/cancelled") is the common path, not the full
state machine; production code must handle input-required, auth-required,
and rejected, because counterparties will send them.

The card validator enforces five spec-derived rules beyond required
fields. First, interfaces: every `supportedInterfaces` entry must carry
an absolute HTTPS URL — the spec says "must be a valid absolute HTTPS
URL in production" — plus a named protocol binding and version. Second,
skill shape: each skill needs `id`, `name`, `description`, and `tags`,
and skill IDs must be unique within the card. Third, security-scheme
shape: each declared scheme must contain exactly one of the five kinds,
with its required subfields (an HTTP-auth scheme needs its `scheme`; an
API-key scheme needs a valid `location` and a `name`; OIDC needs its
discovery URL; OAuth 2.0 needs exactly one flow type). Fourth — and this
is the house coinage doing work — **capability vs authority**: a skill
whose `securityRequirements` name a scheme the card never declares is a
card claiming protection it cannot deliver, and it is refused. Fifth, the
extended card: `extendedAgentCard: true` with no `securitySchemes` is a
refusal, because an extended card is only meaningful behind
authentication the card does not define.

One honest residual the validator carries openly: card `signatures` are
shape-checked, but JWS verification needs the signer's key, which an
offline validator does not have. The check passes the shape and emits a
`signature_unverified` warning that says exactly that. A validator that
silently skipped signatures would be worse; a validator that claimed to
verify them would be lying. There is a third option — say what you did —
and it is the only one this book takes.

## A.4 Messages, parts, and the oneOf rule

A message is a communication turn: `messageId`, `role`, and `parts`, per
§4.1.4. The validator checks the required envelope and then enforces the
spec's sharpest little rule, §4.1.6: **a Part must contain exactly one
of `text`, `raw`, `url`, or `data`**. Not zero, not two — exactly one.
The adversarial tests attack both sides: a part carrying `text` and
`data` together is refused, and a part carrying neither is refused, both
under `part.not_exactly_one_content`. Roles are restricted to
`ROLE_USER`, `ROLE_AGENT`, and `ROLE_UNSPECIFIED`; the envelope must be
non-empty. Artifacts get the same treatment: `artifactId` is required
(unique within the task), and the parts array must contain at least one
part, each of which faces the oneOf rule.

These are small rules with a large purpose. A part that carries both text
and a data blob is a message with two mouths; downstream code will read
one and ignore the other, and the ignored one is where the surprise
lives. The spec forbids it, and the validator makes the forbidding
executable.

## A.5 The task lifecycle: states and the book's transition rule

The spec defines the states and marks the terminals. It does not define
which transitions are legal — so the book does, and marks the table as
its own stricter addition rather than a spec claim. Terminal states are
absorbing: a task that completed, failed, was canceled, or was rejected
cannot move again, mirroring the spec's rule that messages to terminal
tasks cannot be accepted. `TASK_STATE_UNSPECIFIED` is never a valid
status — indeterminate is not a state you are allowed to be in.

```python
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
```

The validator consumes a sequence of observed `(task_id, old_state,
new_state)` triples — the stream of status updates your client actually
saw — and refuses anything outside the table. The tests attack the two
failures that matter most in practice: resurrection (`completed →
working`, refused under `task.transition_from_terminal`) and skipping
(`submitted → completed`, refused under `task.illegal_transition`). In a
cross-organizational handoff, a counterparty whose tasks resurrect or skip
is a counterparty whose lifecycle you cannot reason about — which is the
polite way of saying you cannot trust its "done."

Why add a rule the spec doesn't require? Because Ch 8's orchestrator
treats a handoff's lifecycle as evidence: a delegation that completed is
a delegation whose results may be consumed. If the counterparty's agent
can silently move a completed task back to working, the evidence your
spine recorded was a draft, not a verdict. The stricter table is the
price of treating a remote task's state as something you can build on.

## A.6 Authentication: presented is not verified

The spec's auth rule is one sentence with teeth: the client must
authenticate the request using one of the schemes declared in the public
card's `securitySchemes`. The validator implements it as a three-way
decision, because authentication goes wrong in exactly three ways:

```python
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
```

The second outcome is the one that kills systems: presented-but-unverified
is **rejected**, not downgraded to a warning. An unsigned artifact that
"looks right" is the most dangerous input a system can receive, because
every downstream check treats it as established fact. The validator's
`Credential` carries a `verified` bit precisely so the calling code is
forced to say, for every request, whether it actually verified what it
was handed. If it did not, the request does not go out.

A card with no `securitySchemes` at all is accepted with a warning —
`auth.open_agent` — because the spec permits unauthenticated agents, and
the validator's job is to describe reality, not to forbid it. The warning
says what to do instead: treat every response as untrusted, which is the
Ch 12 posture applied to the whole counterparty.

## A.7 What this validator is not

Every mechanism in this book ends with the sentence that bounds it, and
this one is no exception. This validator checks the protocol surface. It
does not check whether a skill's description matches what the skill does
— the spec calls skills "largely a descriptive concept," and no JSON
check can close that gap. It does not check message *content* — a
perfectly valid envelope can carry a prompt-injection payload, and that
is Ch 12's jurisdiction, not this appendix's. It does not establish trust
in the counterparty — it establishes that the counterparty speaks the
protocol correctly, which is a much smaller claim.

The capability-vs-authority distinction is the through-line. The card is a
capability claim: "I can do these things." Authority is a separate
question — what the card's schemes, your verification, and your own
contracts (Ch 4) permit — and it is answered by your side of the
boundary, never by the card's self-description. Validate the card, verify
the credential, and then apply the book's full machinery to everything
that crosses the wire. A counterparty that passes every check in
`a2a_validate.py` has earned exactly one thing: the right to be
scrutinized by the harder tests.

## A.8 The counterparty worked example

The desk settles through a custodian whose agent speaks A2A. Before the
first settlement message, the desk's client runs the validator against the
custodian's card fetched from `/.well-known/agent-card.json`. The card
passes shape: nine interfaces over HTTPS, a skill named
`settle-delivery-vs-payment` with real tags, an OAuth 2.0 scheme with a
client-credentials flow and a single flow type. The credential the desk
presents names that scheme and is verified — outcome three, accepted.

Then the task lifecycle does its work. The settlement task moves
submitted → working, and the custodian's agent requests auth it had not
declared — a `TASK_STATE_AUTH_REQUIRED` the card's schemes cannot satisfy.
The transition itself is legal under the book's table (submitted →
auth-required is an allowed edge), but the *demand* is not: the card
promised one authentication story and the task is telling another. The
desk refuses the task (`task` transitions to rejected on the desk's side)
and routes the card for human review. A card that passes every
structural check can still fail the conversation — which is why §A.7 says
the validator earns only the right to be scrutinized further. The
mechanics caught the shape violation; the judgment about the counterparty
stayed with a human. That is the correct division of labor.

## A.9 Explicit assumptions

The appendix's credibility rests on the verification bar stated at the
top: spec claims were checked against the v1.0.0 specification before
drafting. What follows is the honest ledger of what that checking could
and could not establish.

**Verified against the spec:** the eight required AgentCard fields
(§4.4.1); the nine TaskState values and their terminal/interrupted
markings (§4.1.3); the Task, TaskStatus, Message, Part, and Artifact
field tables, including the Part oneOf rule (§4.1.4–§4.1.7); the
AgentSkill, AgentInterface, AgentCapabilities, and AgentCardSignature
field tables (§4.4.2–§4.4.7); the five SecurityScheme kinds with the
exactly-one-kind rule (§4.5.1); the per-scheme subfield requirements
checked here (§4.5.2–§4.5.7); the well-known card URI (§8.6); PascalCase
JSON-RPC method names including `SendMessage` (§9); the
"must authenticate using one of the declared schemes" rule (§4.5/§13).

**Book rules, not spec claims:** the allowed-transition table (§A.5) —
the spec marks terminals but defines no transitions; the "extended card
needs declared schemes" refusal; the "skill must not name undefined
schemes" refusal; the "presented-but-unverified is rejected" policy. Each
is labeled `[BOOK RULE]` in the code.

**Assumed — check against the current spec before production use:** the
exact JSON serialization of `SendMessageRequest` beyond the method name
was not exercised by this validator (it validates the data model, not
the wire binding); behavior of agents under v0.3.x is described from the
spec's own migration notes, not from a 0.3.x validation pass; the
`tenant` field on AgentInterface is accepted but no multi-tenant card
semantics are validated. A2A is a living standard — pin the version you
validate against, the way Ch 7 pins the MCP spec date.
