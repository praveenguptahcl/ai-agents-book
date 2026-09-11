"""Lab 2 answer key (Appendix B) — the reference SignalPipeline.

parse -> schema-check -> contract-gate -> dedupe.

The layer split is the whole lesson. The provider schema (Ch 5, strict
mode) guarantees SHAPE: required fields, types, the closed side enum. It
cannot express ranges, so confidence 1.7 sails through it. The Pydantic
contract (Ch 4) guarantees JUDGMENT: confidence in [0, 1], the symbol
allowlist, the notional cap that kills the structurally-valid-but-absurd
proposal. Each layer kills what only it can see; a rejection's name says
which layer fired.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_lab2_signals import (  # noqa: E402 — the lab's GIVEN fixtures
    SIGNAL_JSON_SCHEMA,
    REASON_CODES,
    SignalProposal,
)

Verdict = tuple[Literal["accepted", "rejected"], "str | None"]

_SCHEMA = SIGNAL_JSON_SCHEMA["schema"]


def _is_number(value) -> bool:
    # bool is a subclass of int; True is not a quantity.
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _schema_check(data: dict) -> bool:
    """The strict-mode shape check, implemented by hand.

    Closed object (additionalProperties: false), every property required,
    closed side enum. This is exactly what the provider guarantees — and
    exactly what it cannot exceed. Ranges are not expressible here; the
    contract gate owns them.
    """
    required = _SCHEMA["required"]
    props = _SCHEMA["properties"]
    if any(key not in data for key in required):
        return False
    if any(key not in props for key in data):
        return False
    for key, spec in props.items():
        value = data[key]
        kind = spec["type"]
        if kind == "string" and not isinstance(value, str):
            return False
        if kind == "number" and not _is_number(value):
            return False
        if "enum" in spec and value not in spec["enum"]:
            return False
    return True


class SignalPipeline:
    """Parse -> schema-check -> contract-gate -> dedupe.

    Every rejection carries one of REASON_CODES: MALFORMED_JSON (parse),
    SCHEMA_VIOLATION (shape), CONTRACT_VIOLATION (judgment), DUPLICATE_ID
    (replay). A rejection without a name is a shrug; this pipeline does
    not shrug.
    """

    def __init__(self) -> None:
        self._seen_ids: set[str] = set()

    def process(self, raw: str) -> Verdict:
        # 1. PARSE. A truncated payload dies here; nothing downstream
        #    ever sees it.
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError, TypeError):
            return ("rejected", "MALFORMED_JSON")
        if not isinstance(data, dict):
            return ("rejected", "SCHEMA_VIOLATION")

        # 2. SCHEMA-CHECK. Shape, not judgment: missing fields, wrong
        #    types, bad enums die here. confidence 1.7 PASSES this layer
        #    by design — strict mode cannot express ranges.
        if not _schema_check(data):
            return ("rejected", "SCHEMA_VIOLATION")

        # 3. CONTRACT-GATE. Everything the schema cannot express: the
        #    [0, 1] confidence range, the symbol allowlist, the notional
        #    cap. extra="forbid" keeps the closed world closed.
        try:
            proposal = SignalProposal(**data)
        except ValidationError:
            return ("rejected", "CONTRACT_VIOLATION")

        # 4. DEDUPE. The same id twice is a retry or a replay; each id is
        #    accepted exactly once. (Process-local: the production answer
        #    is Ch 14's ledger / Ch 4's idempotency keys.)
        if proposal.proposal_id in self._seen_ids:
            return ("rejected", "DUPLICATE_ID")
        self._seen_ids.add(proposal.proposal_id)
        return ("accepted", None)


assert set(REASON_CODES) == {
    "MALFORMED_JSON", "SCHEMA_VIOLATION",
    "CONTRACT_VIOLATION", "DUPLICATE_ID",
}, "the lab's closed reason set changed; the key must be re-derived"
