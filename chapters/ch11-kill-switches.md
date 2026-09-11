# Chapter 11 — Kill Switches and Hard Risk Limits

At 02:47 on a Tuesday, WealthForge's dividend-capture agent started buying. Nothing was wrong with the infrastructure. The model was up, the broker was answering, the ledger was writing clean rows, the heartbeat from the supervisor process arrived every five seconds like a metronome. Every health check was green. The agent was healthy.

That was the problem.

A stale signal cache had frozen the "ex-dividend tomorrow" flag on. The strategy, doing exactly what it was coded to do, re-fired its buy intent every minute — and the action plane, doing exactly what *it* was coded to do, validated each proposal and submitted it. By 03:12 the paper portfolio was 40x overweight in a single name. Nothing had malfunctioned. Every component had behaved correctly according to its local logic, and the system as a whole was driving off a cliff with the cruise control engaged.

The operator on call did the only thing that mattered: she killed it. Not by asking the agent to stop — the agent's self-report said everything was fine, and a system that must *agree* to stop is a system that can *refuse* to. She killed it from outside the agent's authority entirely: a switch in the infrastructure, between the decision plane and the broker, that the agent cannot see, cannot veto, and cannot route around.

This chapter is that switch. (If you did Exercise 1 in Chapter 10 — a `halt()` method on the executor — this chapter is the full, production version of that drill, with the authority math made explicit.)

## The stop button must not ask permission

Every safety mechanism in this book so far has lived *inside* the agent's pipeline: contracts validate proposals, the executor dedupes submits, the ledger records truth. The kill switch is the first mechanism that lives *outside* it, and that placement is the entire point.

Consider the failure modes a kill switch must survive:

- **The agent is compromised.** Prompt injection (Ch 12) has the model issuing plausible-looking orders. A kill switch the agent can talk its way past is decoration.
- **The agent is correct but wrong.** The 02:47 loop: no bug in the executor, no injection, just a stale upstream signal. The agent will never flag itself because from its vantage point nothing is wrong.
- **The supervisor is dead.** The process that *would* have noticed is itself crashed. The kill must trigger on the *absence* of a signal, not on anyone's decision to send one.

These three cases share one property: **the decision to stop cannot depend on the cooperation, the judgment, or even the existence of the thing being stopped.** The kill switch is infrastructure. It answers to operators and to hard risk arithmetic, and it fails closed — when in doubt, it stops trading.

That last clause deserves emphasis because it inverts the usual engineering instinct. Most systems fail *open*: a monitoring agent crashes, and trading continues unmonitored. A kill switch must fail the other way. Loss of the heartbeat kills trading. Loss of the operator console kills trading. Ambiguity kills trading. The default state of the system, in the absence of positive evidence that a responsible party is watching, is *stopped*. You will feel the cost of this every time a flaky network causes a false halt. That cost is the premium on the insurance. Price it, budget for it, and never negotiate it away after the first false positive — the false positive is the system demonstrating that it works.

## Four levels of kill

Not every emergency is a full stop. A fat-fingered signal needs a pause; a runaway loop needs its open orders pulled; a breached risk limit needs positions flattened; a suspected compromise needs everything frozen and the keys revoked. One binary switch forces operators to choose between "do nothing" and "nuke everything," and under pressure they will hesitate — which is how a pausable incident becomes a full-stop incident. Graduated levels make the cheap response cheap:

| Level | Name | New submits | Open orders | Cancels | Reconcile / reads | Engaged by |
|---|---|---|---|---|---|---|
| 1 | PAUSE_INTENTS | refused | continue | allowed | allowed | any operator |
| 2 | CANCEL_OPEN | refused | cancelled once, at engagement | allowed | allowed | any operator |
| 3 | FLATTEN_HALT | refused | cancelled, then positions flattened | allowed | allowed | any operator, or RiskMonitor automatically |
| 4 | FULL_STOP | refused | cancelled, flattened, **broker API keys revoked** | **refused — state frozen** | allowed | **two distinct operators** |

