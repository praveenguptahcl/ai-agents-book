# Chapter 4: Designing the Agent Tool Contract

The language model does not place orders. It emits dictionaries.

That sentence is the whole chapter, and most agent teams never learn it. Somewhere between the model's JSON and the broker's matching engine there is a boundary, and whatever crosses that boundary is no longer a suggestion. It is an obligation with a dollar sign on it. The tool contract is the document that decides what is allowed to cross — and the schema is the guard standing at the gate, checking papers before anything moves.

AlphaForge learned this the expensive way. During an early paper-trading session, the research agent decided the momentum signal on a small-cap name was "strong enough to size up." It emitted an order for a symbol the desk had never approved, in a quantity that would have blown through the per-order notional cap by 4x, with no idempotency key — meaning that when the tool call timed out and the orchestrator retried it, the broker would have filled it twice. Three independent defects in one payload. In the old architecture, where the tool layer was a thin `requests.post` wrapper around whatever JSON the model produced, that order would have hit the paper broker. It was paper money, so nobody lost anything except an afternoon. The lesson was not about the money. The lesson was that the model had been given the authority to invent the terms of its own authority.

The fix was not a better prompt. You cannot prompt your way out of this, because the failure is not in the model's judgment — it is in the architecture's missing boundary. The fix was a contract: a Pydantic v2 schema that the model's output must survive before any network call exists. The order above now dies in Python, in under a millisecond, with a `ValidationError`. The broker never hears about it. That is what this chapter builds.

## The contract is the tool

Every tool your agent exposes is a contract with ten load-bearing fields. Not nine. If you cannot fill in all ten for a tool, you do not understand the tool well enough to give it to an agent. Here is the full anatomy for `submit_order` against the Alpaca-style paper broker:

| # | Field | `submit_order` |
|---|-------|----------------|
| 1 | **Preconditions** | Symbol on the account allowlist; qty > 0; price fields consistent with order type (limit requires `limit_price`, market forbids it); computable notional (a price exists); idempotency key present and well-formed |
| 2 | **Postconditions** | Exactly one order exists at the broker with the validated parameters, or the call fails with no order created. No partial state: validation is all-or-nothing before any HTTP. |
| 3 | **Side effects** | Reserves buying power; creates a position or changes an existing one on fill; writes one row to the write-ahead ledger; emits one `order.submitted` trace event |
| 4 | **Authority scope** | The paper account only. No real-money endpoints, no account settings, no withdrawals. The schema cannot express anything outside this scope, so the agent cannot request it. |
| 5 | **Reversibility** | Reversible while open via `cancel_order` (contract in the same module). Irreversible once filled — fills are market facts, not database rows. The contract makes this asymmetry explicit instead of hiding it. |
| 6 | **Idempotency** | `idempotency_key` is required, 8–64 chars, no whitespace. Retries reuse the key; the broker dedupes. There is no default key because a default key would make two different orders look like one retry. |
| 7 | **Latency budget** | Schema validation < 1 ms locally. The contract guarantees rejection happens before the network, so a malformed order costs microseconds, not a broker round-trip plus a ledger entry. |
| 8 | **Failure modes** | `ValidationError` (malformed — never retried, returned to the planner as a correction signal); broker 4xx (rejected — logged, not retried blindly); broker 5xx/timeout (unknown outcome — retry only with the same idempotency key, then reconcile against the ledger) |
| 9 | **Data sensitivity** | Order parameters are internal trading intent. Never logged to stdout in production, never sent to third-party evaluators, redacted from traces shown to the model on retry. |
| 10 | **Observability** | Every validation — pass or fail — emits a structured event: contract name, version, decision, rejection reason, latency. Rejection rate per contract is a dashboard metric, because a spike means the planner is degrading. Every agent-issued order carries `trace_id` so the order can be correlated back to the exact LLM reasoning step that produced it — without it, evaluating agent loops or debugging a rogue order is a forensic nightmare. |

