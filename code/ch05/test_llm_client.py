"""Failure drills for Ch 5: provider integration & strict schemas.

A FakeCompletions object mirrors the openai>=1.40 call shape
(client.chat.completions.create -> response.choices[0].message.content)
with a scripted queue of responses. No network, no API key, no SDK
needed: the drills prove schema enforcement and retry behavior are
properties of OUR client, not of the provider.
"""

import json

import pytest

from llm_client import (
    SIGNAL_SCHEMA,
    OpenAIClient,
    SchemaViolation,
    SignalProposal,
    SignalResult,
    validate_signal,
)


# ---------------------------------------------------------------------------
# Fake SDK surface
# ---------------------------------------------------------------------------

class _FakeMessage:
    def __init__(self, content, refusal=None):
        self.content = content
        self.refusal = refusal


class _FakeChoice:
    def __init__(self, message):
        self.message = message


class _FakeResponse:
    def __init__(self, content):
        message = (content if isinstance(content, _FakeMessage)
                   else _FakeMessage(content))
        self.choices = [_FakeChoice(message)]


class _FakeCompletions:
    def __init__(self, script):
        self.script = list(script)   # queue of raw content strings / _FakeMessage
        self.calls = []              # recorded kwargs, for assertions

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.script:
            raise AssertionError("fake model ran out of scripted responses")
        return _FakeResponse(self.script.pop(0))


class _FakeChat:
    def __init__(self, script):
        self.completions = _FakeCompletions(script)


class FakeClient:
    """Drop-in for the OpenAI SDK client: fake.chat.completions.create."""
    def __init__(self, script):
        self.chat = _FakeChat(script)


GOOD = json.dumps({
    "symbol": "SPY",
    "direction": "long",
    "confidence": 0.72,
    "rationale": "Breakout above 20-day high on 2.1x relative volume.",
    "max_position_pct": 5.0,
})


def make_client(script, **kw):
    return OpenAIClient(FakeClient(script), universe=("SPY", "QQQ"), **kw)


def _schema_keys(schema):
    """Every key appearing anywhere in a JSON-schema dict, recursively."""
    keys = set()

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                keys.add(k)
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(schema)
    return keys


# ---------------------------------------------------------------------------
# Drills
# ---------------------------------------------------------------------------

def test_schema_uses_strict_subset_only():
    """OpenAI strict:true rejects minimum/maximum/minLength with a 400 on
    the wire. The schema must not contain them; ranges live in
    _check_bounds, the local golden reference."""
    forbidden = {"minimum", "maximum", "minLength"}
    assert not (forbidden & _schema_keys(SIGNAL_SCHEMA))


def test_valid_response_accepted_first_try():
    client = make_client([GOOD])
    result = client.request_signal("SPY strong.")
    assert isinstance(result, SignalResult)
    p = result.proposal
    assert isinstance(p, SignalProposal)
    assert (p.symbol, p.direction) == ("SPY", "long")
    assert p.confidence == pytest.approx(0.72)
    assert len(result.attempts) == 1
    # the wire call used the real SDK parameter shape
    kwargs = client._client.chat.completions.calls[0]
    assert kwargs["model"] == "gpt-4o-mini-2024-07-18"
    assert kwargs["response_format"]["type"] == "json_schema"
    assert kwargs["response_format"]["json_schema"]["strict"] is True


def test_default_model_is_pinned():
    """The default must be the pinned version, never the floating alias."""
    client = make_client([GOOD])
    assert client.model == "gpt-4o-mini-2024-07-18"
    client.request_signal("brief")
    kwargs = client._client.chat.completions.calls[0]
    assert kwargs["model"] == "gpt-4o-mini-2024-07-18"


def test_malformed_json_triggers_retry_then_succeeds():
    client = make_client(["{not json at all", GOOD], max_retries=2)
    result = client.request_signal("brief")
    assert result.proposal.symbol == "SPY"
    assert len(result.attempts) == 2  # failure recorded, then success


def test_fail_plausible_ticker_rejected():
    """The model invents 'AMZN' — plausible, real ticker, NOT in universe.
    Schema-valid, confidence-valid, completely unauthorized. Must die here."""
    invented = json.dumps({
        "symbol": "AMZN",            # not in ("SPY", "QQQ")
        "direction": "long",
        "confidence": 0.91,
        "rationale": "AWS reacceleration narrative into earnings.",
        "max_position_pct": 10.0,
    })
    with pytest.raises(SchemaViolation) as ei:
        make_client([invented] * 3, max_retries=2).request_signal("brief")
    assert "not in approved universe" in str(ei.value)


def test_persistent_violation_exhausts_retries_and_raises():
    bad = json.dumps({"symbol": "SPY", "direction": "sideways"})  # bad enum, missing fields
    with pytest.raises(SchemaViolation):
        make_client([bad] * 4, max_retries=2).request_signal("brief")


def test_audit_trail_is_per_call_and_caller_owned():
    """Two calls on the same client must not accumulate state on the
    client: each SignalResult carries its own attempts list."""
    client = make_client([GOOD, GOOD])
    r1 = client.request_signal("a")
    r2 = client.request_signal("b")
    assert len(r1.attempts) == 1 and len(r2.attempts) == 1
    assert not hasattr(client, "last_attempts")  # no client-side accumulation


def test_provider_refusal_raises_schema_violation():
    """A provider refusal (message.refusal set, content None) is a policy
    decision, not a format glitch: it must raise immediately, not retry."""
    refused = _FakeMessage(content=None, refusal="I can't help with that.")
    client = make_client([refused])
    with pytest.raises(SchemaViolation) as ei:
        client.request_signal("brief")
    assert "refusal" in str(ei.value).lower()
    assert ei.value.raw == {"refusal": "I can't help with that."}
    # no retry was attempted: exactly one wire call
    assert len(client._client.chat.completions.calls) == 1


def test_out_of_range_confidence_rejected():
    raw = {"symbol": "SPY", "direction": "flat", "confidence": 1.4,
           "rationale": "x", "max_position_pct": 5.0}
    with pytest.raises(SchemaViolation) as ei:
        validate_signal(raw, ("SPY",))
    assert "confidence" in str(ei.value)


def test_non_string_symbol_rejected():
    raw = {"symbol": 123, "direction": "long", "confidence": 0.5,
           "rationale": "x", "max_position_pct": 5.0}
    with pytest.raises(SchemaViolation) as ei:
        validate_signal(raw, ("SPY",))
    assert "symbol" in str(ei.value)


def test_non_object_response_rejected():
    with pytest.raises(SchemaViolation):
        validate_signal([1, 2, 3], ("SPY",))