Three things to notice. First, **reconcile and reads are never gated**, at any level. Reconcile is read-only toward the broker — it resolves unknown states without creating effects — and freezing is not the same as resolving. A kill that also blinded the operator would trade one unknown (what is the agent doing?) for another (what did it do?). The ledger must show exactly what happened, especially during the kill.

Second, the side effects escalate but never repeat: engaging level 2 runs the cancel effect once; escalating to 3 later runs only the flatten, not the cancel again. Each effect's outcome — success or failure — lands in the audit log either way, and a failed effect does *not* disarm the kill. A kill switch that fails to arm because the broker's cancel endpoint flapped at the worst possible moment is worse than useless; the state arms regardless, and the audit log records what didn't happen so a human can finish the job.

Third, level 4 revokes the broker API keys. This is the belt-and-suspenders that makes FULL_STOP worthy of the name: even if some code path bypasses the `check()` gate — a bug, a second executor someone forgot about, a compromised process — the credentials it would trade with no longer work. Re-arming after a full stop is therefore an operational event, not just a method call: new keys must be issued, which is one more reason the re-arm policy in this chapter is strict.

## Scoped kills: halt the desk, not the firm

The four levels are global by default — and global is a blunt instrument. When WealthForge's dividend-capture agent looped at 02:47, the momentum desk was trading perfectly good signals; a firm-wide halt would have punished the innocent desk for the guilty one's bug. So a kill can carry a scope — `engage` takes it as a parameter:

```python
    def engage(
        self,
        level: KillLevel | int,
        sessions: list[OperatorSession],
        reason: str,
        scope=None,
    ) -> dict:
        """Arm a kill level. Level 4 needs two DISTINCT verified operator
        sessions — never raw strings. ``scope`` narrows the kill to one
        tenant or strategy; None means the whole firm.

        Side effects (cancel opens, flatten, revoke keys) run once per
        (scope, effect), in escalating order, and their outcomes land in
        the audit log. A failed effect does NOT disarm the kill — the
        state arms regardless, because a kill switch that fails to arm
        when the broker's cancel endpoint flaps is worse than useless.
        Effect functions receive the scope so they can target precisely.
        """
```

The semantics are deliberately narrow. A global kill governs every action. A scoped kill governs only actions carrying the same scope — `check("submit", scope=("tenant", "harbor"))` consults harbor's kill and the global kill, never beacon's. A scoped kill never leaks into unscoped actions either: the global submit path does not inherit a tenant's pause. Scopes compose: disarming the global kill leaves the scoped one armed, and each scope's side effects run once, targeted — the cancel effect receives the scope so it pulls harbor's opens, not the firm's.

One judgment call to make explicit: the module allows a scoped FULL_STOP, but revoking broker API keys is rarely tenant-scoped in practice, because most desks share key infrastructure. The scope is for the kill levels; your key architecture decides whether level 4 means anything scoped at all. Don't arm a scoped full stop and assume the keys are scoped too — verify it, or keep level 4 global.

## The dead-man's heartbeat

The heartbeat is the mechanism that handles the third failure mode: the supervisor is dead. The design is deliberately primitive:

- A supervisor process — separate from the agent, separate from the executor — calls `beat()` every few seconds.
- The executor's submit path calls `killswitch.check("submit")` **before** touching the ledger. The check requires a heartbeat fresher than the window (30 seconds default).
- No beat, or a beat older than the window, and the submit is refused with `HeartbeatStale`.

Why a heartbeat instead of a health check? Because a health check asks the agent "are you okay?" and the 02:47 agent would have answered "yes." The heartbeat asks a different question: "is there a responsible process *still alive and still watching*?" The supervisor doesn't attest to the agent's sanity — it can't, no local check can detect the stale-cache loop — it attests to its own continued existence and attention. When it goes silent, the system doesn't conclude the agent is broken. It concludes *nobody is watching*, and the fail-closed default takes over.

