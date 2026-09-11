# Chapter 5 — Provider Integration & Strict Schemas

**Thesis thread:** Authority is granted, never assumed. That principle dies
the moment your system trusts whatever text the model happened to emit. This
chapter wires the AlphaForge research agent to a real provider with a
mechanical, auditable contract on the wire: the model proposes, a strict
schema constrains, and your code — not the model — decides what counts as a
valid proposal. It also corrects a defect in the previous edition, which
printed a hallucinated SDK method (`client.responses.create`). That method
did not exist when the previous edition was written — the Responses API
only became real in 2025, so the old chapter's "live" listing would have
crashed on first run. (It exists today, which is why the correction is
load-bearing rather than archaeology: this chapter uses the Chat
Completions structured-outputs interface — `chat.completions.create`
with `response_format={"type": "json_schema", "strict": True}` —
verified against the installed SDK satisfying `openai>=1.40`.)

---

## 5.1 The proposal pattern

Every agent in this book follows one rule at the provider boundary: **the
model emits proposals, never commands.** A proposal is data that requests
authority. An order is authority exercised. Chapters 6 through 9 will build
the gates — allowlists, position limits, paper-broker execution, human
approval — that turn a proposal into action. But none of those gates work if
the proposal itself arrives as freeform text that your code parses with hope.

The failure mode has a name in the literature: **fail-plausible**. The model
returns something that looks right, parses cleanly, and is wrong in a way
that only domain knowledge would catch. In our quant world the canonical
example is a fabricated ticker: the model proposes `AMZN long, confidence
0.91`, with a crisp rationale about AWS reacceleration. It parses. It reads
like a professional desk note. And `AMZN` was never in the approved trading
universe — the strategy mandate covers five names, and the model just
invented a sixth. If downstream code trusts the string, a position gets
sized against a ticker the risk framework never approved. Fail-plausible is
the silent killer because every layer above the parser *agrees* the output
looks fine.

The defense is a strict schema, enforced twice: once by the provider's
structured-output machinery, once by your own validation code. The
provider-side schema guarantees shape (fields, types, enums). It cannot
express ranges or lengths — OpenAI's strict mode rejects those keywords
outright — so your validation also owns every numeric bound. Your
validation adds everything the provider cannot express or know: the
confidence and size ranges, the universe allowlist, the position caps.
Neither layer trusts the other; both must pass.

## 5.2 The real SDK call

No shims, no wrappers that hide the wire. The exact call, for
`openai>=1.40`:

```python
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
```

