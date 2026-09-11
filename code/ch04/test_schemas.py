"""Chapter 4 — pytest: the contract holds at the boundary.

Every test below simulates what the LLM actually emits (a raw dict) and
asserts on what the tool layer does with it: accept, or reject with the
right error, before any HTTP exists.
"""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from schemas import (
    ALLOWED_SYMBOLS,
    CancelOrderRequest,
    SubmitOrderRequest,
    validate_submit_order,
)


def _base_order(**overrides):
    payload = {
        "symbol": "AAPL",
        "side": "buy",
        "qty": 10,
        "order_type": "limit",
        "limit_price": 232.50,
        "time_in_force": "day",
        "idempotency_key": "alphaforge-2026-09-11-0001",
        "reference_price": 231.80,
    }
    payload.update(overrides)
    return payload


# -- the happy path ---------------------------------------------------------

def test_valid_limit_order_passes_and_computes_notional():
    order = validate_submit_order(_base_order())
    assert order.symbol == "AAPL"          # normalized to uppercase
    assert order.notional == Decimal("10") * Decimal("232.50")


def test_symbol_is_case_normalized():
    order = validate_submit_order(_base_order(symbol="nvda"))
    assert order.symbol == "NVDA"


def test_valid_cancel_passes():
    cancel = CancelOrderRequest(
        order_id="ord_9f31ac",
        idempotency_key="alphaforge-2026-09-11-cancel-01",
        reason="signal flipped to flat before fill",
    )
    assert cancel.order_id == "ord_9f31ac"


# -- the three headline rejections -------------------------------------------

def test_unknown_symbol_rejected_locally():
    with pytest.raises(ValidationError) as exc:
        validate_submit_order(_base_order(symbol="MOON"))
    assert "allowlist" in str(exc.value)


def test_notional_over_cap_rejected_locally():
    # 500 shares x $231.80 = $115,900 > $25,000 cap
    with pytest.raises(ValidationError) as exc:
        validate_submit_order(_base_order(qty=500, order_type="market",
                                          limit_price=None,
                                          idempotency_key="alphaforge-2026-09-11-0003"))
    assert "notional" in str(exc.value).lower()


def test_missing_idempotency_key_rejected_locally():
    payload = _base_order()
    del payload["idempotency_key"]
    with pytest.raises(ValidationError) as exc:
        validate_submit_order(payload)
    assert "idempotency_key" in str(exc.value)


# -- the contract is strict about shape, not just values ----------------------

def test_limit_order_without_limit_price_rejected():
    with pytest.raises(ValidationError, match="requires limit_price"):
        validate_submit_order(_base_order(limit_price=None))


def test_market_order_with_limit_price_rejected():
    with pytest.raises(ValidationError, match="must not carry limit_price"):
        validate_submit_order(_base_order(order_type="market",
                                          reference_price=231.80))


def test_limit_far_from_reference_rejected_as_malformed():
    # $280 vs $231.80 reference = ~21% drift; tolerance is 5%.
    with pytest.raises(ValidationError, match="tolerance"):
        validate_submit_order(_base_order(limit_price=280.00))


def test_zero_quantity_rejected():
    with pytest.raises(ValidationError):
        validate_submit_order(_base_order(qty=0))


def test_unknown_fields_rejected():
    with pytest.raises(ValidationError):
        validate_submit_order(_base_order(secret_backdoor="true"))


def test_cancel_requires_order_id():
    with pytest.raises(ValidationError):
        CancelOrderRequest(order_id="", idempotency_key="alphaforge-cancel-02")


def test_every_allowlisted_symbol_accepts_a_valid_order():
    for symbol in ALLOWED_SYMBOLS:
        order = validate_submit_order(_base_order(symbol=symbol))
        assert order.symbol == symbol


# -- stop orders: the trigger prices the order, not the stale quote --------

def test_stop_order_uses_stop_price_for_notional():
    # 105 shares x $250 stop = $26,250 > $25,000 cap. At the $230
    # reference quote it would be $24,150 and would PASS — sizing the
    # order at the quote instead of the trigger is the bug that blows
    # through buying power at execution time.
    with pytest.raises(ValidationError, match="notional"):
        validate_submit_order(_base_order(
            order_type="stop",
            limit_price=None,
            stop_price=250.00,
            reference_price=230.00,
            qty=105,
            idempotency_key="alphaforge-2026-09-11-stop-01",
        ))


def test_stop_order_within_cap_uses_trigger_price():
    # 100 shares x $250 = $25,000 — exactly at the cap.
    order = validate_submit_order(_base_order(
        order_type="stop",
        limit_price=None,
        stop_price=250.00,
        reference_price=230.00,
        qty=100,
        idempotency_key="alphaforge-2026-09-11-stop-02",
    ))
    assert order.notional == Decimal("100") * Decimal("250.00")


def test_stop_order_without_stop_price_rejected():
    with pytest.raises(ValidationError, match="requires stop_price"):
        validate_submit_order(_base_order(
            order_type="stop",
            limit_price=None,
            idempotency_key="alphaforge-2026-09-11-stop-03",
        ))


