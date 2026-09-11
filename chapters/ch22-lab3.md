# Chapter 22 — Lab 3: Execution Under Fire

*Part VII: Practice. This is a lab, not a lecture. It is red on purpose.*

## The fire drill

Every trading desk has a story about the afternoon everything broke at
once. The good desks have something better: a drill they ran *before*
the afternoon happened. This lab is that drill.

It is 14:32 on a Thursday — synthetic, but treat it as real. The market
starts dropping. Over the next hour it falls more than five percent.
Your paper broker first starts *rejecting* orders ("risk: market-wide
halt"), and then it goes silent entirely: submits time out, lookups
fail, and the only honest thing your ledger can say is *unknown*.

When the dust settles, one question decides whether your desk survives
the postmortem:

> Is every intent accounted for — filled, rejected, or honestly unknown —
> with no phantom fills and no double-submits?

A phantom fill is a ledger row that claims *filled* when the broker never
filled anything. A double-submit is two broker orders where the desk
intended one. Both are born the same way: someone guessed at an outcome
instead of reconciling it. This lab makes you build the system that
refuses to guess.

## What you are proving

This lab is the composition of two cleared chapters, and the point is
that the composition is where the interesting failures live. Each
component passed its own tests. Put them together under a crashing
market and watch the seams:

- **Chapter 10 — the action plane.** The executor keeps the ledger
  consistent while the world falls apart: write-ahead rows, idempotent
  retries with the *same* key, reconcile against broker truth. The four
  outcomes of a submit (definitive response, accepted-not-filled, timeout,
  ambiguous commit) all show up in one afternoon.
- **Chapter 11 — kill switches.** The kill trips at the 5%/hour threshold,
  and the *scoped* kill isolates only the affected desk. The momentum desk
  next door keeps trading its perfectly good signals — the Chapter 6
  lesson returns wearing work clothes: tenant isolation is not a feature,
  it is the unit of blame.
- **Chapter 14 — the on-call script.** When the broker goes silent
  mid-reconciliation, the system says OUTCOME-UNKNOWN and means it. What
  the humans do next is the on-call playbook from Chapter 14; the lab
  hands you the reference and grades the machine's half.

The desk is AlphaForge's day-trading desk, on paper, on purpose. The
crash fixture is synthetic — every bar is labeled SYNTHETIC, and the lab
refuses to pretend otherwise. The discipline it teaches is real.

## The fixture: four phases of a bad afternoon

`FlashCrashBroker` is given, and you do not modify it. It is a raw broker
simulator with a scripted timeline — raw meaning it speaks the broker
protocol (`__call__(order, timeout)` plus `lookup(key)`), so your job
includes wrapping it at the boundary with `wrap_broker`, exactly as
Chapter 10 demands. Its four phases:

| Phase | Submits | Lookups | Meaning |
|---|---|---|---|
| `normal` | fills immediately | broker truth readable | the morning, before |
| `rejecting` | answered, but *rejected* | readable | "risk: market-wide halt" |
| `silent` | `TimeoutError` | `ConnectionError` | the broker is gone |
| `recovered` | fills | readable | the network is back |

The broker keeps `orders`, its book of record. One of the tests compares
that book against your ledger: they must agree *exactly*. If your ledger
claims a fill the broker never made, the test fails — that is the
phantom-fill detector, and it is the most important assertion in the lab.

The market data is `crash_bars()`: sixty deterministic minute bars
sliding about 6.6%, no randomness, so the trip bar is reproducible. And
`second_wave_bars()`: a second leg down *during* the halt, there to test
the no-re-entry discipline. Deterministic fixtures are not a convenience
here; they are the point. A fire drill you cannot replay is theater.

## What you build: the wiring

The cleared components are given. What is missing — what every one of
the eight tests is waiting for — is the *wiring*: four functions that
compose the components into a desk. This is deliberate. In production,
the components are the easy part; the wiring is where desks die.

**1. `wire_desk(secret)` — build the desk.** Construct the Ledger, the
ActionExecutor, the OperatorRegistry, and the KillSwitch, and return them
in a context dict with the broker wrapped *once, at the boundary*, as
`killswitch.guarded(wrap_broker(raw))`. The ordering of the wrapping is
not cosmetic: `wrap_broker` translates transport failures into the
executor's exception taxonomy, and `guarded` re-checks the kill gate at
send time (the Chapter 11 TOCTOU fix). Swap the order and you have built
a gate that checks after the wire — read the `GuardedBroker` docstring
until the ordering feels obvious, because it is load-bearing.

Two details that will bite you if you skip the chapter docstrings:

- The KillSwitch **boots armed-by-default**. Before the first `beat()`,
  every submit is refused. Your wiring must beat the supervisor
  heartbeat, or your desk is a desk that never trades — and three tests
  will tell you so, unhelpfully, with `HeartbeatStale`.
- The executor takes `settle_seconds=0, max_retries=0, backoff=0` in this
  lab. Not because those are production values — they are not — but
  because the lab is about *composition*, not tuning. Deterministic and
  fast beats realistic and flaky when you are grading wiring.

**2. `submit_intent(ctx, order, scope)` — the single doorway.** Every
order the desk sends passes through this function, and it does exactly
two things in exactly this order: check the kill gate *with the scope*
(`killswitch.check("submit", scope=scope)`), then run the executor
through the *wired* broker. If the gate refuses, return
`{"refused": True, "reason": ...}` with the kill level **named** in the
reason — a refusal without a reason is a different kind of unknown, and
the test asserts on the name. A refused submit must leave no ledger row:
the ledger records what the system *did*, and a refusal is something the
system *declined* to do. (Chapter 11's heartbeat section explains why;
the test `test_ledger_consistent_after_halt` checks the phantom row is
absent.)

The scope on the check is what makes the kill surgical. Check without
the scope and the scoped kill never fires for your submits — desk A
would trade straight through its own halt. The test for the innocent
desk catches the mirror image: check *globally* and desk B gets punished
for desk A's crash.

**3. `drive_market(ctx, bars, scope)` — feed the bars, trip the kill.**
Track the drop from the first bar's close; the moment it reaches 5%,
engage a **scoped** `PAUSE_INTENTS` kill for that scope with a *written*
reason naming the measured drop. `engage` requires a verified operator
session from the registry — raw strings are rejected outright (Chapter
11 earned that the hard way; the lab inherits it). One trip per session:
if the kill is already armed for the scope, measure and report, do not
re-engage — re-engaging an armed kill raises `KillAuthError`, which is
exactly what the second-wave test is checking for.

**4. `close_out(ctx)` — the end-of-day discipline.** Run the reconcile
sweep through the wired broker and report `{"pending": [...], "states":
{...}}`. After this, `pending` must be empty — or every remaining row
must carry a recorded `reconcile_error`, which is the ledger's way of
saying *I still don't know, and here is why*. Reconcile reads are never
gated, at any kill level: freezing is not resolving, and a kill that
blinded the operator would trade one unknown for another.

## The honesty rules

The lab grades these. Read them as the specification, not as advice:

1. A row may be `filled` only if the **broker** says so. Broker truth
   wins; the ledger adopts, never invents.
2. A row may be `abandoned` only after the settle window with **no broker
   record** — never while the broker is merely silent. Silence is not
   absence; it is the absence of evidence.
3. `timeout`, `submitted`, and `open` are **honest states**, not failures.
   The failure is claiming to know what you do not.
4. One admin cannot lift a `FULL_STOP`. Ever. Not the admin who engaged
   it, not a different admin, not with a good reason. Two distinct
   verified sessions or the kill stands.

Rule 2 is where most first attempts die: the instinct, when the broker
goes silent and the sweep finds nothing, is to mark the row abandoned
and move on. That instinct manufactures phantom abandonments the same
way guessing manufactures phantom fills. The settle window exists
because a missing record *during an outage* proves nothing.

## The adversarial catalog

The eight tests are the drill's script. Know what each one is attacking:

1. **The trip.** The kill arms at the 5% drop, and the refusal names
   `PAUSE_INTENTS`. (Attacks: a kill that never trips; a refusal that
   doesn't say why.)
2. **The innocent desk.** Desk B trades through desk A's halt.
   (Attacks: global checks; scope leakage.)
3. **In-flight reconciliation.** Orders submitted across all four broker
   phases reconcile to terminal states; ledger fills equal broker fills
   exactly; no duplicate submits. (Attacks: phantom fills, double
   submits, invented outcomes.)
4. **Ledger consistency after the halt.** Every intent accounted for;
   refused submits left no phantom rows. (Attacks: the ledger that
   forgets what it declined.)
5. **The silent broker.** While silent, the row stays `timeout` with a
   recorded `reconcile_error` — never guessed to `filled` or
   `abandoned`. (Attacks: optimism as a bug.)
6. **The second wave.** Re-engaging an armed kill is refused; the second
   leg down breaks against the armed kill; submits stay refused.
   (Attacks: kill stacking; re-entry during the halt.)
7. **The single admin.** One admin cannot lift `FULL_STOP` — tried twice,
   with two different admins, refused twice. (Attacks: two-string
   control; the emergency that becomes a shortcut.)
8. **The lift.** Two verified admins, a written reason, a fresh
   heartbeat — trading resumes. (Attacks: the kill that can never be
   lifted; the lift without the reason.)

Test 5 deserves a second look, because it is the lab's thesis in one
assertion: `assert row["status"] == "timeout"`. After the sweep, in the
middle of the outage, the correct final answer is *I don't know yet*.
The row carries the error that explains why. That is not an incomplete
implementation. That is the implementation.

## Red to green: the checklist

- [ ] Run the lab as shipped. Watch all eight tests fail at the fixture
      with `NotImplementedError`. Read each failure message — they are
      the specification.
- [ ] Implement `wire_desk`. The first green test will be the innocent
      desk's heartbeat, not the crash: get *normal* working before you
      earn the disaster.
- [ ] Implement `submit_intent`. Refusals name the kill level; refused
      submits leave no rows.
- [ ] Implement `drive_market`. Trip at 5%, scoped, written reason,
      verified session. One trip per session.
- [ ] Implement `close_out`. Reconcile through the wired broker; report
      honestly.
- [ ] All eight green. Then read the audit log: `killswitch.audit()`
      should tell the story of the afternoon — trip, refusals, lift —
      in order. If it doesn't, your wiring is right and your
      observability is wrong, which is its own lesson.
- [ ] Break it on purpose: set the broker silent *before* any submit and
      confirm the ledger says unknown, not filled. Remove the `beat()`
      and confirm nothing trades. These are the two cheapest chaos
      experiments in the book, and they take thirty seconds.

## What Appendix B provides

The answer key in Appendix B is the reference wiring — one correct
composition, not the only one. It is graded by the same eight tests, and
it is there for the moment you have earned it: after your implementation
is green, or after you have stared at a red test long enough to know
exactly what question to ask. The key's `drive_market` measures the drop
from the first bar of each feed and guards re-engagement; its
`submit_intent` catches the gate refusal before the executor is touched;
its `close_out` reconciles through the guarded broker so the sweep
itself respects the kill. Compare its choices against yours — where they
differ, one of you has a reason, and the reason is the lesson.

## The handoff

The desk survived its worst afternoon on paper. Every intent is
accounted for, the innocent desk kept trading, the silent broker was
met with honesty instead of optimism, and the kill that stopped the
bleeding was lifted by two people with a written reason.

Lab 4 is the last drill, and it is the longest one: a full quarter of
market history, walk-forward with embargoes, PSR and DSR deflating the
lucky, and an LLM judge scoring the theses. Lab 3 proved the desk can
survive a bad afternoon. Lab 4 asks whether it was ever any good.

---
*Figure 22.1 — the crash timeline: broker phases, the 5% trip bar, the
silent window, and the reconcile sweep. Full specification in
`figs/ch22-figspec.md`.*
