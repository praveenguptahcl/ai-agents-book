# Chapter 21 — Lab 2: The Signal Generator Contract

The desk's signal desk has a new employee. It is an LLM research agent, and
it is the most enthusiastic hire in AlphaForge history. It reads filings at
3 a.m., it spots momentum regimes before the coffee finishes brewing, and it
proposes trades with the unshakeable confidence of someone who has never
been wrong in a way that cost money. Some of its proposals are excellent.
Some of them are for tickers that do not exist.

Between its enthusiasm and the executor stands exactly one thing: the
pipeline you are about to build. This lab proves the composition at the
heart of the book — Chapter 5's strict provider schema and Chapter 4's
Pydantic contract gate, working as two layers that trust neither the model
nor each other.

This is a RED lab. The file `code/ch21/test_lab2_signals.py` fails out of
the box — ten failures, all of them `NotImplementedError`, all of them
yours to fix. The passing implementation is the answer key in Appendix B. It
does not appear in this chapter. That is the lab rule, and it is load-bearing:
a lab whose answer ships next to the question is a reading exercise, not a
lab.

## 21.1 The composition you're proving

Chapter 5 taught the wire: the model emits proposals through a strict JSON
schema, and strict mode guarantees *shape* — fields, types, closed enums.
Chapter 4 taught the gate: a Pydantic contract that guarantees *judgment* —
ranges, the universe allowlist, the notional cap. Neither layer trusts the
other, and both must pass.

The lab makes the split concrete, because the split is where the teaching
lives. OpenAI's strict mode cannot express ranges — "confidence must be in
[0, 1]" is not a thing the provider schema can say. So when the erratic LLM
emits confidence 1.7, the schema *passes it*. The kill has to come from the
contract. Conversely, when the model emits `"side": "long"`, no contract
logic is needed — the closed enum rejects it at the schema as a shape
failure. Two layers, two different vocabularies of refusal, and the lab pins
which layer refuses what.

The pipeline you build has four stages, in this order:

1. **Parse** — the raw string as JSON. Truncated output dies here, before
   anything downstream ever sees it.
2. **Schema-check** — against `SIGNAL_JSON_SCHEMA`: required fields, types,
   the closed `buy`/`sell`/`hold` enum. Failure is `SCHEMA_VIOLATION`.
3. **Contract-gate** — through `SignalProposal`: confidence in [0, 1], the
   symbol allowlist, the $25,000 notional cap. Failure is
   `CONTRACT_VIOLATION`.
4. **Dedupe** — on `proposal_id`. Seen before means a retry or a replay, and
   the pipeline treats both identically: accepted exactly once, then
   `DUPLICATE_ID`.

Every rejection carries a name from a closed set — `MALFORMED_JSON`,
`SCHEMA_VIOLATION`, `CONTRACT_VIOLATION`, `DUPLICATE_ID`. A rejection
without a name is a shrug, and this pipeline does not shrug. When the
executor's log shows a rejection at 2 a.m., the on-call engineer should know
*which layer* refused and *why*, without re-reading the payload.

## 21.2 The erratic LLM

You are given the fixture — nine raw model outputs, deterministic, the same
list every run so that RED today is RED tomorrow and GREEN means something.
One is valid. Eight are hostile in eight different ways:

| Case | Hostility | Killing layer |
|------|-----------|---------------|
| `valid` | None — the control | Accepted |
| `missing_field` | No `side` at all | Schema |
| `confidence_out_of_range` | Confidence 1.7 | Contract (the schema *passes* it) |
| `unknown_symbol` | `GME` — crisp rationale, invented ticker | Contract (the allowlist) |
| `invalid_side` | `"side": "long"` | Schema (closed enum) |
| `malformed_json` | Truncated mid-rationale | Parse |
| `absurd_size` | 10,000,000 shares of SPY | Contract (the notional cap) |
| `duplicate_first` / `duplicate_second` | Same `proposal_id` twice | Dedupe |

Read the `unknown_symbol` case twice. It is Chapter 5's canonical
fail-plausible: the rationale reads like a professional desk note, the JSON
is immaculate, and the ticker was never in the approved universe. Every
layer above the parser agrees the output looks fine. The allowlist is the
only layer that knows — which is why the allowlist is code, not a prompt
instruction.

And read `absurd_size` three times. It is the Chapter 2 lesson wearing a lab
coat: structurally valid, semantically absurd. Every shape check passes.
Ten million shares of SPY is a $5.9 billion proposal against a $25,000 cap.
The schema cannot express "that number is insane" — no schema can, because
insanity is domain knowledge. The contract can, because the contract *is*
domain knowledge written as code. This is the case the whole lab exists for:
the day your pipeline accepts a well-shaped catastrophe is the day you learn
that shape was never the whole job.