Read that table again. Notice what it does: it converts "the agent can place orders" — a sentence that means nothing — into ten checkable claims. A junior engineer can implement any one of them. A reviewer can verify any one of them. A red-teamer can attack any one of them. That is the difference between a tool and a contract. A tool is a function. A contract is a function plus the complete statement of what it may do, what it must not do, and what happens when it is asked to do something outside its terms.

Notice field 6 in particular, because it is where most teams fail. Idempotency is not a nice-to-have for trading tools. Networks fail. Tool calls time out. Orchestrators retry. If "submit the same order twice because the first call's response was lost" is not a defined, tested behavior, your agent will double-fill the first time the network hiccups during a volatile open — and it will do it with perfect confidence, because from its perspective it only submitted one order. The contract makes the key mandatory precisely because the safe default does not exist.

## The schema: Pydantic as the bouncer

The contract table is the specification. Pydantic v2 is the enforcement. Here is the `SubmitOrderRequest` contract — verbatim from the live artifact for this chapter (`code/ch04/schemas.py`), runnable as-is:

```python
from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Broker vocabulary: closed sets. The agent cannot invent new order types,
# new symbols, or new meanings for old fields. If it tries, Pydantic says no.
# ---------------------------------------------------------------------------

OrderSide = Literal["buy", "sell"]
OrderType = Literal["market", "limit", "stop", "stop_limit"]
TimeInForce = Literal["day", "gtc", "ioc", "fok"]

#: The paper account is permissioned for exactly these names.
#: Anything else is a hallucinated symbol and must fail at the schema layer.
ALLOWED_SYMBOLS: frozenset = frozenset({"AAPL", "MSFT", "NVDA", "SPY", "QQQ", "AMD"})

#: Hard guardrails, paper dollars. The broker contract refuses to even
#: *consider* an order above this notional.
DEFAULT_MAX_NOTIONAL = Decimal("25000")

#: A limit price more than this far from the reference quote is either a
#: fat-finger or a prompt-injected sweep. Reject it as malformed.
LIMIT_PRICE_TOLERANCE = Decimal("0.05")  # ±5%


class SubmitOrderRequest(BaseModel):
    """Contract for the paper broker's `submit_order` tool.

    Every field is load-bearing:

    - ``symbol``: must be on the allowlist. The agent does not get to
      trade tickers the desk hasn't approved.
    - ``qty``: positive, 4-decimal fractional shares. Zero and negative
      quantities are nonsense orders; the broker must never see them.
    - ``idempotency_key``: REQUIRED. A retried tool call reuses the key
      and the broker dedupes it. A missing key means a retried order can
      double-fill. There is no safe default, so there is no default.
    - ``max_notional``: per-order dollar cap enforced in the schema, so a
      runaway qty can never become a $10M paper order by accident.
    - ``reference_price``: last known quote, used to sanity-check limits.
      Optional in the payload, but without it (or a limit price) notional
      cannot be computed and the order is rejected.
    """

    model_config = {"str_strip_whitespace": True, "extra": "forbid"}

    symbol: str
    side: OrderSide
    qty: Decimal = Field(gt=Decimal("0"), max_digits=18, decimal_places=4)
    order_type: OrderType
    limit_price: Decimal | None = Field(default=None, gt=Decimal("0"))
    stop_price: Decimal | None = Field(default=None, gt=Decimal("0"))
    time_in_force: TimeInForce = "day"
    idempotency_key: str = Field(min_length=8, max_length=64)
    max_notional: Decimal = Field(default=DEFAULT_MAX_NOTIONAL, gt=Decimal("0"))
    reference_price: Decimal | None = Field(default=None, gt=Decimal("0"))
    #: Correlates this order back to the LLM reasoning step ("thought")
    #: that produced it. Optional — a human-issued order has no thought —
    #: but every agent-issued order should carry one, or debugging a rogue
    #: order and evaluating agent loops becomes a forensic exercise.
    trace_id: str | None = Field(default=None, max_length=128)

    # -- field-level validators -----------------------------------------

    @field_validator("symbol")
    @classmethod
    def symbol_must_be_allowlisted(cls, v: str) -> str:
        v = v.upper()
        if v not in ALLOWED_SYMBOLS:
            raise ValueError(
                f"symbol {v!r} is not on the paper-account allowlist "
                f"{sorted(ALLOWED_SYMBOLS)}"
            )
        return v

    @field_validator("idempotency_key")
    @classmethod
    def idempotency_key_must_be_clean(cls, v: str) -> str:
        if any(ch.isspace() for ch in v):
            raise ValueError("idempotency_key must not contain whitespace")
        return v

    # -- cross-field contract: the order must make sense as a whole ------

    @model_validator(mode="after")
    def order_must_be_internally_consistent(self) -> "SubmitOrderRequest":
        # 1. Price fields must match the order type. A market order with a
        #    limit price is a contradiction; a stop order without a stop
        #    price is incomplete. Both are agent bugs, not broker problems.
        needs_limit = self.order_type in ("limit", "stop_limit")
        needs_stop = self.order_type in ("stop", "stop_limit")

        if needs_limit and self.limit_price is None:
            raise ValueError(f"order_type={self.order_type!r} requires limit_price")
        if not needs_limit and self.limit_price is not None:
            raise ValueError(
                f"order_type={self.order_type!r} must not carry limit_price"
            )
        if needs_stop and self.stop_price is None:
            raise ValueError(f"order_type={self.order_type!r} requires stop_price")
        if not needs_stop and self.stop_price is not None:
            raise ValueError(
                f"order_type={self.order_type!r} must not carry stop_price"
            )

        # 2. Notional cap. Effective price is the limit for limit orders,
        #    the stop trigger for stop orders (worst case: it fills at the
        #    trigger, never at the pre-trigger quote), otherwise the
        #    reference quote. No price, no notional, no order.
        if needs_limit:
            effective_price = self.limit_price
        elif needs_stop:
            effective_price = self.stop_price
        else:
            effective_price = self.reference_price
        if effective_price is None:
            raise ValueError(
                "cannot compute notional: provide limit_price (limit orders), "
                "stop_price (stop orders), or reference_price (market orders)"
            )
        notional = self.qty * effective_price
        if notional > self.max_notional:
            raise ValueError(
                f"notional ${notional:,.2f} exceeds max_notional "
                f"${self.max_notional:,.2f}"
            )

        # 3. Limit sanity (the fat-finger check). The anchor depends on the
        #    order type. A plain limit order is priced against the current
        #    quote — but a stop_limit's limit legitimately sits far from the
        #    quote, because breakout triggers live far from current prices by
        #    design. Anchoring the band to the quote would reject valid
        #    breakout orders; anchoring it to the stop trigger measures drift
        #    from the price the order was actually built around.
        if self.limit_price is not None:
            if self.order_type == "stop_limit":
                anchor = self.stop_price  # required for stop_limit (see step 1)
                anchor_name = "stop_price"
            else:
                anchor = self.reference_price
                anchor_name = "reference_price"
            if anchor is not None:
                drift = abs(self.limit_price - anchor) / anchor
                if drift > LIMIT_PRICE_TOLERANCE:
                    raise ValueError(
                        f"limit_price {self.limit_price} is {drift:.1%} away from "
                        f"{anchor_name} {anchor}; tolerance is "
                        f"{LIMIT_PRICE_TOLERANCE:.0%}"
                    )
        return self

    @property
    def notional(self) -> Decimal:
        """Dollar size of the order at the effective price.

        Uses the stop trigger for stop orders: a buy stop at $250 on a
        $230 quote sizes the order at $250, because that is where the
        buying power is actually consumed.
        """
        price = self.limit_price
        if price is None and self.order_type in ("stop", "stop_limit"):
            price = self.stop_price
        if price is None:
            price = self.reference_price
        assert price is not None  # guaranteed by the model validator
        return self.qty * price
```

