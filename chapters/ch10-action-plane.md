# Chapter 10 — The Action Plane and Execution

Everything before this chapter was rehearsal. The signal fired, the strategy sized the position, the risk gate approved it, the proposal was validated against every rule you wrote. None of that moved a dollar. This chapter is about the single line of code that does: the call that turns a validated proposal into an order at the broker. It is the most dangerous line in the entire system, and this chapter exists to make it boring.

The decision plane answers *what should happen*. The action plane answers *did it happen, exactly once, with proof*. That distinction is the whole chapter. Proposals are cheap, reversible, and re-runnable. Submits are none of those. The moment your agent's logic touches an external API that can move money, you have left the world of pure functions and entered the world of distributed systems — where networks lie, responses get lost, and "try it again" is how you end up long twice the size you intended at 9:31 on a Tuesday.

## The handoff: validated proposal in, exactly-one effect out

Chapters 3 through 9 built the left half — intent was formed, authority was granted and bounded, capability was checked. This chapter owns one arrow: **Action**. Its contract with the rest of the system is narrow and absolute:

- **Input:** a validated order dict. It carries an `idempotency_key`, a symbol, a side, a quantity, an order type. It has already passed every gate. The executor does not re-decide anything.
- **Output:** a ledger record stating, with evidence, what the broker did: filled, partial, rejected, open, timeout, or abandoned.
- **Guarantee:** the same order, executed any number of times for any reason — retry, crash recovery, operator double-click, duplicate message delivery — produces exactly one external effect.

Note what the executor is *forbidden* from doing. It may not change the quantity. It may not invent a new order to "top up" a partial fill. It may not widen a stop or chase a price. The authority granted to the proposal was for *that order, that size, that side*. An executor that improvises is an executor that trades without authority, and everything Part I taught about the capability–authority boundary applies here at full force: the executor has the *capability* to submit anything to the broker API, and its *authority* is precisely one validated proposal. The ledger in this chapter is the enforcement mechanism for that boundary.

## Idempotency keys: the one field that prevents double fills

An idempotency key is a client-chosen string that the broker treats as the order's true identity. Submit twice with the same key and the broker returns the *existing* order instead of creating a second one. Alpaca's paper API does this. So does Stripe, so does every serious order API. The broker-side dedupe is the foundation everything else in this chapter stands on — without it, safe retries are impossible, because a retried submit would be indistinguishable from a second order.

The key must be derived **deterministically from the validated proposal**: a hash of symbol, side, quantity, order type, strategy id, and decision timestamp. Something like `alphaforge-2026-09-11-<proposal-hash>`. The catastrophic version of this idea — the bug I want you to never write — is generating a fresh UUID per *attempt*. That gives every retry a new identity, which tells the broker "this is a brand-new order," which is precisely how a timeout plus one retry becomes a doubled position. The key identifies the *order*, not the *attempt*. Attempts are counted in the ledger; the key never changes across them.

One more rule: keys must be unique across *proposals*. Two different decisions must never share a key, or the second will silently adopt the first's fill. Derive from the proposal content and you get this for free — different content, different hash, different key.

## The write-ahead ledger: record intent before you act

The executor keeps a local ledger — SQLite in our implementation, a dict would do for a toy — and the ordering of writes is the entire game:

1. **Write the intent row first** (`status='submitted'`, attempt count), *then* call the broker.
2. Update the row when the outcome arrives.

Why this order matters: consider the crash between "broker filled the order" and "we recorded the fill." If you called the broker first and recorded second, a crash in that window leaves you with a filled order at the broker and *no record of it*. On restart you would cheerfully submit it again — same key, so the broker dedupes and you're actually safe on the *fill* count, but your books now disagree with reality and your position tracking is corrupt. Write-ahead means the worst case after a crash is a ledger row that says `submitted` with no outcome — which is exactly the ambiguous state `reconcile()` exists to resolve. The ledger is never *wrong* about what it doesn't know; it says "unknown" honestly, and unknown is a state the system knows how to handle.

This is the same write-ahead discipline databases have used for fifty years, applied to the agent's side effects. Your agent's memory of what it did to the world must be at least as durable as the actions themselves.

