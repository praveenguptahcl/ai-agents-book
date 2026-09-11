# Appendix B — Lab Answer Keys

*Read this appendix after attempting the labs, not before. Each key is a
reference implementation — the one the lab's tests were written against —
plus the design reasoning the tests can't check. The keys are genuine:
nothing is hard-coded, and every honesty trap in the labs (the canary,
the FlatLiner, the fabrication detectors) is passed by computation, not
by shortcut.*

## How to run the keys

The labs ship RED — the keys live in `code/app_b/`, never in the lab
directories, so nothing passes out of the box. To check your own work
against a key: Lab 1, copy `code/app_b/lab1_pipeline.py` to
`code/ch20/pipeline.py` and run that lab's tests. Labs 2–4, the keys
import their GIVEN fixtures from the lab test modules themselves
(single source of truth, no duplicated fixtures); splice the key into
the lab directory the way your CI would and run the suite. The repo's
CI runs each lab's tests twice: once as shipped (must be red) and once
with the key (must be green). The harness is `scripts/ci_double_run.py`
(wired into CI at `.github/workflows/lab-double-run.yml`): it copies the
`code/` tree to a temp dir for each run — the shipped labs are never
modified — asserts the RED run fails in exactly the documented way
(Lab 1: collection error for the missing `pipeline` module; Labs 2–3:
every test fails on the `NotImplementedError` stubs; Lab 4: five stub
failures plus the one documented passing trap,
`test_in_sample_sharpe_is_seductive`), then splices the key in and
asserts the GREEN run is fully green (10/10/8/6).

---

## B.1 Lab 1 — The Market-Data Evidence Pipeline

**Key file:** `code/app_b/lab1_pipeline.py` — `QuotePipeline`, `MalformedQuote`,
`UnlabeledData`, `UntrustedSource`. All 10 lab tests green.

### The decision the lab is really about: validation order

The pipeline validates in a fixed order — shape, then provenance, then
source trust, then freshness — and a quote that fails an earlier gate
never reaches a later one. The order is not aesthetic; it determines
which name a failure gets, and the name determines what the operator
does next. A missing price reported as an untrusted source would send
the operator to rotate credentials when the feed simply dropped a
field.

The subtle call is the provenance gate. A missing provenance is *not* a
shape error, even though "provenance" is in the required-field list.
Shape errors say "the feed is broken"; unlabeled-data errors say "the
data's origin is unknown, and it is inadmissible." Those are different
operational situations — one pages the data engineer, the other quarantines
the quote — so they get different gates and different exception types:

```python
    def _validate(self, quote: dict) -> None:
        if not isinstance(quote, dict):
            raise MalformedQuote(f"quote must be a dict, "
                                 f"got {type(quote).__name__}")
        self._check_shape(quote)
        if quote.get("provenance") not in _PROVENANCE_VALUES:
            # Missing, empty, wrong type, or any other value: the data's
            # origin is unknown, so the data is inadmissible. Nothing is
            # emitted, nothing buffered, nothing "fixed up".
            raise UnlabeledData(
                f"quote for {quote.get('symbol')!r} carries no usable "
                f"provenance label (got {quote.get('provenance')!r}); "
                f"unlabeled data is inadmissible")
        if quote["source"] not in self._allowed_sources:
            raise UntrustedSource(
                f"source {quote['source']!r} is not in the allowlist")
```

Note what `_check_shape` deliberately skips: provenance. If the shape
check claimed missing provenance as `MalformedQuote`, the lab's canonical
failure would hide behind the wrong name — and the test pins
`UnlabeledData` for exactly that case.

### Stale is flagged, never dropped

A quote older than the freshness window is still emitted, with
`"stale": True` in the payload. The alternative — silently dropping it —
would hide the outage from the very log the desk reads to notice outages.
"Stale" is information about the feed; dropping it is information about
nothing:

```python
    def ingest(self, quote: dict) -> dict:
        """Validate ONE raw quote and route it into evidence.

        Returns the recorded entry — the acknowledgement. The entry's
        ``seq`` and ``entry_hash`` ARE the receipt: a signal may act on a
        quote only if it can produce this receipt.
        """
        self._validate(quote)
        stale = (self._clock() - quote["ts"]) > self._freshness_seconds
        payload = dict(quote)  # extra fields (currency, as_of) pass through
        payload["tool"] = "get_quote"
        payload["quote_ts"] = quote["ts"]
        payload["stale"] = bool(stale)
        # Ch 9's taxonomy is CLOSED: a market quote arrived because a tool
        # was called, so it is a "tool_call" event with a rich payload —
        # never a new event type.
        return self._router.emit(self._session, "tool_call", payload)
```

Two details worth noticing. First, the event type is `"tool_call"`,
not a new `"market_quote"` type: Ch 9's taxonomy is closed, and new
domains get richer payloads, not new types. Second, the returned entry
*is* the receipt — the audit log's `seq` and `entry_hash`, assigned
atomically at append time. A signal that cannot produce this receipt
for a quote it acted on is the lab's downstream failure mode, and it is
detectable precisely because the receipt is unforgeable.

### Batch ordering and the no-rollback rule

`ingest_batch` sorts by `seq` before ingesting, because the wire
reorders and the evidence must not. When a bad quote appears mid-batch,
the exception propagates — but quotes admitted before it stay admitted.
They were valid; rolling them back would rewrite history to pretend the
batch never partially happened. The ledger never contains a quote that
failed validation, and it always contains the quotes that passed.

### The bool that is not a number

`_is_number` excludes `bool` explicitly, because in Python `True` is an
instance of `int`. A quote with `"price": True` is not a pricing error
the desk can round away — it is a type confusion, and the pipeline
treats it as one. The same guard appears in the `seq` check. These are
the kind of one-line decisions that look paranoid until the first time
a JSON producer serializes a flag into a numeric field, and then they
look like the cheapest insurance in the file. The lab's adversarial
fixtures do not test this case; the key includes it anyway, because an
answer key is allowed to be stricter than the tests it satisfies —
never looser.

### Why the receipt matters more than the row

It is tempting to read `ingest` as "validate, then store." The reference
implementation reads it as "validate, then *witness*." The distinction
is the return value: the recorded entry, with the audit log's
monotonic `seq` and the chained `entry_hash`. Downstream — in Lab 2's
signal pipeline, in the desk's real morning ritual — a signal may act
on a quote only if it can produce this receipt. That turns the evidence
spine from a log the desk *keeps* into a precondition the desk
*enforces*: unlogged data is not merely frowned upon, it is unusable.
The final lab test (`test_evidence_chain_survives_the_lab`) verifies
the HMAC chain over everything the pipeline emitted, which is the
mechanical form of the same idea — the receipt is only as good as the
chain behind it.

---

## B.2 Lab 2 — The Signal Generator Contract

**Key file:** `code/app_b/lab2_signal_pipeline.py` — `SignalPipeline.process`.
All 10 lab tests green.

### The layer split, enforced by rejection names

The pipeline is four stages — parse, schema-check, contract-gate,
dedupe — and the stage that kills a proposal names the rejection. This
is the Ch 4 + Ch 5 composition made mechanical: the provider schema
guarantees shape, the Pydantic contract guarantees judgment, and the
reason code says which one fired. The test that pins the whole lesson
is `test_confidence_out_of_range_dies_at_contract_not_schema`: strict
mode cannot express ranges, so confidence 1.7 *passes* the schema and
must die at the contract. A pipeline that rejected it as
`SCHEMA_VIOLATION` would be green on every other test and wrong about
the architecture.

The schema check is implemented by hand rather than with a validation
library, because the point is to mirror exactly what the provider
guarantees — closed object, required fields, closed enum — and nothing
more:

```python
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
```

The contract gate is the lab's GIVEN `SignalProposal` — the key does
not reimplement it, because the lab is about *composition*, not about
rewriting Ch 4. The one judgment the key adds is dedupe: each
`proposal_id` accepted exactly once, so a retry and a replay are treated
identically. The dedupe is process-local by design; the chapter is
explicit that the production answer is Ch 14's ledger or Ch 4's
idempotency keys, and a lab key that pretended otherwise would be
teaching the wrong scale.