A sharp reader will have noticed a gap: you cannot pass a Python class to a language model. The API boundary for function calling speaks JSON Schema, not Pydantic. So how does the planner know the rules before it emits the dictionary? The answer is that the definition sent to the model is *generated from the same class*:

```python
def tool_definition_for_planner() -> dict:
    """The JSON Schema the LLM sees when it decides what to emit."""
    return SubmitOrderRequest.model_json_schema()
```

Two layers, one source of truth. The model sees JSON Schema, because that is all the wire speaks — field names, types, the closed vocabularies, which fields are required. The boundary enforces Pydantic, because that is where the real logic lives — the notional math, the allowlist, the tolerance bands. If those two were maintained by hand, they would drift within a week: the planner would be playing by rules the bouncer does not enforce, or vice versa. Generating the wire format from the enforcement class makes drift structurally impossible. (All code in this book targets Python 3.10+, which is why you see `Decimal | None` instead of `Optional[Decimal]`.)

Several decisions here are deliberate and worth naming, because each one is a scar from a real failure mode:

**Closed vocabularies via `Literal`.** The agent cannot invent a `"trailing_peg"` order type or a `"yolo"` time-in-force. Pydantic rejects unknown literals before any business logic runs. This sounds trivial until you watch a model "helpfully" emit `order_type: "market_limit_hybrid"` because the prompt mentioned both words.