Three details matter. First, `response_format` with `"type":
"json_schema"` is the structured-outputs interface; `"strict": True` tells
the provider to refuse any response that does not match the schema exactly —
no extra keys, no missing keys, no wrong types. Second, the schema itself
must be written for strict mode: every object sets `"additionalProperties":
false`, every property is listed in `"required"`, enums are closed. Third,
the system prompt still carries the behavioral instruction ("never invent
tickers") because strict mode guarantees *shape*, not *honesty* — the
allowlist check in our code is what catches the invented ticker.

Note what we do not do: we never call `client.responses.create`. That
method did not exist when the previous edition was written — the
Responses API arrived in 2025 — so the old chapter's "live" listing
would have crashed on first run. (It is a real method today; this
chapter stays on the Chat Completions interface deliberately, because
it is the stable, long-supported structured-outputs path and the one
this chapter's verification covers.) This is exactly the class of
defect this book's verification bar exists to prevent: every listing in
this edition is executed in CI, and the SDK surface it depends on is
checked against the installed package.

A fourth detail, operational rather than contractual: the first request
carrying a novel strict schema pays a compilation penalty — the provider
builds the constrained grammar before it samples a single token. On a
latency budget that penalty lands exactly where it hurts most, the first
real proposal of the session. The fix is boring: send one throwaway prompt
at startup (a `warmup()` call, or a dummy request in your init path) so
the grammar is compiled before it matters. Warm-up buys speed, not
correctness — an agent that times out on its first call never gets to be
correct — but do not confuse the two.

## 5.3 The SignalProposal contract

The schema is the contract between the research agent and everything
downstream. Keep it small — five fields — and notice what it does *not*
say: no ranges, no lengths. OpenAI's strict subset rejects `minimum`,
`maximum`, and `minLength` with a 400 on the wire, so those bounds are
documented in descriptions and enforced in `_check_bounds` (§5.4), not in
the schema.

```python
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
```

Read the schema as an authority statement: the model's authority extends to
proposing a direction, a confidence, a rationale, and a *recommended* size
cap. The word "recommended" is load-bearing. `max_position_pct` is the
proposer's suggestion; the position sizer in Chapter 8 will apply the desk's
hard caps and take the minimum. A schema field named `max_position_pct`
looks like a decision. It is a suggestion with a ceiling. Name your fields so
the authority boundary is visible in the JSON itself.

Two deliberate design choices. `direction` includes `"flat"` as a
first-class value, and the system prompt tells the model to prefer it when
conviction is low. Models that must output long-or-short will manufacture
conviction; a model allowed to say "flat" tells you the truth more often.
And `rationale` carries no `minLength` — strict mode forbids the keyword,
so `_check_bounds` rejects empty strings locally. This is the chapter's
thesis in miniature: the provider envelope guarantees keys and types,
never ranges or lengths; the local check is the golden reference, and
anything the envelope cannot express lives there.

## 5.4 Validation your code owns

Provider-side strict mode catches malformed JSON, missing fields, wrong
types, and bad enums. It cannot catch a well-formed lie — and it cannot
even express an out-of-range number or an empty string, so those are ours
too. Our `validate_signal` adds the domain gates and the numeric bounds:

```python
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
```

The universe allowlist is the fail-plausible gate. `AMZN` passes the
provider schema, passes the enum check, passes the confidence range — and
dies here, with a message that names the violation, before it can become a
position. Every rejection carries the raw response (`raw=...`) so the audit
trail in Chapter 10 can show exactly what the model said and exactly why it
was refused. A rejection without evidence is an argument; a rejection with
the raw payload is a fact.

This is also where the "LLM proposes, system disposes" doctrine becomes
mechanical rather than rhetorical. The model does not decide what a valid
signal is. The schema and the allowlist decide. The model merely submits
candidates.

## 5.5 Retry on violation, then stop

Models violate schemas. Sometimes the JSON is truncated, sometimes a field
drifts out of range, sometimes the model "helpfully" adds commentary around
the JSON. The correct response is a bounded retry loop — bounded being the
operative word:

```python
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
```

Why retry at all? Because transient format failures are common and cheap to
absorb, and each retry re-sends the same contract. Why bound it? Because an
unbounded loop is a denial-of-wallet attack against your own API budget, and
because a model that fails the schema three times in a row is telling you
something about the prompt, not the dice. After `max_retries`, we raise
`SchemaViolation` carrying the last raw response — the caller logs it, the
desk sees it, and the failure becomes a prompt-engineering task, not a
silent skip. Notice the loop never *relaxes* the schema to get an answer.
Relaxing the contract to accommodate the model is authority flowing the
wrong direction.

One failure is not retried: a provider refusal (`message.refusal` set,
content empty). A refusal is a policy decision, not a format glitch —
retrying the identical prompt burns budget to hear "no" again.
`_call_model` checks for refusal before parsing and raises
`SchemaViolation` immediately, with the refusal text preserved on `.raw`
for the audit trail.

## 5.6 The proposal is evidence

Every proposal — accepted or rejected — is evidence, and evidence is a
first-class output of this chapter, not a debugging afterthought. Look at
what `request_signal` returns: a `SignalResult` carrying the validated
proposal plus `attempts` — the ordered list of every raw response the
model produced, including the malformed ones. The caller owns that list's
lifecycle: log it, mine it, or drop it. The client keeps no per-call
state, so a long-running daemon cannot leak memory through its own audit
trail. The
`SchemaViolation` exception carries the offending payload on `.raw`. The
`SignalProposal` dataclass is frozen and printable. Together they form a
complete record of the Intent → Authority → Capability → Action chain at its
first link: what was asked, what the model proposed, what the contract
allowed, and what was refused with reasons.

This is what the audit trail in Chapter 10 will consume. When a desk
supervisor asks "why did the agent go flat on QQQ at 10:14?", the answer is
not "the model felt cautious." The answer is the stored proposal: direction
flat, confidence 0.31, rationale logged, schema verdict clean, downstream
gates applied. And when the model invents `AMZN`, the answer is the stored
rejection: schema-valid, universe-violated, killed at the allowlist on
attempt 2 of 3, raw payload preserved. Accountability requires evidence;
this chapter produces it as a side effect of doing the job correctly.

One more consequence: the attempts list on every `SignalResult` is the
cheapest evaluation dataset you will ever own. Every retry is a labeled example of a model
failure mode — truncated JSON, drifted enum, invented ticker. Chapter 12's
eval harness will mine exactly this log to build regression fixtures. Store
it from day one, in a format a human can read, and your future eval work
starts with real data instead of synthetic guesses.

## 5.7 A note on temperature and determinism

We set `temperature=0.2`, not `0`. Full zero-temperature sampling is the
intuitive choice for "deterministic output," but it buys less than it
promises: provider-side sampling at temperature 0 is still not guaranteed
bit-identical across calls, and it can degrade output quality on some
models by collapsing the token distribution too aggressively. What 0.2 buys
is *format stability* — enough randomness to avoid degenerate repetition,
little enough that the JSON envelope lands cleanly on the first attempt
most of the time. Determinism of the *decision* is not the goal here; the
decision isn't made here. The goal is a stable envelope around a stochastic
proposal, and the retry loop absorbs the residual variance. If you need
reproducible research results, pin the model version — the client default
is already the pinned `gpt-4o-mini-2024-07-18`, not the floating alias —
and log it with the proposal — a model alias that
silently upgrades under you is a silent change to your research process.

## 5.8 Failure drill: the fabricated ticker

The full drill lives in `test_llm_client.py` and runs with no network, no
key, no SDK — a fake client mirrors the SDK's call shape
(`fake.chat.completions.create(...)` → `.choices[0].message.content`) with a
scripted response queue. This is deliberate: schema enforcement is a
property of *our* code, so it must be provable without the provider.

The centerpiece test scripts the exact fail-plausible attack:

```python
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
```

Read it as a specification of the threat: schema-valid, confidence-valid,
rationale-plausible, ticker unauthorized. The test asserts the proposal dies
at the allowlist with a named reason, and that three consecutive violations
exhaust the retry budget rather than sneaking one through. Companion tests
cover malformed JSON (retry, then succeed), persistent violations (raise
after budget exhausted), out-of-range confidence, non-object payloads,
non-string symbols, provider refusals, the strict-subset schema audit,
per-call audit-trail ownership, and the pinned default model. Eleven
tests, all green, zero external dependencies — run them:

```
$ python3 -m pytest code/ch05/ -q
11 passed in 0.12s
```

## 5.9 The brief is part of the contract

The system prompt and the market brief are the weakest layer of this
chapter, and they deserve honest labeling. The schema is enforced by
machinery; the allowlist is enforced by code; the system prompt is enforced
by *nothing* — it is a request written in English to a system that
occasionally ignores English. "Never invent tickers" is in the system
prompt, and the model invents tickers anyway often enough that we built an
allowlist to catch it. That is the correct architecture: treat prompt
instructions as policy declarations, and build the enforcement somewhere
the model cannot reach. If a rule matters, it must be checkable in code. If
it is only in the prompt, it is a wish.

The market brief — the user message — deserves the same discipline. In the
AlphaForge pipeline, the brief is assembled from market data: recent bars,
volume, volatility regime. Every number in that brief carries provenance.
The standing rule for this entire book: real bars are stamped REAL,
synthetic fills are stamped SYNTHETIC, and the brief must say which is
which. A model that cannot distinguish backtest bars from live paper bars
will happily "discover" edge in simulated data and propose it with 0.91
confidence. The brief format we use in production prefixes each data block
with its source tag — `[REAL: Alpaca paper bars, 2026-09-10]` or
`[SYNTHETIC: fill simulator]` — so the provenance survives into the audit
trail and the model at least sees the distinction. Prompt-level labeling
does not make the model honest, but it makes the *humans reading the audit
trail* honest about what the model was shown. Garbage in, gospel out is the
failure mode; labeled garbage in, labeled output is the mitigation.

One more brief-construction rule: the brief names the approved universe
explicitly, every call, even though the client already knows it. Redundancy
here is intentional. The schema cannot express "this string must come from
that list," so the universe appears in three places — the system prompt, the
user brief, and the code allowlist — and only the third one enforces. The
first two exist to reduce violations, not to define validity.

## 5.10 What the provider cannot do for you

Structured outputs are a contract on *syntax*. They do not verify
semantics, and three gaps remain yours to close.

**Confidence is a style choice, not a measurement.** The schema enforces
that confidence is a number between 0 and 1. It cannot enforce that the
number *means* anything. A model that outputs 0.91 is performing
confidence, in the theatrical sense — large language models are not
calibrated by default, and their self-reported certainty correlates weakly
with actual correctness. This is the subtlest fail-plausible risk in the
chapter: unlike an invented ticker, a miscalibrated confidence passes every
gate we built, because no gate can see inside the number. The interim rule
is blunt: until Chapter 12's calibration harness maps reported confidence
to observed hit rates on your own data, reported confidence must not move
position size. Log it, display it, plot it — but size positions from
backtested edge and hard caps, never from the model's self-assessment.
Exercise 2 at the end of this chapter is the first step of that
calibration work, and it is not optional reading.

**Rationale is documentation, not input.** The rationale field is unchecked
prose — it can be fluent nonsense, and nothing in this chapter detects
that. Treat it as documentation for humans, never as input to logic. No
downstream code should parse the rationale for keywords, sentiment, or
"conviction." The moment a parser reads the rationale, you have rebuilt the
freeform-text problem this chapter eliminated.

**Strict mode has no memory.** The guarantee is per-call: the model can
propose `long` on call one and `short` on call two for the same brief, and
both pass validation. Consistency across calls is a strategy problem
(Chapter 11), not a schema problem.

The honest summary: this chapter builds a trustworthy *envelope*. The letter
inside is still written by a stochastic parrot with excellent penmanship.
The envelope is what lets every later chapter — backtests, paper execution,
human approval — reason about proposals as data instead of deciphering them
as text. That is the whole job of the provider boundary, and it is enough.

One boundary to name explicitly: nothing in this chapter touches a broker.
Live paper execution arrives in Chapter 10 (the action plane) and the Labs;
Chapter 6 stays a simulated testbench for the provider boundary — the wire
ends at the proposal.

---

**What this fixes:** the previous edition's hallucinated `client.responses.create` (written before the Responses API existed) is replaced with the real `openai>=1.40` Chat Completions structured-outputs call, and every model response now passes a strict schema plus a universe allowlist before it can influence anything.

**Exercises:**

1. **Break the envelope.** Add a sixth field, `stop_loss_pct`, to `SIGNAL_SCHEMA` (required; express the 0–100 bound in `_check_bounds`, since strict mode cannot). Then write a test where the model omits it: confirm the provider-side shape (strict mode) would reject it, and confirm your local `_check_bounds` rejects it too. Which layer catches a `stop_loss_pct` of `-5` — and why can the other one not?
2. **Calibrate or distrust.** Log 50 live `confidence` values from `request_signal` against a paper backtest's realized outcomes for the same briefs. Plot reported confidence vs. observed win rate. Write two sentences on whether the model's confidence deserves to influence position sizing — and what Chapter 12 must do about your answer.