Two engineering details matter. First, the switch **boots armed-by-default**: before the first beat, every submit is refused. There is no window at startup where trading runs unmonitored while the supervisor "gets around to" its first beat. Second, the check runs before the write-ahead ledger row is created. A refused submit must leave no phantom `submitted` row behind — the ledger records what the system *did*, and a kill-switch refusal is not something the system did, it's something the system *declined to do*. (The refusal itself is visible in the executor's logs and, for kills, in the audit log.)

Heartbeat window sizing is a real tradeoff, and Exercise 4 makes you do the math: too short and a supervisor GC pause causes flapping halts; too long and a dead supervisor lets the runaway trade for the whole window. For a 1-minute-bar day-trading loop, 30 seconds bounds the damage to half a bar while tolerating ordinary scheduling jitter.

A third detail, and the subtlest: the check-then-call gap. `check("submit")` runs before the ledger write — but the broker network call happens after. In an async executor, the kill can engage in that gap: the gate was green, the thread yielded, and the order hits the broker after the halt. This is the classic time-of-check to time-of-use (TOCTOU) race, and no amount of early checking fixes it, because the gap is structural.

The fix is to wrap the actual network client. `killswitch.guarded(broker)` returns a broker that re-checks the gate at the last possible instant — immediately before the wire call. The early check stays (it keeps refused submits out of the ledger); the wrapper is defense in depth at the wire. Reconcile reads (`lookup`) pass through ungated: truth-seeking is never an effect. The test suite replays the race both ways — the naive client sends after the kill engages (the bug, documented), the guarded client refuses (the fix, proven).

## Two-person control

Level 4 requires two distinct VERIFIED operator sessions. The word "verified" is doing the heavy lifting, and it was earned the hard way: the first draft of this chapter's module accepted a list of credential *strings* — `engage(FULL_STOP, ["admin-ruth", "admin-sam"], ...)`. A single attacker with execution-plane access can type any two names. That is not two-person control; it is two-*string* control, API theater with a checksum.

The module now binds identities cryptographically. `OperatorRegistry` issues HMAC-signed `OperatorSession` objects — the same discipline as the Ch 6 tenant tokens: signature, expiry, registration, role, and revocation re-verified on every call. Raw strings are rejected outright, with an error message that says why. `issue()` is the trusted bootstrap's tool; in production, sessions are minted at the ingress gateway behind real authentication, and the registry here is the stand-in for that gateway. A demoted admin's session dies with the old rank. A revoked operator's session dies on the very next call.

The rule itself is the two-person rule from nuclear command and aviation, applied to trading infrastructure, and it exists for two reasons:

1. **Panic.** At 3am, watching a portfolio go vertical, one person's judgment is at its worst. Requiring a second credential forces a 60-second conversation — "confirm you see what I see" — that has saved more money than any risk model.
2. **Compromise.** A single stolen credential must not be sufficient to freeze (or, more importantly, to *threaten to unfreeze*) the desk. And the re-arm side mirrors it: a kill engaged at admin rank needs two admins to lift.

Note what two-person control does *not* require: the two operators don't need to agree on the reason, and they don't need equal rank. The mechanism checks *distinctness*, not consensus. Consensus is a meeting; distinctness is a checksum on the decision.

Levels 1–3 stay single-operator by design — the cheap responses must stay cheap — but the module marks the one-line hardening for production desks that want FLATTEN_HALT restricted to risk-officer rank and above. Know where your line is; the code shows you exactly where to draw it.

## Hard risk limits: the machine that stops you

Some kills shouldn't wait for a human. The WealthForge desk rule is a **3% daily drawdown halt**: if the portfolio falls 3% from its session peak, trading stops and positions flatten, automatically, no meeting required. `RiskMonitor` implements it:

- `record_equity(value)` tracks the running peak (reset each session in production).
- `check(killswitch)` engages FLATTEN_HALT the moment drawdown breaches the limit, with the breach arithmetic in the reason string.

The authority semantics are the interesting part. The monitor engages as `risk-monitor`, a system identity ranked as risk-officer — which means **only a human admin can re-arm afterwards**. The machine that stopped you does not get to restart you on its own say-so. An automated halt is a statement that something is wrong enough to need human eyes; letting the same automation clear itself would make the halt advisory. The re-arm rule from the next section enforces this mechanically: disarm requires strictly greater authority than the engager, and the monitor sits at rank 2.

## Chaos drills: kill it on purpose, on schedule

An untested kill switch is a rumor. The test suite for this chapter (`code/ch11/test_killswitch.py`, 47 tests) is written as drills, and three of them deserve attention because they pin the subtlest contracts:

**Drill 1: kill during an open fill.** The executor has submitted, the broker has *accepted* (the `open` state from Ch 10 — the most dangerous moment, a live order with no fill yet), and the operator engages CANCEL_OPEN. The wired cancel effect pulls the open order exactly once. A subsequent submit is refused *before* any ledger mutation — no phantom row. And `reconcile()` still works under the kill, because truth-seeking is not an effect. The ledger afterwards shows exactly what happened: submitted → open → cancelled, with the kill's audit entry alongside.

**Drill 2: kill during the reconcile sweep.** The Ch 10 end-of-day sweep is mid-flight when FULL_STOP engages. The sweep continues — every key resolves against broker truth — because reconcile is read-only and the kill gates effects, not knowledge. When the sweep finishes, there are no unknown states and no new submits.

**Drill 3: the real ledger, the real race.** Two drills run against the actual Ch 10 `Ledger` (SQLite) and `ActionExecutor` — not the `FakeExecutor` stand-in from the earlier drills. The first proves a refused submit writes no phantom row to the production ledger. The second replays the TOCTOU race: the early check passes, the kill engages, the guarded wrapper refuses at the wire, and the honest `submitted` row is left for the next sweep to resolve — never guessed.

An honest caveat about all of these drills: they prove logic, ordering, and ledger hygiene. They do not prove graceful degradation under live network conditions — timeouts, half-open connections, broker-side partial fills. The fakes stand in for the network, and a fake that degrades gracefully proves the fake degrades gracefully. Production adds network fault injection to the game day: a proxy that drops packets on command, a broker sandbox that half-fails. The unit drills earn you the right to run the game day; they are not the game day.

Run the drills on a schedule, not just in CI. The industry term is a *game day*: once a quarter, someone the desk trusts picks a time, engages each level against the paper environment, and verifies the ledger afterwards. The kill switch you test quarterly is infrastructure. The one you don't is a comment.

## Re-arming: who watches the re-armer

Stopping is the easy half. The dangerous half is starting again, because every re-arm is a claim — "the cause is found, the fix is in, it's safe" — and claims need both authority and evidence. The policy:

1. **Strictly greater authority than the engager — with one absolute exception.** An operator's pause is lifted by a risk-officer or admin. The monitor's automated halt is lifted by an admin. Authority to restart must always exceed the authority that stopped — never equal, never less. EXCEPT: a FULL_STOP always requires two distinct verified admins to lift, *regardless of who engaged it*. The first draft had a hole here: two rank-1 operators engaging a full stop could be undone by a single rank-2 risk officer, because rank 2 is "strictly greater" than rank 1. A full stop is a full stop. Two admins, no exceptions, no rank arithmetic.
2. **A written reason, or it doesn't happen.** The `disarm()` call with an empty reason is rejected, and the kill stays armed. The reason is appended to the audit log verbatim.
3. **The audit log is append-only.** Every engage and disarm — who, when, what level, what reason, what the side effects did — lands in a log the caller receives as copies, so no consumer can rewrite history. This log feeds the evidence ledger (Ch 14) and becomes compliance evidence (Ch 19): when the auditor asks "who stopped trading on September 11th and why," the answer is a row, not a memory.