**`extra="forbid"`.** Unknown fields are rejected. A model that adds `secret_backdoor: true` to the payload — whether through hallucination or prompt injection — gets a `ValidationError`, not a silently ignored field. Silently ignoring unknown fields is how injected instructions survive: the parser shrugs, the downstream code reads the one field the attacker cared about.

**Symbol allowlist, not a regex.** A regex validates shape; an allowlist validates authority. `^[A-Z]{1,5}$` would happily approve `MOON`. The desk approved six symbols. The schema knows which six.

**The notional cap lives in the schema, not in a config file the planner can see.** This is the capability/authority split made concrete: the model may propose any quantity, but the maximum dollar size of a single order is not negotiable at planning time. It is a property of the contract.

**Limit sanity vs. the reference price.** A buy limit 20% above the quote is not aggression — it is either a fat-finger or an injected sweep instruction designed to look like one. The ±5% tolerance band turns "the model chose a weird price" from a trading decision into a schema violation, which means it gets corrected by the planner instead of executed by the broker. One refinement: for `stop_limit` orders the band is anchored to the **stop price**, not the quote — a breakout trigger lives far from the current price *by design*, so the fat-finger check must measure drift from the trigger the order was built around, not from a quote the order was never meant to execute at.

## Why Pydantic, and why not the alternatives

Three options exist for validating tool inputs, and two of them are traps.

The first trap is **prompting the model to emit correct JSON** — "be careful to include the idempotency key." This is not validation; it is hope with formatting. It fails exactly when you need it most, because the situations that produce malformed orders (confused context, injected instructions, degraded model quality at long context lengths) are the same situations that make the model ignore your careful instructions. Validation that depends on the thing being validated is not validation.

The second trap is **JSON Schema validated by a generic checker**. JSON Schema can express "qty must be a positive number" but it cannot express "notional must not exceed the cap given the effective price, where the effective price depends on the order type" — at least not without escaping into custom keywords that nobody reviews. Cross-field business rules are where real contracts live, and JSON Schema makes them second-class citizens. You end up with the shape checked by the schema and the actual safety logic scattered across helper functions that run at different times, in different orders, with different error conventions. That is how the 4x-oversize order survived in the old AlphaForge code: the JSON Schema said the qty was a valid number, and the notional check lived in a function that only ran on the happy path.

Pydantic v2 wins for one reason: **validators are code, co-located with the fields they protect, executed in a defined order, with one error type.** Field validators run first (is each value sane on its own?), then model validators run on the assembled whole (does the combination make sense?). The `ValidationError` carries every failure at once, with field paths, so the planner gets the complete correction signal in a single round trip instead of playing twenty questions. And because it is Python, the notional computation, the allowlist lookup, and the tolerance arithmetic are the real logic — not a parallel reimplementation in a schema DSL that drifts from the implementation. The schema *is* the implementation of the contract's preconditions. There is exactly one place where "what counts as a valid order" is defined, and it is this file.

The cancellation contract is deliberately tiny — reversibility should be the cheapest operation in the system — but it keeps the idempotency key, because "cancel, timeout, retry the cancel" must be a no-op rather than an incident:

```python
class CancelOrderRequest(BaseModel):
    """Contract for the paper broker's `cancel_order` tool.

    Cancellation is the reversibility path for every open order, so its
    contract is deliberately tiny — but it still carries an idempotency
    key, because "cancel, retry, cancel twice" must be a no-op, not a bug.
    """

    model_config = {"str_strip_whitespace": True, "extra": "forbid"}

    order_id: str = Field(min_length=1, max_length=64)
    idempotency_key: str = Field(min_length=8, max_length=64)
    reason: str | None = Field(default=None, max_length=280)
    #: Correlates the cancellation back to the reasoning step that issued
    #: it — the same observability story as SubmitOrderRequest.trace_id.
    trace_id: str | None = Field(default=None, max_length=128)
```

And the boundary itself is one function — the entire trust boundary between "the model suggested something" and "the broker will do it":

```python
def validate_submit_order(payload: dict) -> SubmitOrderRequest:
    """The tool-call boundary.

    The LLM emits a dict. This function is the entire trust boundary
    between "the model suggested something" and "the broker will do it".
    It returns a validated contract or raises pydantic.ValidationError.
    Nothing in between.
    """
    return SubmitOrderRequest.model_validate(payload)
```

It returns a validated contract or raises. Nothing in between. Every tool in the system gets one of these, and the orchestrator is forbidden from calling the broker with anything that has not passed through it.

## Four orders walk through the gate

Here is the contract doing its job. One valid order, then the three defects from the AlphaForge incident — each rejected locally, before any HTTP exists:

```
VALID   AAPL buy 10 @ 232.50 notional=$2,325.00
BAD-1    REJECTED locally: symbol
BAD-2    REJECTED locally: Value error, notional $115,900.00 exceeds max_notional $25,000.00 [type=value_error, input_value={'symbol': 'AAPL', 'side'...erence_price': '231.80'}, input_type=dict]
BAD-3    REJECTED locally: idempotency_key
```

Each rejection teaches the planner something different, and the difference matters for how the system recovers:

**BAD-1 (unknown symbol)** is a *knowledge* failure. The model believed MOON was tradable. The correction is factual — "the account is permissioned for AAPL, MSFT, NVDA, SPY, QQQ, AMD" — and the planner can re-plan immediately against the real universe. Note the security dimension: if the symbol had come from tool output (a scraped "hot stocks" list, a retrieved research note), this rejection is also the moment a prompt-injected ticker dies. The allowlist does not care where the symbol came from. It cares whether the desk approved it.

**BAD-2 (notional over cap)** is a *sizing* failure. The model wanted 500 shares; the contract allows roughly 107 at that price. The planner's correct response is to downsize, not to argue — the cap is not a suggestion. This is also the rejection that would have been a double-fill disaster combined with BAD-3's defect: an oversized order, retried without an idempotency key, is how paper accounts end up with positions that violate every risk limit simultaneously.

**BAD-3 (missing idempotency key)** is an *engineering* failure, and the most dangerous of the three. The order itself was perfectly reasonable — 5 shares of AAPL, well within cap. A human reviewer would approve it. But without the key, the retry semantics are undefined, and "undefined retry semantics on a money-moving tool" is the single most common cause of duplicate execution in agent systems. The contract refuses to distinguish "good order, missing key" from "bad order" because at the boundary, there is no such distinction. An order you cannot safely retry is an order you cannot safely send.

Look at what did *not* happen for each rejection. No HTTP request was constructed. No ledger row was written. No rate-limit budget was spent. No partial state exists anywhere that a recovery routine must clean up. The planner receives a structured `ValidationError`, which is genuinely useful information — "your symbol was wrong, your size was wrong, your key was missing" — and it can correct course. Compare that to the alternative: the broker returns a 422 three hundred milliseconds later, the orchestrator has to decide whether the order exists or not (outcome unknown — the theme of Chapter 9), and the trace now contains a failed external call that the evaluator must explain.

This is why the latency budget in the contract table matters and why it is measured in microseconds. Local rejection is not an optimization. It is the difference between "the agent made a mistake and corrected it" and "the agent made a mistake and the world now contains the consequences."

