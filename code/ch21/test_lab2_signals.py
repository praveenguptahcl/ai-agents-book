"""Lab 2 — Signal Generator Contract (Chapter 21).

RED lab: this file FAILS out of the box. That is the point. Your job is to
build the validation pipeline that turns it green. The passing implementation
is the answer key in Appendix B — it does not appear in this chapter.

The desk's situation: an LLM research agent proposes trades. It is
enthusiastic, fluent, and intermittently unacquainted with reality. Between
its proposals and the executor stands exactly one thing: the pipeline you
are about to build.

You are GIVEN:
  * ``SIGNAL_JSON_SCHEMA`` — the strict-mode provider schema (Chapter 5).
    It guarantees shape. It cannot express ranges.
  * ``SignalProposal`` — the Pydantic contract gate (Chapter 4).
    It guarantees judgment: ranges, the universe allowlist, the notional cap.
  * ``erratic_llm_responses()`` — the erratic-LLM fixture. Deterministic:
    the same list every run, so RED is reproducible and GREEN means something.
  * ``REASON_CODES`` — the closed set of rejection reasons. A rejection
    without a name is a shrug; this pipeline does not shrug.

You BUILD:
  * ``SignalPipeline.process(raw)`` — parse → schema-check → contract-gate
    → dedupe. Returns ``("accepted", None)`` for a fully valid proposal, or
    ``("rejected", <one of REASON_CODES>)`` otherwise.

Pipeline order matters. A malformed payload dies at parse. A well-formed
payload with a missing field dies at the schema. A well-shaped payload with
confidence 1.7 dies at the contract — the schema cannot express ranges, so
this is the layer split the lab is proving. A valid proposal seen before
dies at dedupe: the same id twice is a retry or a replay, and the pipeline
treats both the same way — once.
"""
from __future__ import annotations

import json
from typing import Literal

import pytest
from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# GIVEN: the paper universe and the notional cap (from Chapter 4).
# ---------------------------------------------------------------------------

#: The desk is permissioned for exactly these names. Anything else is a
#: hallucinated symbol and must fail at the contract gate.
ALLOWED_SYMBOLS = frozenset({"AAPL", "MSFT", "NVDA", "SPY", "QQQ", "AMD"})

#: Hard guardrails, paper dollars. A single proposal may not commit more
#: than this capital. A $5.9B allocation to SPY is not a typo the schema
#: can catch — it is a judgment the contract must make.
MAX_NOTIONAL = 25_000.0

# ---------------------------------------------------------------------------
# GIVEN: the strict-mode provider schema (Chapter 5).
#
# Written the way OpenAI strict mode demands: closed objects, every property
# required, closed enums. Note what strict mode CANNOT express: ranges.
# "confidence must be in [0, 1]" is not in this schema. That is Chapter 4's
# job, and the lab proves the two layers compose.
# ---------------------------------------------------------------------------

SIGNAL_JSON_SCHEMA = {
    "name": "signal_proposal",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "proposal_id",
            "symbol",
            "side",
            "capital",
            "confidence",
            "rationale",
        ],
        "properties": {
            "proposal_id": {"type": "string"},
            "symbol": {"type": "string"},
            # Intentions, not orders: long/short/flat. An order verb here
            # is a vocabulary failure and dies at the schema.
            "side": {"type": "string", "enum": ["long", "short", "flat"]},
            "capital": {"type": "number"},
            "confidence": {"type": "number"},
            "rationale": {"type": "string"},
        },
    },
}

#: Every rejection carries one of these names. Closed set: if your pipeline
#: wants a fifth reason, the pipeline is wrong, not the set.
REASON_CODES = frozenset(
    {
        "MALFORMED_JSON",  # parse failed: truncated, not JSON at all
        "SCHEMA_VIOLATION",  # shape failed: missing field, wrong type, bad enum
        "CONTRACT_VIOLATION",  # judgment failed: range, allowlist, notional cap
        "DUPLICATE_ID",  # seen before: retry or replay, accepted exactly once
    }
)

Decision = Literal["accepted", "rejected"]
Verdict = tuple[Decision, str | None]


