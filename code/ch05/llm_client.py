"""Ch 5: Provider Integration & Strict Schemas.

Real OpenAI SDK (openai>=1.40) structured-output client for AlphaForge
signal proposals. The LLM proposes policy (a trading signal); it never
decides authority. Every response is validated against a strict JSON
schema, a universe allowlist, and numeric bounds before it is trusted.

Key API surface (openai>=1.40, exact):
    from openai import OpenAI
    client = OpenAI()                      # reads OPENAI_API_KEY from env
    client.chat.completions.create(
        model="gpt-4o-mini-2024-07-18",
        messages=[{"role": "user", "content": "..."}],
        response_format={"type": "json_schema",
                        "json_schema": {"name": "...", "schema": {...},
                                        "strict": True}},
    )

The module never imports openai at top level: `OpenAIClient` takes an
already-constructed client (dependency injection), so unit tests can
substitute a fake with zero network access. Live wiring happens only in
`make_openai_client()`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence


# ---------------------------------------------------------------------------
# The contract: what the model is allowed to say
# ---------------------------------------------------------------------------
#
# Strict-mode note: OpenAI's strict:true schema subset supports keys,
# types, enums, required, and additionalProperties — but NOT numeric or
# string constraints (minimum, maximum, minLength, ...). Those keywords
# are rejected with a 400 on the wire. The ranges therefore live in
# _check_bounds, our code's golden reference: the provider envelope
# guarantees shape (keys + types); our code guarantees meaning.

SIGNAL_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "symbol": {
            "type": "string",
            "description": "Ticker from the approved trading universe.",
        },
        "direction": {
            "type": "string",
            "enum": ["long", "short", "flat"],
            "description": "Proposed position direction.",
        },
        "confidence": {
            "type": "number",
            "description": "Model self-reported confidence, 0 to 1 "
                           "(range enforced locally; strict mode has no ranges).",
        },
        "rationale": {
            "type": "string",
            "description": "One or two sentences explaining the proposal "
                           "(non-empty enforced locally).",
        },
        "max_position_pct": {
            "type": "number",
            "description": "Maximum portfolio percent the proposer recommends, "
                           "0 to 100 (range enforced locally).",
        },
    },
    "required": ["symbol", "direction", "confidence",
                 "rationale", "max_position_pct"],
}

RESPONSE_FORMAT: Dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "signal_proposal",
        "schema": SIGNAL_SCHEMA,
        "strict": True,
    },
}


@dataclass(frozen=True)
class SignalProposal:
    """A validated proposal. A proposal is not an order; it is a request
    for authority that downstream gates (Ch 6+) will accept or reject."""

    symbol: str
    direction: str          # long | short | flat
    confidence: float       # 0.0 .. 1.0
    rationale: str
    max_position_pct: float  # 0.0 .. 100.0


@dataclass(frozen=True)
class SignalResult:
    """The per-call result: a validated proposal plus its audit trail.

    The caller owns `attempts` — log it, mine it for eval fixtures, or
    drop it. The client keeps no per-call state, so a long-running daemon
    cannot leak memory through its own audit trail.
    """

    proposal: SignalProposal
    attempts: List[Any]     # ordered raw responses, including failures


class SchemaViolation(Exception):
    """Raised when the model response cannot be coerced into the contract."""

    def __init__(self, message: str, raw: Any = None) -> None:
        super().__init__(message)
        self.raw = raw


# ---------------------------------------------------------------------------
# Local validation (deterministic, no model involved)
# ---------------------------------------------------------------------------

def _check_bounds(d: Mapping[str, Any]) -> List[str]:
    """The golden reference: every constraint the provider envelope cannot
    express (ranges, non-empty strings, enums, symbol shape) is checked
    here, deterministically, with no model involved."""
    problems: List[str] = []
    for key in SIGNAL_SCHEMA["required"]:
        if key not in d:
            problems.append(f"missing required field: {key}")
    extra = set(d) - set(SIGNAL_SCHEMA["properties"])
    if extra:
        problems.append(f"unexpected fields: {sorted(extra)}")
    if "symbol" in d and (not isinstance(d["symbol"], str)
                          or not d["symbol"].strip()):
        problems.append(f"bad symbol: {d['symbol']!r}")
    if "direction" in d and d["direction"] not in ("long", "short", "flat"):
        problems.append(f"bad direction: {d['direction']!r}")
    for key, lo, hi in (("confidence", 0.0, 1.0),
                        ("max_position_pct", 0.0, 100.0)):
        if key in d:
            try:
                v = float(d[key])
            except (TypeError, ValueError):
                problems.append(f"{key} not numeric: {d[key]!r}")
                continue
            if not (lo <= v <= hi):
                problems.append(f"{key}={v} outside [{lo}, {hi}]")
    if "rationale" in d and not str(d["rationale"]).strip():
        problems.append("rationale is empty")
    return problems


def validate_signal(raw: Any, universe: Sequence[str]) -> SignalProposal:
    """Parse + validate a decoded JSON object against the contract.

    The universe allowlist is the anti-hallucination gate: a plausible
    ticker that is not in the approved universe is rejected here, before
    it can become a position.
    """
    if not isinstance(raw, dict):
        raise SchemaViolation(f"response is not a JSON object: {type(raw).__name__}",
                              raw=raw)
    problems = _check_bounds(raw)
    symbol = raw.get("symbol")
    if isinstance(symbol, str) and symbol not in set(universe):
        problems.append(f"symbol {symbol!r} not in approved universe")
    if problems:
        raise SchemaViolation("; ".join(problems), raw=raw)
    return SignalProposal(
        symbol=str(symbol),
        direction=str(raw["direction"]),
        confidence=float(raw["confidence"]),
        rationale=str(raw["rationale"]).strip(),
        max_position_pct=float(raw["max_position_pct"]),
    )


# ---------------------------------------------------------------------------
# Provider wiring
# ---------------------------------------------------------------------------

def make_openai_client(api_key: Optional[str] = None):
    """Construct the real OpenAI SDK client. Import is lazy so unit tests
    never pay for (or need) the dependency."""
    from openai import OpenAI  # openai>=1.40
    return OpenAI(api_key=api_key) if api_key else OpenAI()


class OpenAIClient:
    """Thin wrapper over an OpenAI SDK client with retry-on-violation.

    `client` is any object exposing `client.chat.completions.create(...)`
    with the openai>=1.40 signature — the real SDK client in production,
    a fake in tests.
    """

    def __init__(
        self,
        client: Any,
        *,
        model: str = "gpt-4o-mini-2024-07-18",
        universe: Sequence[str] = ("SPY", "QQQ", "AAPL", "MSFT", "NVDA"),
        max_retries: int = 2,
        temperature: float = 0.2,
        system_prompt: str = (
            "You are a quantitative research assistant for the AlphaForge "
            "trading desk. Propose ONE trading signal as strict JSON matching "
            "the provided schema. Use only tickers from the approved universe "
            "named in the user message. Never invent tickers. If you lack "
            "conviction, propose direction=flat with low confidence."
        ),
    ) -> None:
        self._client = client
        self.model = model
        self.universe = tuple(universe)
        self.max_retries = max_retries
        self.temperature = temperature
        self.system_prompt = system_prompt

    # -- low-level call ----------------------------------------------------
    def _call_model(self, user_content: str) -> str:
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_content},
            ],
            response_format=RESPONSE_FORMAT,
            temperature=self.temperature,
        )
        message = resp.choices[0].message
        refusal = getattr(message, "refusal", None)
        if refusal:
            # A refusal is a provider policy decision, not a format glitch:
            # retrying the identical prompt will not help. Raise immediately
            # with the refusal text preserved for the audit trail.
            raise SchemaViolation(f"Provider refusal: {refusal}",
                                  raw={"refusal": refusal})
        return message.content or ""

    # -- public API --------------------------------------------------------
    def request_signal(self, market_brief: str) -> SignalResult:
        """Ask the model for a signal proposal; retry on schema violation.

        Returns a SignalResult: the validated proposal plus the ordered
        per-call attempts list (caller-owned). Raises SchemaViolation
        after max_retries+1 failed attempts; the exception carries the
        last raw response. A provider refusal raises immediately.
        """
        user_content = (
            f"Approved universe: {', '.join(self.universe)}.\n"
            f"Market brief:\n{market_brief}\n"
            "Respond with exactly one JSON object matching the schema."
        )
        attempts: List[Any] = []
        last_exc: Optional[SchemaViolation] = None
        for _ in range(self.max_retries + 1):
            content = self._call_model(user_content)
            attempts.append(content)
            try:
                raw = json.loads(content)
            except json.JSONDecodeError as exc:
                last_exc = SchemaViolation(
                    f"response is not valid JSON: {exc}", raw=content)
                continue
            try:
                proposal = validate_signal(raw, self.universe)
            except SchemaViolation as exc:
                last_exc = exc
                continue
            return SignalResult(proposal=proposal, attempts=attempts)
        assert last_exc is not None
        raise last_exc


# ---------------------------------------------------------------------------
# Live demo (paper/paper-key only — never real credentials)
# ---------------------------------------------------------------------------

def demo(market_brief: str, api_key: Optional[str] = None) -> None:
    """Run one live proposal against the real provider.

    Requires OPENAI_API_KEY in the environment (or pass api_key). Uses a
    paper-style test brief; no orders, no broker calls.
    """
    client = OpenAIClient(make_openai_client(api_key))
    try:
        result = client.request_signal(market_brief)
    except SchemaViolation as exc:
        print(f"REJECTED after retries: {exc}")
        return
    proposal = result.proposal
    print(f"ACCEPTED: {proposal.symbol} {proposal.direction} "
          f"conf={proposal.confidence:.2f} "
          f"max_pos={proposal.max_position_pct:.1f}%")
    print(f"  rationale: {proposal.rationale}")
    print(f"  attempts logged: {len(result.attempts)}")


if __name__ == "__main__":
    demo("SPY gapped up 0.8% on heavy volume; QQQ flat; NVDA earnings "
         "tomorrow after close. VIX 14.2, drifting lower.")