## 21.3 A proposal walks the pipeline

Watch one proposal make the full journey, the way the desk's signal desk
runs it every morning. The research agent emits this at 9:31 a.m. (JSON
shown with line breaks added; content identical to the fixture):

```json
{"proposal_id": "sig-0001-deadbeef", "symbol": "AAPL", "side": "buy",
 "qty": 10, "confidence": 0.72, "reference_price": 232.50,
 "rationale": "momentum continuation, volume confirms"}
```

**Parse** reads it as JSON — no truncation, no surprises. **Schema-check**
walks the required list: all seven fields present, types correct, `side` a
member of the closed enum. **Contract-gate** takes over where shape ends:
confidence 0.72 is inside [0, 1], `AAPL` uppercases onto the allowlist, and
the notional — 10 × $232.50 = $2,325 — fits comfortably under the $25,000
cap. **Dedupe** checks `sig-0001-deadbeef` against the seen set: new. The
verdict is `("accepted", None)`, and the proposal continues to the executor
with its papers stamped at every stage. Total cost: under a millisecond, in
Python, before any network call exists — Chapter 4's latency budget, honored.

Now the hostile one, from the same morning:

```json
{"proposal_id": "sig-0004-deadbeef", "symbol": "GME", "side": "buy",
 "qty": 10, "confidence": 0.80, "reference_price": 24.00,
 "rationale": "meme momentum, retail flow accelerating"}
```

Parse succeeds. Schema-check succeeds — every required field is present,
every type correct, `buy` is a valid enum member. The shape is immaculate.
Then the contract gate uppercases `GME`, checks the allowlist, and refuses:
`CONTRACT_VIOLATION`. The rationale was crisp. The JSON was perfect. The
ticker was invented, and the only layer that knew was the one written as
code rather than as instructions. On the desk's dashboard — Chapter 4's
field 10, rejection rate per contract — this shows up as one more tick in
the contract-violation column. A spike in that column means the planner is
degrading: it is inventing tickers more often, and the dashboard knows
before any human does. That is what observability on a boundary looks like.

Notice what the pipeline never does: it never asks the model to try again,
never "helpfully" corrects `GME` to a real ticker, never fills in the
missing `side` on the `missing_field` case. A pipeline that repairs
proposals is a pipeline that invents authority — the exact defect Chapter 4
was written to kill. Refuse, name the reason, move on. The planner can read
the reason code and correct itself; that is the planner's job, not the
gate's.

## 21.4 The contract gate, given

The Pydantic gate ships finished — verbatim from the lab file, and the
second of the two layers your pipeline must compose:

```python
class SignalProposal(BaseModel):
    """The contract a signal must survive before any executor hears of it."""

    model_config = {"extra": "forbid", "frozen": True}

    proposal_id: str = Field(min_length=8, max_length=64)
    symbol: str
    side: Literal["buy", "sell", "hold"]
    qty: float = Field(gt=0)
    confidence: float = Field(ge=0, le=1)
    reference_price: float = Field(gt=0)
    rationale: str = Field(min_length=1, max_length=2000)

    @field_validator("symbol")
    @classmethod
    def symbol_must_be_allowlisted(cls, v: str) -> str:
        v = v.upper()
        if v not in ALLOWED_SYMBOLS:
            raise ValueError(f"symbol {v!r} is not on the paper-account allowlist")
        return v

    @model_validator(mode="after")
    def notional_must_fit_the_cap(self) -> "SignalProposal":
        notional = self.qty * self.reference_price
        if notional > MAX_NOTIONAL:
            raise ValueError(
                f"notional ${notional:,.0f} exceeds the ${MAX_NOTIONAL:,.0f} cap "
                f"({self.qty:g} x ${self.reference_price:g})"
            )
        return self
```

Note `extra="forbid"` — the closed world stays closed — and note that the
notional check is a *model* validator, because "ten million times five
hundred ninety" is a fact about the whole proposal, not about any one field.
Field validators check papers; model validators check the story the papers
tell together.

## 21.5 What you build

The stub is the whole assignment, and it fits in a screen:

```python
class SignalPipeline:
    """Parse → schema-check → contract-gate → dedupe. You build this."""

    def __init__(self) -> None:
        self._seen_ids: set[str] = set()

    def process(self, raw: str) -> Verdict:
        raise NotImplementedError(
            "Lab 2 RED: build the pipeline — parse, schema-check, "
            "contract-gate, dedupe — then watch this file go green."
        )
```