# ---------------------------------------------------------------------------
# GIVEN: the Pydantic contract gate (Chapter 4).
#
# Everything the provider schema cannot express lives here: confidence in
# [0, 1], the symbol allowlist, the notional cap that kills the absurd-but-
# well-shaped proposal. extra="forbid" keeps the closed world closed.
# ---------------------------------------------------------------------------
class SignalProposal(BaseModel):
    """The contract a signal must survive before any executor hears of it."""

    model_config = {"extra": "forbid", "frozen": True}

    proposal_id: str = Field(min_length=8, max_length=64)
    symbol: str
    # An intention, not an order: long/short/flat with a capital
    # commitment. The strategy never touches orders — the executor does.
    side: Literal["long", "short", "flat"]
    capital: float = Field(gt=0)
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1, max_length=2000)

    @field_validator("symbol")
    @classmethod
    def symbol_must_be_allowlisted(cls, v: str) -> str:
        v = v.upper()
        if v not in ALLOWED_SYMBOLS:
            raise ValueError(f"symbol {v!r} is not on the paper-account allowlist")
        return v

    @model_validator(mode="after")
    def capital_must_fit_the_cap(self) -> "SignalProposal":
        if self.capital > MAX_NOTIONAL:
            raise ValueError(
                f"capital ${self.capital:,.0f} exceeds the "
                f"${MAX_NOTIONAL:,.0f} cap"
            )
        return self


# ---------------------------------------------------------------------------
# GIVEN: the erratic-LLM fixture.
#
# Nine raw model outputs. One is valid. Eight are hostile in eight different
# ways — the exact failure taxonomy from Chapters 4 and 5, plus the Ch 2
# lesson (structurally valid, semantically absurd) and the replay case.
# Deterministic: no randomness, so RED today is RED tomorrow.
# ---------------------------------------------------------------------------
def erratic_llm_responses() -> list[tuple[str, str]]:
    """(case_name, raw_model_output) pairs. One valid; eight hostile."""
    dup = (
        '{"proposal_id": "sig-0008-deadbeef", "symbol": "QQQ", "side": "flat", '
        '"capital": 5000.0, "confidence": 0.51, '
        '"rationale": "no edge; sitting out"}'
    )
    return [
        (
            "valid",
            '{"proposal_id": "sig-0001-deadbeef", "symbol": "AAPL", '
            '"side": "long", "capital": 10000.0, "confidence": 0.72, '
            '"rationale": "momentum continuation, volume confirms"}',
        ),
        (
            # The schema's required list catches this: no "side".
            "missing_field",
            '{"proposal_id": "sig-0002-deadbeef", "symbol": "MSFT", '
            '"capital": 10000.0, "confidence": 0.60, '
            '"rationale": "forgot the side entirely"}',
        ),
        (
            # Strict mode cannot express ranges, so the schema PASSES this.
            # The contract gate must kill it: confidence 1.7 is not a belief.
            "confidence_out_of_range",
            '{"proposal_id": "sig-0003-deadbeef", "symbol": "NVDA", '
            '"side": "short", "capital": 5000.0, "confidence": 1.7, '
            '"rationale": "extremely sure"}',
        ),
        (
            # Fail-plausible, the Ch 5 canonical: crisp rationale, invented
            # sixth ticker. The allowlist is the only layer that knows.
            "unknown_symbol",
            '{"proposal_id": "sig-0004-deadbeef", "symbol": "GME", '
            '"side": "long", "capital": 10000.0, "confidence": 0.80, '
            '"rationale": "meme momentum"}',
        ),
        (
            # Closed enum: "buy" is an order verb, not an intention.
            # Shape failure, not judgment — the signal may never speak
            # orders.
            "invalid_side",
            '{"proposal_id": "sig-0005-deadbeef", "symbol": "SPY", '
            '"side": "buy", "capital": 10000.0, "confidence": 0.50, '
            '"rationale": "wrong vocabulary"}',
        ),
        (
            # Truncated mid-rationale. Parse dies first; nothing downstream
            # ever sees it.
            "malformed_json",
            '{"proposal_id": "sig-0006-deadbeef", "symbol": "QQQ", '
            '"side": "long", "capital": 10000.0, "confidence": 0.66, '
            '"rationale": "trunca',
        ),
        (
            # THE Ch 2 lesson: structurally valid, semantically absurd.
            # Every shape check passes. A $5.9B capital allocation to SPY
            # against a $25k cap. Only the contract knows.
            "absurd_size",
            '{"proposal_id": "sig-0007-deadbeef", "symbol": "SPY", '
            '"side": "long", "capital": 5900000000.0, "confidence": 0.90, '
            '"rationale": "sizing up"}',
        ),
        ("duplicate_first", dup),
        # Same proposal_id as duplicate_first: a retry, or a replay.
        # The pipeline accepts each id exactly once.
        ("duplicate_second", dup),
    ]