def test_stop_order_must_not_carry_limit_price():
    with pytest.raises(ValidationError, match="must not carry limit_price"):
        validate_submit_order(_base_order(
            order_type="stop",
            stop_price=250.00,
            idempotency_key="alphaforge-2026-09-11-stop-04",
        ))


def test_stop_limit_requires_both_prices():
    with pytest.raises(ValidationError, match="requires limit_price"):
        validate_submit_order(_base_order(
            order_type="stop_limit",
            stop_price=250.00,
            limit_price=None,
            idempotency_key="alphaforge-2026-09-11-stoplimit-01",
        ))
    with pytest.raises(ValidationError, match="requires stop_price"):
        validate_submit_order(_base_order(
            order_type="stop_limit",
            idempotency_key="alphaforge-2026-09-11-stoplimit-02",
        ))


def test_stop_limit_valid_and_priced_at_limit():
    # Honest breakout geometry: the quote sits at $230, the stop trigger at
    # $250, the limit cap at $251. The limit is ~9% from the quote — which
    # would fail a quote-anchored drift check — but only 0.4% from the stop
    # trigger, so the stop-anchored check passes it. The limit remains the
    # worst case for notional.
    order = validate_submit_order(_base_order(
        order_type="stop_limit",
        limit_price=251.00,
        stop_price=250.00,
        reference_price=230.00,
        qty=90,
        idempotency_key="alphaforge-2026-09-11-stoplimit-03",
    ))
    assert order.notional == Decimal("90") * Decimal("251.00")


def test_stop_limit_with_limit_far_from_stop_rejected():
    # The fat-finger check is anchored to the stop trigger for stop_limit
    # orders: a limit 20% above the $250 trigger is malformed even though
    # the trigger itself is far from the quote. (qty sized so the notional
    # cap passes — this test must isolate the drift check, not the cap.)
    with pytest.raises(ValidationError, match="tolerance"):
        validate_submit_order(_base_order(
            order_type="stop_limit",
            limit_price=300.00,
            stop_price=250.00,
            reference_price=230.00,
            qty=80,
            idempotency_key="alphaforge-2026-09-11-stoplimit-04",
        ))


def test_market_order_priced_at_reference():
    order = validate_submit_order(_base_order(
        order_type="market",
        limit_price=None,
        reference_price=231.80,
        idempotency_key="alphaforge-2026-09-11-market-01",
    ))
    assert order.notional == Decimal("10") * Decimal("231.80")


# -- traceability: every agent-issued order carries its thought --------------

def test_trace_id_round_trips_on_submit():
    order = validate_submit_order(_base_order(trace_id="thought-7f3a-budget-review"))
    assert order.trace_id == "thought-7f3a-budget-review"


def test_trace_id_optional_on_submit():
    order = validate_submit_order(_base_order())
    assert order.trace_id is None


def test_trace_id_round_trips_on_cancel():
    cancel = CancelOrderRequest(
        order_id="ord_9f31ac",
        idempotency_key="alphaforge-cancel-03",
        trace_id="thought-7f3a-budget-review",
    )
    assert cancel.trace_id == "thought-7f3a-budget-review"


# -- strict mode: the smuggling vectors stay closed -------------------------

def test_string_quantity_rejected_not_coerced():
    # "10" looks like a number but is not one. Strict mode must refuse
    # it, not silently cast it — string-to-number is the coercion an
    # injected payload relies on.
    with pytest.raises(ValidationError):
        payload = _base_order()
        payload["qty"] = "10"
        validate_submit_order(payload)


def test_string_prices_rejected_not_coerced():
    with pytest.raises(ValidationError):
        payload = _base_order()
        payload["limit_price"] = "232.50"
        validate_submit_order(payload)
    with pytest.raises(ValidationError):
        payload = _base_order(order_type="market", limit_price=None)
        payload["reference_price"] = "231.80"
        validate_submit_order(payload)


def test_boolean_quantity_rejected():
    # bool subclasses int; True must not become a quantity of 1.
    with pytest.raises(ValidationError):
        validate_submit_order(_base_order(qty=True))


def test_json_numbers_accepted_int_and_float():
    # The wire speaks JSON: int and float are legitimate numeric types.
    order = validate_submit_order(_base_order(qty=10, limit_price=232.50,
                                              reference_price=231.80))
    assert order.qty == Decimal("10")
    assert order.limit_price == Decimal("232.50")


def test_validated_order_is_frozen():
    # A validated contract is immutable: nothing downstream may mutate an
    # order after the boundary approved it.
    order = validate_submit_order(_base_order())
    with pytest.raises(ValidationError):
        order.qty = Decimal("999999")


def test_validated_cancel_is_frozen():
    cancel = CancelOrderRequest(
        order_id="ord_9f31ac",
        idempotency_key="alphaforge-cancel-04",
    )
    with pytest.raises(ValidationError):
        cancel.order_id = "ord_mutated"
