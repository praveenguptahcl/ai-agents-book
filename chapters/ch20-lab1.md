# Lab 1: The Market-Data Evidence Pipeline

*Part VII: Practice. Chapter 20.*

Every trading desk has a morning ritual, and it is never about the
trading. Long before the first signal fires, before any model proposes
anything, the desk's data pipeline wakes up: it fetches the overnight
quotes, checks they are what they claim to be, stamps them with where
they came from, and files them where every downstream system can find
them. The pipeline is boring. The pipeline is the most important code
the desk owns.

Here is why. A signal is a function of its inputs. If the inputs are
wrong — stale, mislabeled, forged, or simply *of unknown origin* — then
every downstream guarantee in this book is void. The tool contract in
Chapter 4 validated the shape of the proposal. The tenant session in
Chapter 6 proved who was asking. The evidence spine in Chapter 9
recorded what happened. None of it means anything if the *quote itself*
arrived without provenance. A signal that traded on data of unknown
origin is not a disciplined agent with a data problem. It is a rumor
with a brokerage account.

This lab builds the desk's morning pipeline: the wiring between the
market-data server (Chapter 7's MCP transport) and the evidence spine
(Chapter 9's router). Fetch → validate → label → route → acknowledge.
Five verbs. The lab's thesis fits in one sentence: **no quote enters
the evidence without a provenance label, and no signal may act on a
quote it cannot produce a receipt for.**

## The lab is red — that is the point

Run it before you read further:

```
$ python -m pytest test_lab1_data.py -q
ERROR collecting test_lab1_data.py
E   ModuleNotFoundError: No module named 'pipeline'
```

One error, at collection, zero tests run. The harness imports — the
real Ch 7 server, the real Ch 9 router, a verified Ch 6 session — all
resolve. The only missing piece is `pipeline.py`: the module *you*
write. That absence is the lab's starting condition, and it is
deliberate. In test-driven development, red is not failure; red is the
specification of what "done" looks like, written before a line of
solution exists. Your job is to turn this file green without modifying
it. (The one passing implementation lives in Appendix B. It is not
here, and peeking before your pipeline is green is cheating only
yourself — the exam is the understanding, and there is no partial
credit for a copied answer you cannot explain.)

## What the lab proves

Chapters 7 and 9 each proved their own machinery in isolation. The
server proved it can serve quotes over the MCP wire with contract
validation at both ends. The router proved it can chain evidence with
an HMAC key and fail closed on unknown event types. But a production
desk does not run chapters in isolation. The composition is the
system: the quote must travel from the wire *into* the evidence, and
every property the two chapters guaranteed separately must survive the
journey. That is what you are proving — that the composition holds,
with tests that attack it.

## What is given

The harness in `test_lab1_data.py` is complete and honest. Read it;
it is short, and it is the only documentation you get:

- **`quote_server`** — a real `MCPServer` from Chapter 7, the
  AlphaForge market-data tool server, driven in-process through
  JSON-RPC envelopes. It serves deterministic SYNTHETIC quotes for the
  approved universe. It is not a market feed; it is a paper-broker
  fixture, and every quote it emits says so.
- **`fetch`** — `fetch(symbol) -> dict`. One `get_quote` tool call
  through the MCP wire, parsed into a dict. The harness stamps the
  wire source (`alphaforge-market-data`), a timestamp, and a sequence
  number onto each fetched quote. Note the asymmetry: the *real* wire
  always arrives labeled. The hostile cases — unlabeled, untrusted,
  stale, scrambled — arrive only as adversarial fixtures, built by
  hand. In production, the attacker's quotes do not come down your
  wire; they come from everywhere else. Your pipeline must treat every
  quote as potentially hostile regardless of where you got it.
- **`router`** — a real `EvidenceRouter` from Chapter 9, with a fresh
  HMAC secret. Everything your pipeline emits lands in its audit log,
  chained and tenant-scoped.
- **`session`** — a verified `TenantSession` from Chapter 6 for tenant
  `"desk-alpha"`, issued by a real `TenantStore` and re-verified from
  the token bytes. Not a string. The router would reject a string, and
  so should your mental model: the tenant on every entry comes from
  the proof, not from the caller's word.

## The five verbs, and what breaks at each

The pipeline's shape is five verbs — fetch, validate, label, route,
acknowledge — and each verb exists because a specific failure lives
there. Walk them in order, with the failure each one owns:

**Fetch** owns the wire. The MCP call can fail: the server can return
an error envelope, the content can be missing, the JSON can be corrupt.
Your pipeline's fetch path must surface those as failures, not as
empty quotes — an empty dict flowing into validation would be rejected
as malformed, which is correct but confusing; a wire failure should
read as a wire failure. (In this lab the harness's `fetch` is given
and trustworthy. In production, fetch is where retries, timeouts, and
circuit breakers live — Chapters 10 and 14. The lab isolates the
pipeline by handing you a working fetch; do not mistake the isolation
for the architecture.)

**Validate** owns the four refusals, and it is the only verb allowed
to say no. Everything downstream of validation is entitled to assume
validity — that is the whole point of a gate. If validation is
permissive ("we'll fix the label later"), every downstream system must
re-validate, and you have not built a pipeline; you have built five
systems that happen to share a name.

**Label** owns provenance as a first-class field. Notice that the lab
does not ask you to *discover* provenance — the quote arrives with it
(or it does not, and validation refuses). Labeling is not detective
work; it is transcription under oath. The pipeline copies the
provenance claim into the evidence payload exactly as received. If the
claim is later proven false, the evidence shows what was claimed and
when — which is precisely what the auditor needs. A pipeline that
"improves" labels is a pipeline that destroys evidence.

**Route** owns the closed taxonomy. The quote becomes a `tool_call`
event in the evidence spine — not because market data is a tool in any
deep sense, but because the taxonomy is closed and the arrival *was* a
tool call. Routing is also where the tenant binding happens: the
session you were given proves you are the desk, and the entry is
recorded under that tenant. Reads are tenant-scoped (Chapter 9), so
the desk's morning quotes are invisible to every other tenant —
absence, not an error.

**Acknowledge** owns the receipt. The router's `emit` returns the
entry — `seq`, `entry_hash`, the payload as recorded — and that
return value is the acknowledgement. There is no second receipt
object, no separate "success" boolean. One record, one receipt, no
disagreement possible between them. When the signal later asks "may I
act on this quote?", the answer is not a policy lookup. It is: "show
me the receipt." No receipt, no trade. That rule, enforced
everywhere, is what turns evidence from a nice-to-have into the
mechanism by which the desk refuses to act on unproven data.

## The contract

Your `QuotePipeline` has five verbs and nine clauses. The verbs are
the pipeline's shape — **fetch → validate → label → route →
acknowledge** — and the clauses, pinned by the tests, are its law:

1. **Construct** it with the fetch callable, the router, the session,
   the set of trusted sources, a freshness window (default 60
   seconds), and an injectable clock. The clock is injectable so the
   staleness test does not sleep; time is a dependency like any other.
2. **`ingest(quote)`** validates one raw quote dict and routes it.
   It returns the recorded entry — the acknowledgement. The entry's
   `seq` and `entry_hash` are the receipt. A signal may act on a quote
   only if it can produce this receipt.
3. **`ingest_batch(quotes)`** emits in `seq` order, not arrival order.
   The wire reorders packets; the evidence must not reorder history.
   Sort by sequence, then emit.
4. **Shape first.** A quote is valid only if it carries `symbol`,
   `price`, `provenance`, `source`, `ts`, and `seq`, correctly typed.
   Anything else is `MalformedQuote`, and nothing is emitted. Shape is
   not a judgment call; it is the cheapest check and it runs first.
5. **Provenance is mandatory.** It must be exactly `"REAL"` or
   `"SYNTHETIC"` — missing, empty, or anything else raises
   `UnlabeledData`. Unlabeled data is **inadmissible**: never emitted,
   never buffered, never "fixed up". This is the lab's canonical
   failure, and it deserves its own paragraph — see below.
6. **Sources are allowlisted.** A quote from a source outside
   `allowed_sources` raises `UntrustedSource`. The pipeline does not
   negotiate with sources it was not told to trust. Note what this
   implies: adding a new feed is a configuration change to the allow
   list, reviewed and versioned like any other change to system
   intent (Chapter 3) — not something the agent decides at runtime.
7. **Stale is flagged, not dropped.** A quote older than the freshness
   window is still evidence — it is evidence *that the feed went
   quiet* — so it is emitted with `"stale": True` in the payload.
   Silently dropping it would hide the outage, and hidden outages are
   how desks discover at 9:35 that they have been trading on 9:15
   prices. Flagging preserves the information while marking it
   unfit for decisions.
8. **The event type is `tool_call`.** Chapter 9's taxonomy is closed:
   new domains do not get new event types; they get richer payloads.
   A market quote arrived *because a tool was called*, so `tool_call`
   it is. If your pipeline emits any other type, the test fails — and
   in production, the router would flag it as misconfiguration. Learn
   the taxonomy instead of extending it.
9. **The payload is the record.** It carries at minimum
   `tool="get_quote"`, `symbol`, `price`, `provenance`, `source`,
   `seq`, `quote_ts`, and `stale`. Extra fields pass through
   untouched — the pipeline validates, it does not editorialize.

### The canonical failure

Clause 5 is the heart of the lab, so let it land. `test_unlabeled_quote_rejected` deletes the provenance label from a
perfectly good quote and asserts two things: the pipeline raises
`UnlabeledData`, and the audit log is *empty*. Not "emitted with a
warning". Empty. And `test_mixed_batch_admits_only_the_valid` goes
further: in a batch of two, the good quote lands and the unlabeled
one leaves no trace — then it asserts that every entry in the log
carries a valid provenance. That final assertion is the guarantee the
whole desk relies on: **a downstream signal reading this log can
trust that every quote in it survived validation**, because the only
way in was through your pipeline, and your pipeline refuses the
unlabeled.

Why is this the canonical failure rather than, say, the malformed
quote? Because malformation is an accident and mislabeling is a
*lie* — or worse, an unknown. A missing price is obviously broken;
a missing provenance looks fine and means nothing. The most
dangerous data in a pipeline is the data that parses cleanly and
proves nothing. Every system in this book downstream of this lab —
the signal generator in Lab 2, the executor in Lab 3, the
walk-forward in Lab 4 — inherits this guarantee. If you let one
unlabeled quote through here, you have voided every warranty the
rest of the book offers.

## Why the harness is built this way

Three design decisions in `test_lab1_data.py` are worth understanding,
because each one is a lesson the book has been teaching:

**Real machinery, not mocks.** The harness imports the actual Ch 7
server, the actual Ch 9 router, and the actual Ch 6 session store. A
mock server would let your pipeline pass against a fiction — and this
lab exists to prove a *composition*, which a mock cannot witness. The
cost is that your pipeline must satisfy the real contracts: the real
JSON-RPC envelope shape, the real closed taxonomy, the real session
verification. That cost is the lesson. In production, the composition
is the system, and testing the pieces against doubles proves only that
the doubles agree with you.

**The adversarial fixtures are hand-built, not fetched.** The real
wire always arrives labeled — Ch 7's server guarantees it. So the
hostile quotes (unlabeled, untrusted, stale, scrambled) are
constructed as dicts, standing in for every source that is *not* your
wire: a compromised feed, a misconfigured proxy, a replayed capture.
Your pipeline must not distinguish "quotes from fetch" from "quotes
from fixtures" — it validates everything identically, because in
production the pipeline cannot tell which quotes came down the honest
wire either. Uniform suspicion is the design.

**Time is injected.** The pipeline takes a `clock`, and the stale
test drives it — no `sleep`, no flakiness. This is Chapter 15's
discipline arriving early: a test that depends on wall-clock timing
is a test that fails at 2am on the CI runner and passes on your
laptop, and a lab about evidence integrity cannot afford a test suite
that lies about its own results.

## Hints, not the answer

- Start with the refusal paths. Write the three exception classes
  first, then the validation order: shape → provenance → source →
  freshness. The happy path is what is left when every refusal is
  handled.
- The router's `emit` returns the entry. That return value is your
  acknowledgement — do not construct a separate receipt object.
  Duplicating the receipt is how receipts and records disagree.
- For `ingest_batch`, sort a *copy*. The caller's list order is the
  caller's business; the evidence order is yours.
- The freshness check needs the injected clock, not `time.time()`
  directly — otherwise the stale test cannot be deterministic, and
  nondeterministic tests are a Chapter 15 failure wearing a Lab 1
  costume.
- Clause 8 will tempt you to invent a `market_data` event type. Do
  not. The closed taxonomy is a feature: it means every consumer of
  the evidence — the trace reconstructor, the evaluator, the auditor
  — already knows how to read what you emit.

## Red to green: the checklist

- [ ] `python -m pytest test_lab1_data.py -q` is red with
      `ModuleNotFoundError: No module named 'pipeline'` — the honest
      starting state. (If it is red for any other reason, the harness
      is broken; re-read the imports before writing a line.)
- [ ] `pipeline.py` defines `QuotePipeline`, `MalformedQuote`,
      `UnlabeledData`, `UntrustedSource`, importable from the lab
      directory.
- [ ] The happy-path test passes: one fetched quote in, one chained
      entry out, receipt returned.
- [ ] Each refusal test passes *and* asserts the audit log state
      afterwards — a refusal that emits is not a refusal.
- [ ] The ordering test passes: scrambled arrival, sequenced
      evidence.
- [ ] The chain test passes: `router.verify()` is clean after your
      emissions. (If it is not, you wrote to the log outside the
      router — the only writer is `emit`, per Chapter 9.)
- [ ] All 9 tests green. Then — and only then — compare against
      Appendix B, and be able to explain every line where yours
      differs.

## Figure

*Figure 20.1 — The morning pipeline: MCP quote server → pipeline (fetch, validate, label, route, acknowledge) → evidence spine, with the four adversarial fixtures (unlabeled, stale, untrusted, scrambled) stopped or flagged at the validation gate. Full rendering spec in `figs/ch20-figspec.md`.*

## Handoff

The pipeline runs, the evidence is labeled, and the log contains
nothing a signal cannot trust. But the pipeline only moves data —
it does not *decide* anything. The next lab crosses that line: Lab 2
takes an erratic language model, puts the strict `SignalProposal`
schema from Chapter 5 in front of it, and proves that even a model
having a bad day can only emit intentions a Pydantic gate has
approved. Data was Lab 1's problem. Judgment is Lab 2's.
