"""Chapter 4 — Strict tool contracts for the paper broker.

Thesis: a tool is not a function the agent "calls". It is a contract
with typed inputs, explicit side effects, and a bounded blast radius.
This module enforces the contract LOCALLY with Pydantic v2, before any
HTTP request leaves the process.

Rule of this chapter: an invalid order dies here, in Python, with a
ValidationError. It never touches the broker. No partial fills, no
rejected orders burning rate limits, no malformed requests polluting
the write-ahead ledger.

PAPER ONLY. No real money, no real keys, no real broker endpoints.
"""

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


def validate_submit_order(payload: dict) -> SubmitOrderRequest:
    """The tool-call boundary.

    The LLM emits a dict. This function is the entire trust boundary
    between "the model suggested something" and "the broker will do it".
    It returns a validated contract or raises pydantic.ValidationError.
    Nothing in between.
    """
    return SubmitOrderRequest.model_validate(payload)


def tool_definition_for_planner() -> dict:
    """The JSON Schema the LLM sees when it decides what to emit."""
    return SubmitOrderRequest.model_json_schema()


if __name__ == "__main__":
    # -- one valid order ---------------------------------------------------
    good = validate_submit_order(
        {
            "symbol": "aapl",  # normalized to AAPL by the validator
            "side": "buy",
            "qty": "10",
            "order_type": "limit",
            "limit_price": "232.50",
            "time_in_force": "day",
            "idempotency_key": "alphaforge-2026-09-11-0001",
            "reference_price": "231.80",
        }
    )
    print(f"VALID   {good.symbol} {good.side} {good.qty} @ {good.limit_price} "
          f"notional=${good.notional:,.2f}")

    # -- three rejections, each dying locally ------------------------------
    bad_payloads = [
        # 1. Unknown symbol: the agent hallucinated a ticker.
        {
            "symbol": "MOON",
            "side": "buy",
            "qty": "10",
            "order_type": "market",
            "idempotency_key": "alphaforge-2026-09-11-0002",
            "reference_price": "12.00",
        },
        # 2. Notional over the cap: 500 shares x $231.80 = $115,900.
        {
            "symbol": "AAPL",
            "side": "buy",
            "qty": "500",
            "order_type": "market",
            "idempotency_key": "alphaforge-2026-09-11-0003",
            "reference_price": "231.80",
        },
        # 3. Missing idempotency key: a retry could double-fill.
        {
            "symbol": "AAPL",
            "side": "sell",
            "qty": "5",
            "order_type": "market",
            "reference_price": "231.80",
        },
    ]
    for i, payload in enumerate(bad_payloads, start=1):
        try:
            validate_submit_order(payload)
            print(f"BAD-{i}    UNEXPECTEDLY PASSED (this is a bug)")
        except Exception as e:  # noqa: BLE001 — demo prints the rejection
            first_line = str(e).splitlines()[1] if "\n" in str(e) else str(e)
            print(f"BAD-{i}    REJECTED locally: {first_line.strip()}")