Notice the recursion the policy avoids: there is no "emergency re-arm" override, no break-glass that bypasses the authority check. A break-glass that bypasses the check is just a second, unguarded re-arm path, and attackers — and panicked operators — always find the unguarded path first. If the situation is urgent, escalate to someone with the authority. That *is* the fast path.

## The code: `killswitch.py`

The full module is `code/ch11/killswitch.py` (stdlib only; ~650 lines). The core is the gate — everything else is authority bookkeeping around it:

```python
    def check(self, action: str, scope=None) -> None:
        """Gate every effect. Actions: 'submit', 'cancel', 'reconcile', 'read'.

        ``scope`` is the action's scope — ("tenant", id) or ("strategy",
        id). A global kill applies to every action; a scoped kill applies
        only to actions carrying the same scope.

        reconcile/read always pass — freezing is not resolving. cancel
        passes at levels 1-3 (it is the cleanup mechanism) and freezes
        only at FULL_STOP. submit requires no armed kill AND a fresh
        heartbeat, checked in that order.
        """
        _check_scope(scope)
        level = self.level_for(scope)
        if action in ("read", "reconcile"):
            return None
        if action == "cancel":
            if level >= KillLevel.FULL_STOP:
                raise HaltedError(
                    f"cancel refused: {level.name} armed: "
                    f"{self._describe_applicable(scope)}"
                )
            return None
        if action == "submit":
            if level >= KillLevel.PAUSE_INTENTS:
                raise HaltedError(
                    f"submit refused: kill {level.name} armed: "
                    f"{self._describe_applicable(scope)}"
                )
            if not self._heartbeat_fresh():
                raise HeartbeatStale(
                    "submit refused: supervisor heartbeat stale or missing "
                    f"(window {self._window}s) — trading stays dead until "
                    "the supervisor beats again"
                )
            return None
        raise KillAuthError(f"unknown action: {action!r}")
```

And the binding into the Ch 10 executor has two positions with a strict division of labor — the early check *before* the write-ahead row, and the wrapper at the wire:

```python
    def guarded(self, broker):
        """Wrap the broker client so the gate is consulted at send time.

        A ``check()`` before the ledger write keeps refused submits out of
        the ledger — but between that check and the wire call, the kill
        can engage. This wrapper re-checks ``submit`` at the last possible
        instant, immediately before the broker is touched. ``lookup`` is
        read-only truth and is never gated, even at FULL_STOP.
        """
        return GuardedBroker(self, broker)
```

The wrapper it returns re-checks the gate at the last possible instant:

```python
class GuardedBroker:
    """The kill switch wrapped around the actual broker client.

    The caller's early ``check("submit")`` (before the ledger write) keeps
    refused submits out of the ledger — but the kill can engage in the gap
    between that check and the wire call. This wrapper closes the TOCTOU
    window: the gate is consulted at the last possible instant, immediately
    before the broker is touched. ``lookup`` is read-only truth-seeking
    and is never gated, even at FULL_STOP.
    """

    def __init__(self, killswitch: KillSwitch, broker):
        self._kill = killswitch
        self._broker = broker

    def __call__(self, order: dict, timeout=None):
        self._kill.check("submit")  # at send time — the TOCTOU fix
        return self._broker(order, timeout)

    def lookup(self, key: str):
        return self._broker.lookup(key)  # reconcile reads: never gated
```

The `RiskMonitor` tracks the peak, breaches at 3%, and engages as the system identity — holding a verified `OperatorSession` for `risk-monitor`, issued by the registry at construction. The `OperatorRegistry` issues and re-verifies those sessions (HMAC-signed, the Ch 6 discipline); in production the sessions are minted at the ingress gateway behind real authentication, which is why the kill switch takes the registry as a constructor argument rather than hardcoding names — the authority source is a dependency, not a constant.