# ---------------------------------------------------------------------------
# YOUR CODE HERE: the validation pipeline.
#
# Build SignalPipeline.process(raw) -> (decision, reason):
#   1. PARSE the raw string as JSON. Failure -> ("rejected", "MALFORMED_JSON").
#   2. SCHEMA-CHECK the parsed dict against SIGNAL_JSON_SCHEMA (required
#      fields, types, the closed side enum). Failure -> SCHEMA_VIOLATION.
#   3. CONTRACT-GATE through SignalProposal (ranges, allowlist, notional).
#      Failure -> CONTRACT_VIOLATION.
#   4. DEDUPE on proposal_id. Seen before -> ("rejected", "DUPLICATE_ID").
#      Otherwise record the id and -> ("accepted", None).
#
# Every rejection reason must be a member of REASON_CODES.
# ---------------------------------------------------------------------------
class SignalPipeline:
    """Parse → schema-check → contract-gate → dedupe. You build this."""

    def __init__(self) -> None:
        self._seen_ids: set[str] = set()

    def process(self, raw: str) -> Verdict:
        raise NotImplementedError(
            "Lab 2 RED: build the pipeline — parse, schema-check, "
            "contract-gate, dedupe — then watch this file go green."
        )


# ---------------------------------------------------------------------------
# The tests. They fail until the pipeline exists. Read them as the spec:
# each test names the exact behavior your process() must exhibit.
# ---------------------------------------------------------------------------
@pytest.fixture()
def pipeline() -> SignalPipeline:
    return SignalPipeline()


def _case(name: str) -> str:
    return dict(erratic_llm_responses())[name]


def test_valid_proposal_accepted(pipeline: SignalPipeline) -> None:
    decision, reason = pipeline.process(_case("valid"))
    assert decision == "accepted"
    assert reason is None


def test_missing_field_rejected_with_named_reason(
    pipeline: SignalPipeline,
) -> None:
    decision, reason = pipeline.process(_case("missing_field"))
    assert decision == "rejected"
    assert reason == "SCHEMA_VIOLATION"


def test_confidence_out_of_range_dies_at_contract_not_schema(
    pipeline: SignalPipeline,
) -> None:
    # Strict mode cannot express ranges, so the schema PASSES confidence 1.7.
    # This test pins the layer split: the kill must come from the contract.
    decision, reason = pipeline.process(_case("confidence_out_of_range"))
    assert decision == "rejected"
    assert reason == "CONTRACT_VIOLATION"


def test_unknown_symbol_rejected(pipeline: SignalPipeline) -> None:
    decision, reason = pipeline.process(_case("unknown_symbol"))
    assert decision == "rejected"
    assert reason == "CONTRACT_VIOLATION"


def test_invalid_side_rejected(pipeline: SignalPipeline) -> None:
    decision, reason = pipeline.process(_case("invalid_side"))
    assert decision == "rejected"
    assert reason == "SCHEMA_VIOLATION"


def test_malformed_json_rejected(pipeline: SignalPipeline) -> None:
    decision, reason = pipeline.process(_case("malformed_json"))
    assert decision == "rejected"
    assert reason == "MALFORMED_JSON"


def test_absurd_size_rejected_at_contract_gate(
    pipeline: SignalPipeline,
) -> None:
    # A $5.9B capital allocation to SPY is perfectly shaped JSON. Every
    # shape check passes. The rejection must come from the contract's
    # capital cap — this is the Chapter 2 lesson wearing a lab coat.
    decision, reason = pipeline.process(_case("absurd_size"))
    assert decision == "rejected"
    assert reason == "CONTRACT_VIOLATION"


def test_duplicate_proposal_id_accepted_exactly_once(
    pipeline: SignalPipeline,
) -> None:
    first_decision, _ = pipeline.process(_case("duplicate_first"))
    assert first_decision == "accepted"
    second_decision, second_reason = pipeline.process(_case("duplicate_second"))
    assert second_decision == "rejected"
    assert second_reason == "DUPLICATE_ID"


def test_every_rejection_carries_a_closed_set_reason() -> None:
    hostile = [
        "missing_field",
        "confidence_out_of_range",
        "unknown_symbol",
        "invalid_side",
        "malformed_json",
        "absurd_size",
    ]
    for name in hostile:
        decision, reason = SignalPipeline().process(_case(name))
        assert decision == "rejected", name
        assert reason in REASON_CODES, (name, reason)


def test_pipeline_is_deterministic() -> None:
    raw = _case("valid")
    assert SignalPipeline().process(raw) == SignalPipeline().process(raw)
    raw_bad = _case("absurd_size")
    assert SignalPipeline().process(raw_bad) == SignalPipeline().process(
        raw_bad
    )