One concurrency note: the ledger opens SQLite in WAL mode with a 30-second busy timeout, so the trading thread can submit while a scheduler thread runs `reconcile()` without locking errors. That covers light concurrency; for heavy parallel writers, serialize the ledger behind an explicit mutex — a busy timeout buys patience, not ordering.

## The four outcomes of a submit

Every submit ends in exactly one of four ways, and confusing them is the source of nearly every execution bug:

**1. A definitive response.** The broker answered: filled, partially filled, or rejected. Record it, return it, done. Rejections are terminal — a rejected order is not retried, because the broker *told you no*, and retrying a no is how you turn a risk-gate rejection into an incident. Partials are terminal too: the executor records `partial` with the filled quantity and stops. Topping up the remainder is a *new decision* requiring *new authority* — it belongs in the strategy layer as a new proposal with a new key, never in the executor.

**2. Accepted, not yet filled.** Real brokers do not fill synchronously. Alpaca's paper API — like every production order API — *accepts* the order first (`new`/`accepted`) and fills it later, sometimes seconds later, sometimes after a partial cascade. Treating an acceptance as a fill is a lie; treating it as a timeout is wasteful and wrong, because retrying an accepted order is pointless. So the executor records a third ledger state, **`open`**: the broker has the order (the acceptance carries a `broker_id`), the fill is pending. A separate transition, `await_fill()`, polls `lookup(idempotency_key)` until the broker reports terminal or a wait budget elapses. In production you would replace the poll loop with the broker's websocket order-update stream — the state machine is identical, only the trigger changes from poll to push, and `reconcile()` remains the backstop either way.

**3. A timeout or transport error.** The call exceeded its deadline, the connection reset, the broker 500'd. The outcome is *unknown*: the order may have been accepted, may have filled, may never have arrived. This is the only outcome that retries — with the **same key**, with exponential backoff, and only up to a configured limit. The same key is what makes the retry safe: if the first attempt actually got accepted, the retry hits the broker's dedupe and returns the existing order instead of creating a second one. Backoff matters because hammering a struggling broker with immediate retries is how you turn one timeout into ten. After the retry budget is exhausted, the executor does the disciplined thing: it stops, leaves the row in `timeout` status, and returns it. It does not guess.

**4. The ambiguous commit.** This is outcome 3 viewed from the broker's side: the order was accepted or filled, but the response was lost. The broker is holding your order; your ledger says `timeout`. This state is *expected* — in a busy market it will happen — and the system treats it as a first-class citizen rather than an edge case. It is resolved by `reconcile()`, never by assumption: the sweep finds the broker's record and the row moves to `open` (then `await_fill` drives it terminal) — or, if the broker truly never saw it, to `abandoned`.

Notice the asymmetry the chapter is built on: **timeouts may retry; ambiguity may never be guessed at.** Retrying is safe because the key makes it idempotent. Guessing is never safe because there is no mechanism that makes a wrong guess harmless. When in doubt, the executor prefers a row that says "unknown" over a confident lie.

## Reconcile: the broker is the source of truth

`reconcile()` is the end-of-day sweep, and the discipline around it is simple: **no order may remain in an unknown state.** For every ledger row stuck in `submitted` or `timeout`, the executor asks the broker — `lookup(idempotency_key)` — what actually happened, and adopts the broker's answer wholesale:

- Broker has a record → the ledger adopts the broker's answer wholesale: terminal statuses (`filled`/`partial`/`rejected`) close the row; an acceptance moves it to `open`, where `await_fill()` or the next sweep drives it terminal.
- Broker has no record → the order is marked `abandoned` — **but only after the settle window**. A missing record is not proof the broker never saw the order: the lookup may be racing a just-sent submit, or it may have hit a lagging read replica. Treating a premature `None` as abandonment and resubmitting is exactly how a doubled fill happens on a slow broker. So `reconcile()` checks the row's age first: if it is younger than `settle_seconds` (60 seconds in production), the row stays pending and a later sweep decides. Only a *persistently* missing record earns `abandoned`, and only then is resubmission with the same key safe — there is nothing to collide with.