## Worked example: the 02:47 loop, replayed

The test suite replays the opening scenario against the module with a fake clock. Timeline:

- **T+0:00** — Supervisor beats. Heartbeat fresh. Five paper orders submit normally.
- **T+0:35** — Signal cache freezes the ex-div flag. The strategy re-fires every minute; the executor keeps submitting. All health checks green.
- **T+0:41** — `RiskMonitor.record_equity` sees the portfolio 3.1% off its peak. `check()` engages FLATTEN_HALT as `risk-monitor`: open orders cancelled, 4 positions flattened, reason string carries the breach arithmetic. Submits now refuse.
- **T+1:05** — The on-call operator, seeing the halt, escalates to FULL_STOP with a second operator's verified session (two sessions, not two strings): broker API keys revoked, state frozen. Reconcile still runs — the ledger resolves every open row against broker truth.
- **T+1:20** — A risk-officer tries to re-arm: rejected, not strictly above the monitor's rank, and the full stop needs two admins anyway.
- **T+2:30** — Root cause found (stale cache TTL), fix verified on paper. Two admins disarm with the written reason. The audit log holds the complete story: engage, effects, refused re-arm, disarm — six entries, no gaps.

Run it: `python3 -m pytest code/ch11/ -q` → **47 passed**.

FIG 11.1 — Kill Switch Architecture (see `figs/ch11-figspec.md` for the full layout spec: supervisor heartbeat, early gate + guarded-broker send-time gate, verified two-person engage, scoped kills, and the audit trail into the evidence ledger).

## What this fixes

It makes "stop" a property of the infrastructure rather than a request to the agent: graduated levels keep the cheap response cheap, the dead-man's heartbeat fails closed when the supervisor dies, two-person control protects the full stop from panic and single-credential compromise, hard risk limits halt the desk without waiting for a human, chaos drills prove the switch works before the emergency, and the re-arm policy guarantees that restarting is always a more deliberate act than stopping.

## Exercises

1. **Per-tenant heartbeats.** Extend `KillSwitch` so `check("submit", tenant_id=...)` enforces a separate heartbeat window per tenant (Ch 6). Write a test where tenant A's stale heartbeat blocks only A's submits while tenant B, whose supervisor is healthy, keeps trading. In three sentences, argue whether a *global* heartbeat (one dead supervisor stops everyone) or per-tenant is the safer default for a 100-tenant paper-trading desk.
2. **Kill during `await_fill`.** Write a chaos drill where the kill engages *between* two `lookup()` polls of Ch 10's `await_fill()` loop. Assert the loop exits without submitting, the ledger row is left `open` (not forced terminal), and the next scheduled sweep resolves it. This is the poll-loop analogue of Drill 2 — the in-flight transition must degrade to "unknown, reconcilable," never to a guess.
3. **Kill-gating the MCP server.** Your Ch 7 MCP server exposes tools to the agent. Add a kill gate to `tools/call` so a level-2 kill refuses tool *invocation* but still serves `tools/list`. Justify the split in one paragraph: why is discovery read-only (like reconcile) while invocation is an effect (like submit)?
4. **Size the heartbeat window.** A 1-second window flaps on supervisor GC pauses; a 10-minute window lets a dead supervisor's runaway trade for 10 minutes. For a 1-minute-bar day-trading loop with a 5-second supervisor beat interval, compute the worst-case damage window and the false-halt probability under a 200ms scheduling jitter, then defend your chosen window in numbers.
5. **The re-arm reason rubric.** The audit log requires a written reason, but the module accepts any non-empty string — "looks fine now" passes. Draft a four-point rubric for an acceptable re-arm reason (root cause, evidence, what changed, who reviewed), then argue both sides: should the *machine* enforce the rubric (a judge scoring the reason), or is reason-quality inherently a human accountability artifact that the machine should only preserve?