The full stage order, with the closed reason set:

```python
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
```

### Why the key asserts on the reason set

The last lines of `signal_pipeline.py` are not implementation — they
are a tripwire:

```python
assert set(REASON_CODES) == {
    "MALFORMED_JSON", "SCHEMA_VIOLATION",
    "CONTRACT_VIOLATION", "DUPLICATE_ID",
}, "the lab's closed reason set changed; the key must be re-derived"
```

If the lab ever gains a fifth reason code, the key refuses to import
rather than silently drifting. A closed set that grows without the key
knowing is how "the pipeline is wrong, not the set" stops being true.
This is the same instinct as Ch 9's closed taxonomy: the set of names
is a contract, and contracts are checked at the boundary, not trusted
in the middle.

### Parse defensively, reject precisely

The `except (json.JSONDecodeError, ValueError, TypeError)` clause is
wider than the lab's fixture needs — the fixture only ever hands the
pipeline strings. It is there because `process` takes `raw`, and in
production `raw` is whatever the model emitted, including the empty
string, including `None` if the caller is sloppy. `json.loads(None)`
raises `TypeError`, not `JSONDecodeError`; a pipeline that only caught
the latter would crash on the former, and a crash is not a rejection.
Every input to this function leaves as a verdict tuple. That is the
whole contract of the stage, and the key honors it for inputs the tests
never send.

---

## B.3 Lab 3 — Execution Under Fire

**Key file:** `code/app_b/lab3_solution.py` — `wire_desk`, `submit_intent`,
`drive_market`, `close_out`. All 8 lab tests green.

### Three wiring decisions carry the whole lab

**First: the gate is checked before the executor, with the scope.**
`submit_intent` calls `killswitch.check("submit", scope=scope)` *before*
`executor.execute`. The ordering matters twice: a refusal must leave no
phantom ledger row (the ledger records only what the system did, and a
refusal is something the system declined to do), and the scope is what
makes the kill surgical — a global check here would halt the innocent
desk next door:

```python
def submit_intent(ctx: dict, order: dict, scope) -> dict:
    """The desk's single doorway to the market.

    The kill gate is checked WITH the scope before the executor touches
    anything. A refusal names the kill level — a refusal without a reason
    is a different kind of unknown — and leaves no ledger row.
    """
    killswitch = ctx["killswitch"]
    try:
        killswitch.check("submit", scope=scope)
    except HaltedError as exc:
        level = killswitch.level_for(scope).name
        return {"refused": True,
                "reason": f"submit refused by kill gate ({level}): {exc}"}
    return ctx["executor"].execute(order, ctx["wired_broker"])
```

Note the refusal names the kill level explicitly. The `HaltedError`
message already contains it, but the key does not rely on message
formatting — it reads `level_for(scope).name` and puts it in the
reason. A refusal without a named reason is a different kind of
unknown, and this lab grades that.

**Second: the broker is wrapped once, at the boundary.**
`killswitch.guarded(wrap_broker(raw))` is a single expression because
it is a single decision. `wrap_broker` is the anti-corruption layer:
raw `TimeoutError`/`ConnectionError` become `BrokerTimeout`/`BrokerError`,
the only taxonomy the executor's `except` clause understands — without
it, a silent broker arrives at the executor wearing the wrong exception
and gets misclassified. `guarded` re-checks the gate at send time,
closing the TOCTOU window between the early check and the wire call.
Wrapping twice, or wrapping in the wrong order, would either double-gate
or leave the translation off one of the two network paths (submit vs.
lookup) — and the Ch 10 chapter documents exactly the `AttributeError`
that the decorator version of this idea produced.

**Third: the drop is measured from the session's first bar, and an
armed kill is never re-engaged.** `drive_market` tracks
`(first_close - close) / first_close` per bar; at 5% it engages a
*scoped* `PAUSE_INTENTS` with a written reason naming the measured
drop. If the scope already has a kill at `PAUSE_INTENTS` or above, it
measures and returns `{"tripped": False, ...}` — the switch refuses
stacking, loudly, and the caller must not ask:

```python
        if drop >= DROP_THRESHOLD and trip_bar is None:
            if killswitch.level_for(scope) >= KillLevel.PAUSE_INTENTS:
                break  # already armed: measure, don't stack
            operator = ctx["registry"].issue("op-ella")
            killswitch.engage(
                KillLevel.PAUSE_INTENTS,
                [operator],
                f"market drop {drop:.2%} from session open "
                f"({first_close:.2f} -> {bar['close']:.2f}); "
                f"scoped halt for {scope[1]}",
                scope=scope,
            )
            trip_bar = i
            break
```

The written reason is load-bearing: an auditor reading the kill log
later must be able to reconstruct *why* the desk halted without
replaying the market. "Second wave panic" — the reason the test uses
for the refused re-engagement — is an example of what not to write.

### The two-person rule, tested both directions

Tests 7 and 8 are a pair, and the key passes both without special
cases because the discipline lives in the Ch 11 component, not in the
wiring. Test 7 engages a `FULL_STOP` with two admins and shows one
admin cannot lift it — not the engaging admin, not a different one.
Test 8 lifts it with both admins, a written reason, and a fresh
heartbeat, and trading resumes. The key's only contribution is
`killswitch.beat()` in `wire_desk` and the refusal to get clever:
there is no "emergency override" path in the wiring, because an
override path in the wiring would be the very hole the two-person rule
exists to close. The heartbeat detail is worth pausing on. `check`
requires a fresh heartbeat for every submit, checked *after* the kill
level — so a desk whose supervisor died cannot trade even with no kill
armed. The lab's `wire_desk` beats once at construction; in production
that beat comes from the supervisor loop in Ch 14. A student who
forgets the beat gets a desk that refuses everything with
`HeartbeatStale`, which is the correct failure: a silent supervisor is
indistinguishable from a dead one, and both mean "do not trade."

### The honest states

`close_out` runs the reconcile sweep through the wired broker and
reports pending keys plus final states. The sweep is where the lab's
honesty rules bite: a row may be `filled` only if the broker says so
(broker truth wins the reconcile); a row may be `abandoned` only after
the settle window with no broker record, never while the broker is
merely silent. In the silent phase the sweep records a
`reconcile_error` on the row and leaves it `timeout` — the unknown
documented, not resolved. The most expensive sentence in production is
"I don't know what happened" left unsaid; this lab makes the pipeline
say it, on the record, with a timestamp.

---

## B.4 Lab 4 — Walk-Forward Verdict

**Key file:** `code/app_b/lab4_solution.py` — `build_folds`,
`verify_strategy`. All 6 lab tests green.

### The verdict rule is the book's honesty thesis as code

```python
    if all(g == "HOLD" for g in fold_grades):
        verdict = "HOLD"
    elif all(g == "PASS" for g in fold_grades) \
            and dsr_value >= DSR_PASS_THRESHOLD:
        verdict = "PASS"
    else:
        verdict = "FAIL"
```

Read it as the three things the lab will not let you confuse. HOLD is
what a strategy that never traded earns — honest flat, never a zero
dressed up as a result (the FlatLiner's grades are `("HOLD",) * 5`, and
its DSR is reported as 0.0 with the explicit note that the DSR is
*undefined* when there are no trades: a zero dressed up as a statistic
is fabrication). PASS requires *every* fold green *and* the
multiplicity control cleared — the canary's three green folds are not
enough, because the fourth fold said no, even though the DSR cleared the
threshold (0.976 ≥ 0.95). Everything else is
FAIL, including the seductive middle: good folds, bad statistics.

Nothing is hard-coded. The canary's verdict is discovered: the folds
are walked with the real Ch 16 harness (fresh strategy instance per
fold, t+1 execution, the embargo the test demands), the grades come
from the default grader, and the DSR is computed against the GIVEN
25-trial null distribution. On the reference run the canary grades
`("PASS", "PASS", "PASS", "FAIL", "HOLD")` with DSR 0.976 — above the
0.95 bar, so the folds (not multiplicity) deliver the FAIL, matching the
grader's expected verdict by computation. Swap in a genuinely good strategy and the same code
reports PASS; that is what makes it a key rather than a cheat sheet.