Two properties make reconcile trustworthy. First, it is *read-only* toward the broker: it queries, never submits, so running it twice or running it concurrently with execution cannot create fills. Second, one key's network failure must not kill the sweep: transport errors are trapped *per key*, recorded on the row (`reconcile_error`), and retried by the next sweep — a single flapping lookup can't leave the other ninety-nine orders unknown. It runs *before* any resubmission of a previously ambiguous key. The rule from the module docstring bears repeating: never resubmit on an ambiguous commit without reconciliation. The `execute()` method enforces this itself — if it finds a prior row in `submitted`/`timeout`/`open` state, it reconciles that key before doing anything else. A process that crashed mid-batch on Monday and restarts on Tuesday will reconcile Monday's ambiguity before it submits a single new order.

In production this sweep runs on a schedule — every minute during the session, and mandatorily at the close — plus on every executor startup. An unknown state is a debt, and reconcile is how you pay it.

## The failure taxonomy

Every failure the action plane can see, and what the executor does about each:

| Failure | What happened | Executor behavior |
|---|---|---|
| Timeout | Submit exceeded deadline; outcome unknown | Mark `timeout`, backoff, retry with **same key** (broker dedupe prevents a second fill); after budget, hold in `timeout` for reconcile |
| Partial fill | Broker filled part of the quantity | Record `partial` as **terminal**; never top up — a remainder is a new proposal with a new key, decided upstream |
| Duplicate submission | Same key submitted twice (retry, crash recovery, double-click) | Broker returns the existing order; ledger unchanged; second `execute()` call returns the cached terminal record without touching the broker |
| Stale read | Ledger and broker disagree (e.g. ledger says `submitted`, broker says filled) | Broker wins. `reconcile()` adopts broker truth into the ledger; the ledger is a cache, the broker is the source |
| Ambiguous commit | Accepted server-side, response lost | Status stays `timeout`; **never guessed**. `reconcile()` queries by key: a broker record moves the row to `open` (then `await_fill` drives it terminal), a persistently missing record past the settle window marks it `abandoned` |
| Accepted, not yet filled | Broker acknowledged the order (`accepted`/`new`); fill comes later | Record `open` with the broker id; `await_fill()` polls to terminal (or the broker's websocket pushes updates in production); never treated as filled, never retried |
| Read-after-write race | `lookup()` returns nothing, but the submit is still in flight or the read hit a lagging replica | Row younger than `settle_seconds` stays pending — a missing record is only proof of abandonment after the window; premature resubmission is how double fills happen |
| Reconcile sweep network failure | One key's `lookup()` raises a transport error mid-sweep | Trapped per key, recorded as `reconcile_error`, sweep continues; the next sweep retries the failed key |
| Unwrapped transport error | Raw `ConnectionError`/`TimeoutError` from the SDK reaches the executor | The injected broker callable is an anti-corruption layer: `wrap_broker()` maps transport failures to `BrokerTimeout`/`BrokerError` at the boundary; anything else propagates as a bug, never a phantom retry |

The table has a theme: in every row, the executor's job is to *narrow uncertainty without creating new effects*. Retries don't create fills (dedupe). Reconcile doesn't create fills (read-only). The only thing that creates a fill is a first submit of a previously unseen key — and the ledger guarantees you only ever do that once per proposal.

## The broker boundary is an anti-corruption layer

There is one more contract in this chapter, and it sits *outside* the executor: the injected broker callable itself. The executor's retry logic catches exactly two exceptions — `BrokerTimeout` and `BrokerError` — and that `except` clause is only correct if nothing else can arrive wearing a transport failure's clothes. A raw `ConnectionError` from a reset socket or a bare `TimeoutError` from the HTTP layer must never reach the executor unmapped: the first would propagate as an unexpected crash, the second would be anybody's guess.

So the object you inject is an **anti-corruption layer**: its job is to translate the transport's failure vocabulary into the broker protocol's. The module ships `wrap_broker()` for exactly this — it returns a `BrokerAdapter` that maps `TimeoutError` to `BrokerTimeout` (outcome unknown, safe to retry with the same key) and `ConnectionError`/`OSError` to `BrokerError`, passes protocol exceptions through untouched, and lets everything else propagate as the programming bug it is. Wrap the real SDK client at the boundary, once, and the executor's narrow `except` clause stays honest. The test suite pins this: a fake that raises a raw `ConnectionError` is wrapped, retried, and ends in `open` — never in a traceback.

One design note, because this is where the first version of this chapter was wrong: the adapter is a *class*, not a function decorator. The original `wrap_broker` decorated the submit callable — and decorators return bare functions, which silently strip every other attribute the protocol needs. The first time a decorated broker went to reconcile, `broker.lookup(key)` crashed with `AttributeError`. The broker is not a function; it is a protocol — submit *and* lookup — and both paths make network calls, so both get the same translation. An external review caught this precisely because the test suite was blind to it: the wrapped-broker test only ever submitted, never reconciled. There is now a dedicated test that forces reconciliation through the adapter, and the honest lesson is worth keeping: a test that never exercises the path it claims to protect is not coverage, it is costume.

## The code: `action_executor.py`

The full module is `code/ch10/action_executor.py` (stdlib + pytest only; ~200 lines). Its core loop is worth reading in full, because every line is a decision from the taxonomy above:

```python
def execute(self, order, broker):
    key = order["idempotency_key"]

    prior = self.ledger.get(key)
    if prior is not None:
        if prior["status"] in TERMINAL:
            return prior            # decided already; never resubmit
        if prior["status"] in PENDING:   # submitted | timeout | open
            resolved = self.reconcile_key(key, broker)  # ask first, submit never
            if resolved is None or resolved["status"] != "abandoned":
                return resolved     # open rows return here too: no resubmit

    attempts = 0
    while True:
        attempts += 1
        self.ledger.record_attempt(key, order, attempts)  # write-ahead: before the call
        try:
            response = broker(order, self.timeout)
        except (BrokerTimeout, BrokerError) as exc:
            self.ledger.mark_timeout(key, attempts, str(exc))
            if attempts > self.max_retries:
                return self.ledger.get(key)   # hold as 'timeout'; reconcile later
            time.sleep(self.backoff * 2 ** (attempts - 1))
            continue                          # SAME key — no duplicate possible
        # Terminal fills/rejections land here; acceptances land in 'open'.
        return self.ledger.apply_broker_response(key, response, attempts)
```

Five things to notice. First, the terminal-key early return: calling `execute()` twice with the same order touches the broker exactly once — the second call is a ledger lookup. Second, the pending-key path reconciles *before* submitting, which is the "never resubmit on ambiguity" rule made executable — and `open` rows flow through the same path, so a double-click on an accepted order refreshes its state instead of resubmitting it. Third, `record_attempt` runs before `broker(...)` on every attempt — write-ahead, no exceptions. Fourth, the final line routes through `apply_broker_response`, which is where the synchronous-fill assumption dies: an acceptance becomes `open`, not `filled`, and the fill is observed later through `await_fill()` or the sweep. Fifth, the retry loop only catches `BrokerTimeout` and `BrokerError` — and that narrow clause is honest only because `wrap_broker` guarantees the universe of inputs at the boundary. Catching everything would turn programming bugs into phantom retries.

## Worked example: five orders, one lost response

The test suite (`code/ch10/test_action_executor.py`, 16 tests, all green) runs the AlphaForge morning batch — five market orders, alternating buy/sell on AMD — against an in-memory fake of Alpaca's paper API. The fake implements the two broker behaviors the whole design leans on: **server-side dedupe on the client order id**, and **accept-first, fill-later** — submits return `accepted`, and the fill appears on a later `lookup()`. The scenario that matters is order 3:

1. The executor writes its intent row and submits order 3.
2. The fake broker *accepts it* — then raises `BrokerTimeout` instead of returning. The response is lost. The broker is holding the order; the ledger says `timeout`. This is the ambiguous commit, manufactured on demand.
3. The executor backs off and retries **with the same key**. The fake sees a known key and returns the existing acceptance — no second order, no second fill. The ledger records `open`, attempt count 2, one broker id.
4. `await_fill()` polls `lookup()`: first poll still shows `accepted`, second shows `filled`. The ledger closes the row. The broker's internal order book holds exactly five orders for five keys.

A second test drains the retry budget (`max_retries=0`) so the order genuinely ends in `timeout` — then `reconcile()` asks the broker, learns it was accepted (row moves to `open`), and `await_fill()` drives it to `filled`. A third covers the crash case with a fake clock: a ledger row marked `submitted` with nothing at the broker reconciles to *still pending* inside the settle window (the lookup may be racing the submit), and only to `abandoned` — safe to resubmit — after the window passes. The suite also pins the negative behaviors: terminal keys never resubmit (the double-click test), an `open` key re-executed refreshes from the broker instead of resubmitting, partials are terminal without top-up, rejections stay rejected, one key's lookup failure is trapped per-order without killing the sweep, a raw `ConnectionError` through the adapter becomes a retried `BrokerError` instead of a traceback, and a forced reconciliation *through* the wrapped adapter proves the exception translation holds on the lookup path too — submit and lookup both speak the protocol's failure vocabulary.

Run it: `python3 -m pytest code/ch10/ -q` → **16 passed**.

FIG: The Action Execution Lifecycle (state machine)

States: proposed → validated → submitted → open → {filled | partial | rejected}; plus timeout and abandoned. Terminal states are filled, partial, rejected, abandoned — execute() never resubmits them. The open state is the fix for the synchronous-fill assumption: real brokers accept first and fill later.

- proposed ──(validate: risk gates, contract checks)──▶ validated
- validated ──(ledger already holds terminal record for key)──▶ filled | partial | rejected  [cached return; broker never touched]
- validated ──(ledger holds submitted/timeout/open for key)──▶ reconcile FIRST, then proceed  [open rows refresh from broker; no resubmit]
- validated ──(write intent row, then submit)──▶ submitted
- submitted ──(definitive broker response)──▶ filled | partial | rejected  [recorded; terminal]
- submitted ──(broker accepts: new/accepted)──▶ open  [broker_id captured; fill pending]
- submitted ──(timeout / transport error)──▶ timeout  [outcome unknown; ledger honest]
- open ──(await_fill poll: lookup shows terminal)──▶ filled | partial | rejected
- open ──(await_fill poll: still accepted, budget remains)──▶ open  [keep polling]
- open ──(await_fill: max_wait elapsed)──▶ open  [held for the scheduled sweep; never forced]
- timeout ──(retry: SAME idempotency key, exponential backoff)──▶ submitted  [broker dedupe ⇒ no duplicate]
- timeout ──(retry budget exhausted)──▶ timeout  [held; reconcile() resolves; never guessed]
- timeout|submitted|open ──(reconcile: broker.lookup finds record)──▶ filled | partial | rejected | open  [broker truth adopted]
- timeout|submitted ──(reconcile: no record AND row older than settle_seconds)──▶ abandoned ──(resubmit, same key)──▶ submitted  [safe: nothing to collide with]
- timeout|submitted ──(reconcile: no record BUT row younger than settle_seconds)──▶ unchanged  [racing a submit or a lagging replica; later sweep decides]
- any pending ──(reconcile: lookup raises transport error)──▶ unchanged + reconcile_error recorded  [sweep continues; next sweep retries]

Invariants: (1) the ledger is written before the broker is ever called; (2) no transition out of timeout toward submitted without the same idempotency key; (3) reconcile() is read-only toward the broker — it queries, never submits; (4) the broker is the source of truth whenever ledger and broker disagree, except that a *missing* record only wins after the settle window; (5) in production, await_fill's poll loop may be replaced by the broker's websocket order-update stream — same states, push instead of poll.

## What this fixes

It makes the submit call safe to retry and honest about asynchrony: the same validated order, executed any number of times for any reason, can only ever fill once; acceptances are tracked as `open` and polled to terminal rather than assumed filled; no broker record is trusted as abandonment until the settle window passes; and no order is ever left in an unknown state.

## Exercises

1. **Kill-switch drill.** Add a `halt()` method to `ActionExecutor` that refuses all new submits (raise `HaltedError`) but still permits `reconcile()`. Write a test where three orders time out *after* the halt is engaged: assert no new submits occur, every order ends reconciled (filled or abandoned), and `pending_keys()` is empty. This is the shape of a real trading halt — freezing is not the same as resolving.
2. **Partial-fill policy, upstream.** The executor records partials as terminal by design. Write a `TopUpPolicy` in the *strategy* layer (not the executor) that, given a `partial` ledger record, proposes a new order for the unfilled remainder with a *new* idempotency key derived from the original key plus a `-topup-1` suffix. In three sentences, argue why the new key must differ from the original — and what would break if it didn't.