## FIG: Tool Contract Validation Flow

FIG: Sequence diagram, "Tool Contract Validation Flow." Five participants arranged left to right: **Planner (LLM)**, **Tool Gateway**, **Schema Validator (Pydantic)**, **Policy Engine**, **Paper Broker**. Arrows, top to bottom: (1) Planner → Tool Gateway: `submit_order` payload as raw dict (dashed arrow, labeled "suggestion, not obligation"). (2) Tool Gateway → Schema Validator: `SubmitOrderRequest.model_validate(payload)` (solid arrow, labeled "contract check"). Decision diamond inside Schema Validator: "valid?" (3a, reject path) Schema Validator → Tool Gateway: `ValidationError` with field-level reasons (solid red arrow, labeled "rejected locally, <1 ms"); Tool Gateway → Planner: structured correction signal listing the failed fields (dashed red arrow, labeled "no HTTP, no ledger, no side effects"); the flow ends here for invalid payloads — draw this path terminating at the Planner with a bold "✕ STOP" marker, making clear the Paper Broker was never contacted. (3b, accept path) Schema Validator → Tool Gateway: validated `SubmitOrderRequest` (solid green arrow, labeled "contract satisfied"). (4) Tool Gateway → Policy Engine: validated request (solid arrow, labeled "authority check: kill switch? buying power? position limits?"). Decision diamond inside Policy Engine: "authorized?" — its reject path mirrors the schema reject path (red arrow back to Planner, labeled "rejected by policy"). (5, authorized path) Policy Engine → Paper Broker: signed HTTP POST with idempotency key header (solid arrow, labeled "first network call in the entire flow"). (6) Paper Broker → Tool Gateway: order acknowledgment (solid arrow); Tool Gateway → Planner: `OrderAccepted` with broker order id (dashed arrow). Caption beneath: "The broker is the fifth participant and the last to hear about the order. Everything before it is local, cheap, and reversible." Style: clean technical sequence diagram, monospace labels, red for reject paths, green for the accept path, generous whitespace between the two decision diamonds.

## Schema validation is not policy

A careful reader will have noticed the Policy Engine in the figure and asked: if the schema already checks the notional cap, what is left for policy? The answer is the most important distinction in the chapter: **the schema checks shape; the policy checks state.**

The schema can verify that the order is well-formed — right fields, right types, internally consistent, within static bounds. It cannot know whether the kill switch was pulled thirty seconds ago, whether buying power is exhausted, whether this is the eleventh order in a minute from a runaway loop, or whether the portfolio is already 40% concentrated in the name being bought. Those are questions about the world, and the world changes between validation and execution. Policy is evaluated at execution time, against live state, and it can say no to a perfectly well-formed order.

This layering is deliberate defense in depth. The schema catches the model's mistakes — malformed, contradictory, out-of-bounds proposals — at zero cost. The policy catches the world's changes — revoked authority, depleted resources, regime shifts — at execution cost. Neither layer trusts the other to do its job, and neither trusts the planner at all. When Gemini reviewed the previous edition of this book, it flagged exactly this confusion: teams that put buying-power checks in the schema end up with stale authority, and teams that put shape checks in the policy end up paying broker round-trips to discover typos. Shape is static; check it statically. State is live; check it live.

Run it yourself: `python -m pytest code/ch04/ -q`. Twenty-four dots, zero network calls. That is the point.

**Exercise 1.** Add a `max_position_pct: Decimal` field to `SubmitOrderRequest` — the order's notional as a fraction of portfolio equity — and write a model validator that rejects any order exceeding 10% of a `portfolio_equity` field. Then argue, in three sentences, whether `portfolio_equity` belongs in the schema or in the Policy Engine from the figure, using the shape-vs-state distinction.

**Exercise 2.** The `±5%` limit tolerance is a static constant. Design (in prose plus one validator sketch) a *dynamic* tolerance that widens during the first and last 15 minutes of the trading session when spreads are naturally wide, and explain what new failure mode your dynamic band introduces — and which contract field (from the ten-field table) would catch it.