`process` returns `("accepted", None)` for the fully valid proposal and
`("rejected", <one of REASON_CODES>)` for everything else. The tests are the
spec — read them before you write a line. Each one names the exact behavior
required, including the pinned layer splits: `confidence_out_of_range` must
die with `CONTRACT_VIOLATION` (not merely "rejected"), because the lab is
proving *which layer refuses*, not just that something refuses.

Two design decisions are yours, and both are deliberate. First, the
schema-check against `SIGNAL_JSON_SCHEMA` is yours to write — the schema is
given as data, the enforcement as code, because a schema nobody enforces is
a comment. Second, dedupe state lives in the pipeline instance (`_seen_ids`),
which means the pipeline is stateful and the tests construct fresh
instances — except the duplicate test, which processes twice through one
instance. Think about what that implies for a production deployment before
you dismiss it as test mechanics.

Think about what that implies for a production deployment before
you dismiss it as test mechanics. The lab's `_seen_ids` lives in process
memory: restart the pipeline and it forgets every id it ever saw, and a
replayed proposal sails through dedupe a second time. The lab-scale answer
is fine for the lab. The production answer is the durable ledger from
Chapter 14 — or, closer to home, Chapter 4's `idempotency_key`: the
executor's version of "accepted exactly once," enforced where the money
moves rather than where the proposals are screened. Dedupe at the pipeline
is defense in depth; idempotency at the executor is the guarantee. The lab
teaches the habit; the later chapters teach the durability.

## 21.6 Red → green checklist

1. **Run it RED.** `pytest code/ch21/test_lab2_signals.py` — confirm ten
   failures, all `NotImplementedError`. If it isn't RED, you don't have the
   lab; you have a different file.
2. **Read the tests as the spec.** Ten tests, ten behaviors. Note the two
   that pin reason codes to layers, not just verdicts.
3. **Implement `process` in stage order.** Parse, schema, contract, dedupe.
   Resist the urge to reach for the contract first — the layer split is the
   lesson, and skipping stages is how production pipelines quietly lose
   layers.
4. **Watch the absurd case.** When `absurd_size` goes green with
   `CONTRACT_VIOLATION`, you have proven the composition. Everything else is
   plumbing; that test is the thesis.
5. **Run it GREEN.** Ten passing. Then run it twice — the determinism test
   exists because a pipeline that flaps is a pipeline that lies.
6. **Do not open Appendix B** until you are green or genuinely stuck. The
   answer key is a reference for the stuck, not a shortcut for the hurried.

## 21.7 Rules of engagement

Paper only — the lab's universe is the paper account's six symbols, and the
notional cap is paper dollars. The fixture is deterministic; if you add your
own adversarial cases (you should), keep them deterministic too. And when
you are done, notice what you built: a four-stage pipeline that stands
between an enthusiastic model and real money, in which every refusal has a
name and every name tells you which layer did its job. That is not a filter.
That is the authority boundary from Chapter 1, with tests.

*Figure 21.1 — the four-stage validation pipeline: parse → schema-check
(shape) → contract-gate (judgment) → dedupe, with each stage's rejection
reason code. Full specification in `figs/ch21-figspec.md`.*

## 21.8 What the pipeline cannot do

Honest limits, because a lab that oversells its artifact teaches the wrong
confidence. The pipeline validates *proposals*, not *theses*. A well-formed
lie about the market — right shape, real ticker, sane size, confident
rationale, completely wrong about the world — sails through all four stages
with papers stamped. Catching that is not validation's job; it is
evaluation's job (Chapter 15's judges) and verification's job (Chapter 16's
walk-forward). The pipeline answers "may this be considered?" It never
answers "is this wise?"

It also cannot fix a bad universe. If Chapter 3's intent declares a trading
universe of meme stocks, the pipeline will faithfully, correctly, and
disastrously validate proposals for all of them. Garbage universe in,
correctly-gated garbage out. The pipeline enforces the intent it is given;
it does not audit the intent. That is why the book starts with intent
before it builds gates.

And it is synchronous and local by design — under a millisecond per
proposal, no network, no model calls. That is Chapter 4's latency budget,
and it is a constraint, not an accident: a gate that phones home for every
decision is a gate that fails when the network does. The day you are tempted
to add an LLM call inside the validator "for better judgment," re-read the
`absurd_size` test. The judgment is already there. It is written in
Pydantic.

## Handoff

The signal now survives the pipeline — or dies with a named reason. Either
way, the executor only ever sees proposals that earned their way through.
In Lab 3, the executor gets its turn: the validated signal meets a
flash crash, the kill switch trips at 5%/hour, and the ledger has to be
consistent afterwards. The pipeline you built here is what keeps the fire
drill honest — without it, Lab 3 would be testing the executor against
garbage inputs, and garbage in means the drill proves nothing.
