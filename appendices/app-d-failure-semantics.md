# Appendix D — Failure-Semantics Catalog

**Reference, not narrative.** Chapter 10 gave the action plane a taxonomy of the failures it can see; this appendix is the full catalog — every failure mode an agent system meets at its execution boundary, each with a name, a detection signal, and the pattern that handles it. Read it the way you read a fire-extinguisher chart: find your failure, find your pattern, do not improvise.

**Consistency note.** Chapter 10 is the seed. Nothing here contradicts it: every entry that Ch 10 named — timeout, partial fill, duplicate submission, stale read, ambiguous commit, accepted-not-yet-filled, read-after-write race, reconcile sweep failure — keeps its Ch 10 meaning and behavior. This appendix extends the taxonomy to the modes Ch 10 didn't cover (a tool that lies, auth expiring mid-run, model drift, human intervention mid-transaction) and generalizes two of them (partial fill → partial completion). Where Ch 14's 2:14am OUTCOME-UNKNOWN playbook is the operational face of a failure, the entry points at it instead of re-deriving it.

**The discipline.** Every entry below is built on one distinction — the most expensive sentence in production:

> *"The call failed"* is a fact. *"I don't know what happened"* is a debt.

A failed call has a name, a bounded blast radius, and a pattern. An unknown outcome has none of those until you name it, and the system that treats unknowns as failures (retry-and-hope) will eventually fabricate a fill, double a position, or lose money it cannot account for. The catalog's whole purpose is to make every unknown nameable — and therefore handleable.

Two rules govern every entry:

1. **Never guess at an unknown.** Timeouts may retry (the idempotency key makes it safe); ambiguity may never be resolved by assumption. Reconcile, then act. (Ch 10 § "The four outcomes of a submit.")
2. **The broker is the source of truth; the ledger is a cache.** When they disagree, the broker wins, and the ledger adopts its answer. (Ch 10 § "Reconcile.")

And one meta-pattern underlies all of them: the **saga** — the multi-step action treated as a unit, with each step's reversal planned before the step runs. The executor's ledger row is a saga log: intent recorded before the call, attempts counted, outcomes named. If you remember one idea from this appendix, make it this: reason about *transactions*, not *calls*.

---

## 1. Timeout

**Definition.** The submit exceeded its deadline (or the transport died: reset socket, broker 500). The outcome is unknown — the order may have been accepted, may have filled, may never have arrived. Timeout is not failure; it is the *absence of information*.

**Detect:** **the response never arrived within the deadline.** The observable signal is on your side of the boundary, not the broker's — you learn nothing about the broker's state from a timeout.

**Pattern: idempotent retry with the same key, then hold for reconcile.** Mark the ledger row `timeout`, back off exponentially, and retry with the **identical idempotency key** — the broker's dedupe turns a retried submit into a lookup of the first attempt, so the retry is safe even if the first attempt actually landed. After the retry budget is exhausted, stop. The row stays in `timeout` status — an honest "unknown" — and `reconcile()` resolves it against the broker's authoritative state. Never let a timeout become a guess about what happened.

**Worked example (Ch 10's executor).** Order 3 of the AlphaForge morning batch: submit times out. The ledger records `mark_timeout` with the attempt count; the retry loop fires with the same key `alphaforge-…-<hash>`; the broker dedupes to the existing order and returns `accepted`; the row moves to `open`; `await_fill()` polls it to `filled`. If the retry budget had expired instead, the row would sit in `timeout` until the end-of-session sweep reconciled it. In no branch does anyone *assume* the order's state.

**Never:** retry with a fresh key (that is how one timeout becomes two positions — Ch 10 § "Idempotency keys"), or retry immediately without backoff (that is how you turn one broker brownout into ten).

---

## 2. Partial completion

**Definition.** A multi-step action completed part of its effect. The canonical case is Ch 10's partial fill — the broker filled 400 of 1,000 shares — but the pattern generalizes: any action whose effect is divisible can land in the middle, and "mostly done" is not a status your ledger can carry.

**Detect:** **the broker's terminal response names a filled quantity smaller than the requested quantity.** Note "terminal": the broker is *done* with this order. A partial is not an order that is still working (that is "accepted, not yet filled"); it is an order whose remaining quantity will never fill under this key.

**Pattern: record partial as terminal; completion is a new decision.** The executor writes `partial` with the filled quantity and stops — full stop. Topping up the remainder is not the executor's job, because the remainder is a *new proposal*: it needs fresh authority (Ch 4's contract), a fresh idempotency key (derived from the new proposal, never recycled), and a fresh decision by the strategy layer. The saga frame helps: the partial is a completed step whose compensation plan was "the remainder becomes a new saga." What you must never do is loop inside the executor until the quantity is whole — that turns one authorized decision into an unbounded one.