### The thesis is written for the judges literally

The two judges are keyword rules standing in for pinned-model calls —
the machinery under test is the agreement statistics and the cost
ledger, not the judges' taste. The thesis must state the true verdict
(using the word "verdict"), cite the fold count ("folds") and the
embargo ("embargo"), and must never claim a PASS the pipeline did not
earn: the no-fabrication judge fails any thesis containing "PASS" when
the true verdict is not PASS. So the thesis carries the verdict and
the evidence, while the grade table lives in `reason` — which the
judges never see:

```python
    thesis = (
        f"Strategy {strategy_factory.__name__}: the walk-forward verdict "
        f"is {verdict} across {n_folds} folds with a {embargo_bars}-bar "
        f"embargo. The deflated Sharpe ratio is {dsr_value:.2f} against "
        f"{N_TRIALS} null trials (annualized Sharpe {sharpe_annual:.2f})."
    )
```

This separation — the human-readable `reason` (which names every fold
grade, including the PASSes) versus the judge-scored `thesis` (which
states only the verdict and the evidence) — is the design decision the
anti-fabrication tests are really grading. A pipeline that pasted the
grade table into the thesis would trip the no-fabrication judge on the
canary; a pipeline that omitted the verdict word would fail
verdict-correctness. On the reference run both judges pass all three
rubric cases (κ = 1.0), and the cost ledger reads
(3 × $0.02 + 3 × $0.02) / 5 = $0.024 per verified signal — inside the
$1.00 budget, because verification that nobody can afford to run is
verification that nobody runs.

### What the pipeline refuses to do

Two refusals are part of the key, not just the tests. A zero embargo
raises `EmbargoViolation` from `build_folds` — the key does not catch
it, because an embargo of zero is information leakage with a permission
slip, and the fold builder must refuse loudly rather than round up. A
mixed-provenance dataset raises `DataViolation` from the walk-forward
harness — the key lets it propagate, because a pipeline that swallowed
it would be laundering the labels the whole book depends on.

### Why DSR 0.0 for the FlatLiner is not a lie

The key reports `dsr=0.0` when the strategy made no trades, and the
comment in the code insists this is not a statistic — it is a marker
for "undefined." This deserves emphasis because it is the easiest place
in the whole lab to fabricate without noticing. The DSR formula needs a
return series; with no trades there is no series, and any number the
pipeline emitted would be a choice disguised as a measurement. Reporting
0.0 *and* routing the verdict to HOLD via the all-HOLD rule keeps the
two honest: the number says "nothing to deflate," the verdict says
"nothing traded." A reader tempted to "improve" the key by returning
`None` for the DSR should notice the `VerdictReport` is frozen with
`dsr: float` — the schema itself refuses the honest null, so the key
documents the convention instead. Schemas that cannot express "not
applicable" are a recurring theme in this book; the answer is always
the same: document the convention at the boundary, never smuggle a
meaning into the value.

### The cost ledger as a design constraint

The $0.024-per-verified-signal figure is not trivia — it is the Ch 15
lesson (cost-per-verified-success) closing the loop on the Ch 17
machinery. The key scores 3 rubric cases × 2 judges at $0.02 per call
and divides by the 5 folds, because the cost that matters is per
*verified signal*, not per judge call. A verification pipeline whose
cost the desk will not fund is a pipeline the desk will not run, and a
pipeline nobody runs verifies nothing. The budget check
(`cost_per_verified_signal <= JUDGE_BUDGET`) is in the test, but the
design decision — metering the judges, dividing by folds, keeping the
thesis to one paragraph so the stub judges' keyword rules stay
deterministic — is in the key. When the judges become real pinned-model
calls (Ch 5 strict schema, Ch 14 gateway accounting), the same ledger
holds; only the per-call price changes.