**Worked example (Ch 10's executor).** Order 4 of the morning batch returns `partial`: 400/1,000 filled. `apply_broker_response` records `partial`, filled_quantity=400. The executor returns. The strategy layer sees the partial, decides it still wants the remaining 600, emits a *new* proposal with a new key (`…-<new-hash>`), and submits that. The ledger now shows two rows — one `partial`, one new submit — and the evidence trail (Ch 9) shows the decision that connected them. Any auditor can reconstruct the afternoon from those rows.

---

## 3. Stale read

**Definition.** Two sources disagree about the world, and at least one of them is out of date. The Ch 10 case: the ledger says `submitted`, the broker says `filled`. The general case: any cache — the ledger, a read replica, the agent's context window (Ch 2's Observe problem) — holding a past truth.

**Detect:** **two reads of the same entity return different states.** The signal is disagreement, not absence. The ledger's row_age and the broker's `lookup()` are the two witnesses; when they conflict, you have a staleness problem, not a data problem.

**Pattern: the authoritative source wins; caches adopt, never argue.** `reconcile()` adopts the broker's answer wholesale into the ledger. The ledger is a *cache* of the broker's truth, and a cache that contradicts its source is corrupt by definition. For the general case — any non-authoritative view the agent acts on — the pattern is versioning: stamp every read with the version or timestamp it was taken at (Ch 14's durable runs use fencing tokens for exactly this), and refuse to act on a read older than the decision's freshness window. An agent that decides on stale context and acts on live authority is how "the price moved three minutes ago" becomes an incident.

**Worked example (Ch 10's executor).** After the morning batch, a sweep finds a row in `submitted` while `lookup(key)` returns `filled`. No debate: the row becomes `filled` with the broker's timestamps. The stale `submitted` is not "corrected" — it is *replaced*, and the evidence log records that the broker was the source, so the correction itself is auditable.

**Never:** "fix" the broker's record to match your ledger. You do not have write access to reality; you have a cache of it.

---

## 4. Ambiguous commit

**Definition.** The broker accepted or filled the order, but the response was lost — a timeout that hides a success. This is outcome 3 (timeout) viewed from the broker's side, and it is the most dangerous failure in the catalog, because every instinct says to resubmit and every resubmission risks a duplicate.

**Detect:** **a `timeout` row whose broker state is unknown.** You cannot distinguish this from a true timeout from your side of the boundary — that is precisely what makes it ambiguous. The honest detection is the *absence of a distinguishing signal*: the row is in `timeout`, the retry budget is spent, and you have no broker record either way.

**Pattern: hold, reconcile, never guess — then follow the on-call playbook.** The row stays `timeout`. `reconcile()` queries by key: a broker record moves the row to `open` (then `await_fill` drives it terminal); a *persistently* missing record — past the 60-second settle window, so you are not racing a lagging replica — marks it `abandoned`, and only then is resubmission with the same key safe. The operational face of this failure is Ch 14's **2:14am OUTCOME-UNKNOWN playbook**: read, don't act; check the sweep, not the broker's status page; bounded escalation only (trip the desk-scoped kill switch, page the broker with the idempotency key); reconcile before resume, with the kill switch lifted by two verified operators. The failure mode that kills desks is not the outage — it is the human doing something creative during the outage.

**Worked example (Ch 10's executor + Ch 14).** Order 3's response is lost entirely — retries time out too. The row sits in `timeout`. The sweep's `lookup(key)` finally returns the broker's record: `accepted`, with a `broker_id`. The row moves to `open`, `await_fill()` polls it to `filled`. The 2:14am human, following the playbook, did exactly one useful thing: nothing — until the sweep resolved it, at which point the kill-switch-lift protocol ran. No resubmission, no ledger editing, no agent restart.

---

## 5. Tool lies

**Definition.** The tool returned success — but didn't do it. Or returned data that isn't real: a fabricated fill, a lookup result for an order that never existed, a "balance" that doesn't match the broker's books. Ch 10's anti-corruption layer assumes the broker speaks an honest protocol; this failure is what happens when the far side of the boundary is not trustworthy, or is buggy, or has been compromised (Ch 12's data-plane attacks at protocol scale).

**Detect:** **cross-plane disagreement that reconciliation cannot explain.** The signal is not a timeout or an error — it is a *claim* that fails verification: the tool says `filled` but a later authoritative lookup says the order never existed; two independent reads of the same quantity disagree; the evidence spine (Ch 9) shows an act with no matching world-state change. Treat every tool response as a claim, and every claim as unverified until it survives an independent check. The detection pattern is the Verify stage of the ODAV loop (Ch 2) pointed at the tool itself: verify is not "did the call return" — it is "did the world change the way the call claimed."

**Pattern: verify tool claims against the authoritative source; quarantine the tool on the first lie.** The executor's reconcile already implements the mild form: broker records beat tool claims. The full pattern extends it: (a) never let a tool's self-report be the terminal record — the terminal record is always the *independent* observation (broker lookup, balance query, position feed); (b) on a detected lie, quarantine the tool — route all its claims through heightened verification (Ch 12's output review is the content-level sibling), and emit evidence naming the discrepancy; (c) if the tool is a third-party integration, the lie is a vendor incident — the procurement questionnaire (Ch 19) exists precisely to ask vendors how their tools behave when they fail.

**Worked example.** The morning batch's broker adapter returns `{"status": "filled"}` for order 5 — but the fill never appears in the position feed. The executor does not record `filled` from the tool's word; `reconcile()`'s `lookup(key)` returns no record past the settle window, so the row is marked `abandoned` and the discrepancy is emitted as evidence. The tool is quarantined: subsequent submits through it require lookup-confirmation before any row goes terminal. The ledger never contains a fill the broker cannot confirm.

**Never:** record a tool's success claim as the terminal state without an independent observation. "The tool said so" is not evidence.

---

## 6. Auth expiry mid-run

**Definition.** The credential the executor acts under dies mid-session: the broker rotates API keys, the OAuth token expires, the tenant session is revoked. Calls that succeeded at 10:00 start returning 401/403 at 14:00. This is not a transport failure — the network is fine, the broker is fine, *your authority* is gone.

**Detect:** **authentication or authorization errors on calls that previously succeeded.** The signal is the *transition*: a 401 on a session that was verified an hour ago is auth expiry; a 401 on a session that was never verified is a configuration bug (Ch 3). The anti-corruption layer must translate this distinctly — it is a different universe from timeout, and mapping it to a retryable transport error is how you turn one expired token into a hundred failed attempts and a locked account.

**Pattern: stop acting, re-verify authority, resume from the ledger — never replay against dead credentials.** The boundary translates auth failures into a non-retryable error the executor treats as *terminal-for-this-session*: no backoff loop, no same-key retry (a retry with revoked credentials is both futile and, at some brokers, a lockout trigger). Control passes to the session layer (Ch 6): re-authenticate, obtain a *new* verified tenant session, and only then resume — with the executor's `reconcile()` running first, so every `submitted`/`timeout`/`open` row is re-resolved under the new session before a single new submit. The ledger is what makes resumption safe: the intent rows survived the auth death, so the new session inherits exactly the pending work and nothing else.

**Worked example.** At 14:00 the broker rotates keys. Order 6's submit returns 401. `wrap_broker` maps it to a non-retryable auth error — *not* `BrokerTimeout` — so the retry loop never fires. The executor marks the row and halts the batch. The session layer re-authenticates the tenant (Ch 6's verified session, fresh token), the sweep reconciles all pending rows (order 6: broker has no record → `abandoned` after the settle window → resubmitted under the new session with the same key), and the batch continues. The ledger shows a clean seam: submits before the seam under the old session, after the seam under the new one.

**Never:** cache credentials past their lifetime and retry into the void, or — worse — catch the 401 inside the executor and keep the batch running "in case it recovers." An unauthenticated executor is not a degraded executor; it is a stopped one.

---

## 7. Model drift

**Definition.** The model behind the agent changes its behavior without the system changing: the provider ships a new checkpoint, the pinned model is silently re-pointed, temperature ≠ 0 produces a different distribution, or the prompt's semantics shift as the model is updated. The failure is slow, silent, and — unlike every other entry here — it happens *above* the execution boundary, in the Decide stage (Ch 2), before the executor ever sees an order.

**Detect:** **eval regression on the frozen golden set.** The signal is statistical, not evented: pass rates on the pinned evaluation set (Ch 15) drift down, judge agreement (Cohen's κ) decays, or the distribution of proposals shifts (confidence calibration moves, a strategy that proposed 3 trades a day now proposes 30). No single bad decision detects drift — only the aggregate does. This is why Ch 15's regression-in-CI discipline exists: the eval suite is the smoke detector, and a model change that skips the eval gate is an unmonitored change.

**Pattern: pin, gate, shadow — then roll back.** (a) **Pin** the model: version, checkpoint, and parameters are part of system intent (Ch 3), and the provider integration (Ch 5) fails closed on an unpinned model. (b) **Gate** every model change through the eval suite: the golden set re-runs, κ and pass-rate thresholds (Ch 15) must hold, and cost-per-verified-success is recomputed — a "better" model that costs 3× per verified signal fails the gate. (c) **Shadow** the new model on live traffic before it touches the executor: proposals scored, never submitted, until the shadow's evals match or beat the incumbent's. On detection in production: freeze new submits (the kill switch is a legitimate response to a drifted brain — Ch 11), roll back to the pinned version, and let the walk-forward verdict (Ch 16–17) re-qualify the new model before it returns.

**Worked example.** The desk's signal-generating model is updated by the provider on a Tuesday. Wednesday's golden-set run shows κ dropping from 0.78 to 0.41 — the LLM judge and the deterministic grader no longer agree, because the model's thesis language changed. The CI gate blocks the rollout; the executor never sees a drifted proposal. The team shadows the new model for a week, re-qualifies it through the lab-4 pipeline (Ch 23), and only then re-pins. The cost of the week of shadowing is the price of the sentence the catalog forbids: "the model seemed fine."

**Never:** auto-accept provider model updates into a trading path, or detect drift by watching P&L (by the time the P&L moves, the drift has been trading for weeks).

---

## 8. Mid-transaction human intervention

**Definition.** A human (or another agent, or the kill switch) changes the world while a transaction is in flight: an operator cancels an order directly at the broker's dashboard, the desk-scoped kill switch trips during the `open` window, a second admin lifts a kill the first admin just tripped, a risk officer flattens a position the agent is managing. The intervention is not a failure of the system — it is an *input* the system did not plan for, arriving at the worst possible moment.

**Detect:** **ledger-vs-world mismatch with an out-of-band cause.** The signal looks exactly like a stale read (entry 3) — the ledger says `open`, the broker says `cancelled` — except the broker's audit trail shows the change came from a human session, not from the agent's key. Detection therefore has two parts: the sweep detects the *mismatch* (same as any stale read), and the evidence trail (Ch 9) attributes the *cause* (the broker's cancel record names the operator's session, not the agent's idempotency key).

**Pattern: no special-casing — the intervention is just another world-state change, and the sweep reconciles it; the gate prevents the next submit.** This is the entry where the catalog's discipline matters most, because the temptation is to build a "human override" code path with its own semantics. Don't. The sweep adopts the broker's truth regardless of who changed it: the human-cancelled order becomes `cancelled` (terminal) in the ledger, exactly as a broker-cancelled order would. The *gate* is where the human's authority lives: the kill switch (Ch 11) sets a flag the executor checks before every submit — GuardedBroker refuses new sends while the switch is tripped, and re-arm requires two verified admins. The human does not reach into the transaction; the human operates the gate, and the transaction reconciles around it. The evidence log records both: the human's action (who, when, under what authority) and the sweep's adoption of its effects. That record is what makes the intervention auditable instead of mysterious.

**Worked example.** During the morning batch, the risk officer trips the desk-scoped kill switch after order 3 — a headline just crossed. Orders 1–2 are `filled`; order 3 is `open`; orders 4–5 are never submitted (GuardedBroker refuses them). The sweep finds order 3 `filled` at the broker and closes the row. Meanwhile the risk officer, not trusting the sweep, cancels order 3 directly at the broker dashboard — a second intervention. The next sweep sees `cancelled` where the ledger said `filled`: the ledger adopts `cancelled`, the evidence trail records the operator's session as the cause, and the position feed is reconciled to match. The ledger is never "wrong" — it is a cache that caught up. When the headline clears, two admins lift the switch (Ch 11's two-person rule), and orders 4–5 are re-proposed as *new* decisions, because the world they were proposed into no longer exists.

**Never:** let a human edit the ledger (that is how fraud is born — Ch 14), restart the agent to "clear" the intervention (that is how the 3am death becomes a 3:05am second death — Ch 14), or build an override path that bypasses the gate. The gate is the human's instrument; the ledger is the system's memory; neither reaches into the other.

---

## The decision tree (summary)

For the figure specification (`figs/app-d-figspec.md`): the catalog compresses to one question asked in order —

1. **Did you get an answer?** No → **Timeout** (entry 1): same key, backoff, hold for reconcile.
2. **Did the answer claim less than the request?** Yes → **Partial completion** (entry 2): record terminal, remainder is a new decision.
3. **Do two sources disagree?** Yes → was the disagreement caused out-of-band by a human? → **Human intervention** (entry 8): adopt broker truth, gate the next submit. Otherwise → **Stale read** (entry 3): authoritative source wins.
4. **Is the outcome unknown after the retry budget?** Yes → **Ambiguous commit** (entry 4): never guess; reconcile; run the 2:14am playbook.
5. **Does the answer's claim fail independent verification?** Yes → **Tool lies** (entry 5): quarantine the tool, terminal records only from independent observation.
6. **Did authority die mid-run?** Yes → **Auth expiry** (entry 6): stop, re-verify the session, resume from the ledger.
7. **Did the aggregate behavior shift with no system change?** Yes → **Model drift** (entry 7): pin, gate, shadow, roll back.
8. **None of the above, but the world changed under you?** → You missed an entry. Go back to 1.

The tree's root lesson is the appendix's thesis: every branch ends in a *named* state and a *named* pattern. "I don't know what happened" is never a terminal node — it is always a pointer to the reconcile step that will find out.
