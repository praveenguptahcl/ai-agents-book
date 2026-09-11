# Chapter 9 — Evidence Routing

It is 4:07 PM on a Thursday. The paper book shows a 2,000-share short in NVDA that nobody admits to. The strategy log says the signal was flat. The risk gate says it approved nothing. The agent, when asked, produces a confident paragraph explaining that it "never issued such an order" — and large language models are fluent in exactly this kind of confident paragraph, which is why the paragraph is worth nothing.

What settles it is not any participant's story. It is the evidence trail: at 13:41:22, an `intent_record` — strategy `gap-fade-7`, short, confidence 0.81, capital $48,000. At 13:41:23, an `authority_check` — tenant `t-ava`, scope `submit`, allowed. At 13:41:24, a `tool_call` — `submit_order`, args digest `9f2c…`, result `accepted`. At 13:41:31, a `broker_response` — filled, 2,000 shares, $187.42. Four entries, each hash-chained to the previous, each written by infrastructure the agent cannot touch. The agent's paragraph says one thing; the chain says another. The chain wins, because the chain was designed to win: **the agent proposes; the infrastructure records.**

That is this chapter's thesis, and it is the hinge the whole spine turns on. Everything before it — intent, authority, capability, action — *generates* evidence. Everything after it — verification, accountability — *consumes* evidence. This chapter owns the arrow between them: the routing layer that decides what gets recorded, where it goes, who may read it, and how you know nobody rewrote it after the fact.

## The taxonomy: name every kind of evidence or lose it

Evidence that has no name gets no handling. A system that logs "stuff happened" in one undifferentiated stream will, under pressure, discover that the auditor needs one subset, the debugger needs another, and the evaluator needs a third — and that reconstructing those subsets after the fact is the failure mode. So the first act of the evidence layer is definitional: every event the system can emit belongs to exactly one type.

| Event type | Emitted when | Example payload |
|---|---|---|
| `intent_record` | The strategy emits a trading intention (Ch 3) | symbol, side, confidence, capital |
| `authority_check` | A tenant token is verified and a scope checked (Ch 6) | tenant, scope, allow/deny, reason |
| `tool_call` | A tool is invoked under its contract (Ch 4) | tool name, args digest, result summary |
| `broker_response` | The broker answers a submit (Ch 10) | broker_id, status, filled_qty, avg_price |
| `reconcile_event` | The sweep resolves an ambiguous key (Ch 10) | key, prior status, resolution |
| `refusal` | The provider refuses (Ch 5) | category, reason, attempts burned |
| `kill_switch` | A breaker trips or resets (Ch 11) | trigger, scope, operator |

Three properties of this table are load-bearing. First, it is **closed**: the router knows the full vocabulary, and anything outside it is a misconfiguration, not a new feature. Second, payloads carry **digests and summaries, never raw secrets** — the args digest of a tool call proves *which* call it was without embedding the API key that rode along in the headers. Third, the taxonomy is **the contract between the planes**: Ch 10's ledger, Ch 6's audit log, and Ch 5's attempt records all speak these seven types, so evidence composed in one chapter is legible in the next.

## Routing: three consumers, three different needs

One store cannot serve the auditor, the on-call engineer, and the evaluation judge, because they want contradictory things. The auditor wants completeness and immutability — every event, forever, tamper-evident. The on-call engineer wants fidelity and recency — full detail on the last hour, and permission to forget the rest. The judge wants curation — only the events that bear on decision quality, frozen at scoring time. So the router fans every event out to three consumers with different retention and admission rules:

- **The audit log** receives *everything*. Every event type, every tenant, forever. This is the record the compliance chapter (Ch 19) hands to the auditor and the record the 4:07 PM dispute is settled against. Append-only, HMAC-chained, immutable.
- **The trace sink** receives the operational types — `tool_call`, `broker_response`, `reconcile_event`, `kill_switch` — in a bounded ring buffer. Full fidelity, short retention. It exists to answer "what happened at 09:31" during an incident, and then it is allowed to forget. The audit log is the durable record; the trace is the scratch pad.
- **The eval dataset** receives only the curated types — intent, tool calls, broker responses, refusals, kill switches — as frozen snapshots. Deliberately excluded: `authority_check` and `reconcile_event`. The judge scores decisions and outcomes, not the plumbing that verified a token or the sweep that cleaned up a timeout. Admitting plumbing into the eval set is how you get a judge that rewards tidy token handling instead of good trading.

The routing table is data, not code, and it is validated at construction: a table that names a type outside the taxonomy is rejected immediately. Fail fast on config. But at *runtime* — when an event arrives with a type the router doesn't know, because someone shipped a new emitter without updating the router — the rule inverts: **fail closed**. The unknown event is written to the audit log, flagged as anomalous, and dropped from the other two sinks. It is never silently discarded. A dropped event is a hole in the record; a flagged event is evidence of the misconfiguration itself. The system prefers to incriminate its own wiring than to lose a fact.

## Tamper-evidence: the chain that makes lying expensive

An append-only log that anyone can rewrite is a diary, not evidence. The audit log's defense is the hash chain, keyed: each entry stores the HMAC-SHA256 of the previous entry's hash, computed with a secret key injected from the infrastructure — never from source, never in the repo. Every entry commits to the entire history before it. To alter the 13:41:24 `tool_call` you must recompute its MAC — which invalidates the 13:41:31 entry's `prev_hash` — which forces recomputing that MAC — cascading to the head. `verify_chain()` walks the log recomputing MACs and reports the *first* broken sequence number, so tampering is not merely detectable but localizable.

Note the threat model precisely, because this is where audit chapters usually lie by omission. The HMAC promises **tamper-evidence against everyone who does not hold the key**: the insider without infrastructure access, the bug corrupting a row, the "oops" nobody can explain. It does *not* promise anything against the key holder or the infrastructure itself — with the key, the whole chain can be recomputed from genesis, and no hash chain ever invented can prevent that. Key custody is a first-class design decision, not a deployment detail. And a chain nobody verifies is a seatbelt nobody wears: run verification on every log rotation, before every compliance export, and after every incident.

Two details matter. First, the hash commits to the tenant id and event type alongside the payload — re-attributing an entry to another tenant, or re-labeling a `refusal` as a `tool_call`, breaks the chain exactly as surely as editing the payload. Second, two strategies may emit in the same instant, so the append path serializes on a lock: sequence number, previous-hash read, and append are one atomic step. Sequential consistency in a concurrent environment requires a lock at the serialization choke point; without it, two threads read the same length, and one entry's link is orphaned forever.

## What the chain cannot see: truncation

Here is the blindspot, stated plainly because the alternative is a false sense of safety: **a hash chain detects edits, not deletions.** Silently dropping the last ten entries leaves a perfectly valid chain — every remaining link verifies, every MAC recomputes. `verify_chain()` will tell you the log is intact, and it will be telling the truth about the wrong question.

The fix is external anchoring. `checkpoint()` returns the head hash, and the infrastructure writes `(seq, head_hash)` pairs to WORM — write-once, read-many — storage on a schedule: every rotation, every export, every hour. A truncated log still verifies locally, but its head no longer matches the anchor, and that mismatch is the detection. The chain makes lying about the *past* expensive; the anchor makes lying about the *present* visible. Neither works without the other, and the rotation drill in the exercises makes you build both.

Each entry also carries two clocks: `ts` (wall clock, for humans and auditors) and `mono` (`time.monotonic()`, for ordering). Wall clock lies — NTP steps, leap seconds, an operator "fixing" the time — so forensic timelines are reconstructed from `mono`, which cannot step backward. The hash commits to both: rewriting the ordering evidence breaks the chain exactly like rewriting the payload.

## Who watches the watcher

Here is the uncomfortable question: the router decides what gets recorded. Who constrains the router? If the agent can emit arbitrary events, can it flood the audit log with noise, or — worse — emit a forged `authority_check` claiming a scope it was never granted?

The answer is architectural, and it has two parts. First, **the agent holds a narrow capability, not a broad one**: it gets `emit(tenant_id, event_type, payload)` and nothing else. The audit log exposes no public write method — the router calls a private `_append`, and the test suite pins the absence of any other write path. An agent that wants something in the record must ask the router, and the router applies the taxonomy, the routing table, and the tenant binding. The agent can propose evidence; it cannot author it.

Second, **the router validates, it does not trust**. The `authority_check` event is emitted by the authority layer (Ch 6) *about* the agent, not *by* the agent about itself. And the tenant recorded on every entry comes from the session, not from the caller's word: `emit` takes the *verified session object* — in AlphaForge, Ch 6's `TenantSession` — and extracts the tenant id from it. A bare tenant-id string is rejected outright, because a string is a claim and the session is the proof. A compromised intermediate layer holding Ava's session cannot re-label her evidence as Ben's; the binding is `session.tenant_id`, full stop. Note the division of labor, because it is the whole architecture in miniature: the signature check belongs to the authority layer (Ch 6's `require_tenant`, the one choke point that verifies); the router binds the verified identity without re-authenticating it. One choke point per job.

This is the same boundary discipline as every earlier chapter, applied one level up: capability (the agent can call `emit`) is separated from authority (only the router writes the log), exactly as Ch 4 separated the model's dictionaries from the executor's submits.

## Retention and partitioning: whose evidence is it

Two tenants share the AlphaForge process. Tenant Ava's evidence must never be readable by tenant Ben's agent — and per Ch 6's convention, the read path returns *absence* for other tenants' entries rather than an error, because an error would itself leak that the entry exists for someone else. The audit log, trace sink, and eval dataset all enforce tenant-scoped reads with the same rule.

Retention is where the three consumers diverge deliberately. The audit log keeps everything — its whole point is that the 4:07 PM dispute in *2027* can still be settled. The trace sink is a ring buffer: when it fills, the oldest events are evicted, because operational debugging has a short half-life and unbounded memory is a slow leak wearing a helpful mask (Ch 5's `last_attempts` lesson, applied to infrastructure). The eval dataset keeps whatever the evaluation runs need and no more — judge inputs are versioned with the model checkpoint they scored, then archived.

## The code: `evidence.py`

The full module is `code/ch09/evidence.py` (stdlib only: `hashlib`, `hmac`, `json`, `time`, `threading`, `secrets`, `copy`; ~330 lines). The core is the router's `emit` — the single choke point, now bound to the verified session rather than a bare string:

```python
def emit(self, session, event_type: str, payload: dict) -> dict:
    _session_tenant_id(session)  # fail fast: strings are not sessions
    payload = dict(payload or {})
    if event_type not in EVENT_TYPES:
        # Fail closed: unknown evidence is still evidence. Flag it so the
        # misconfiguration shows up in the very log it tried to bypass.
        return self.audit._append(
            session, event_type, payload, flagged=True)
    entry = self.audit._append(session, event_type, payload)
    if event_type in TRACE_TYPES:
        self.trace._record(session, event_type, payload)
    if event_type in EVAL_TYPES:
        self.evalset._record(session, event_type, payload)
    return entry
```

And the audit log's write path — the one the agent can never call — with the lock, the HMAC, the dual clocks, and the serialization fallback:

```python
def _append(self, session, event_type: str, payload: dict,
            flagged: bool = False) -> dict:
    tenant_id = _session_tenant_id(session)
    with self._lock:  # the serialization choke point: seq, prev_hash,
                      # and append are one atomic step
        seq = len(self._entries)
        prev = (self._entries[-1]["entry_hash"] if self._entries
                else self.GENESIS)
        ts = self._clock()
        mono = time.monotonic()
        record = dict(payload or {})
        try:
            entry_hash = self._hash_entry(
                seq, ts, mono, tenant_id, event_type, record, prev)
        except Exception:
            # A payload that cannot be serialized is still evidence — of
            # its own failure. Never silently drop it.
            record = {_SERIALIZATION_FAILED: True,
                      "raw_repr": repr(payload)}
            entry_hash = self._hash_entry(
                seq, ts, mono, tenant_id, event_type, record, prev)
            flagged = True
        entry = {
            "seq": seq,
            "ts": ts,
            "mono": mono,
            "tenant_id": tenant_id,
            "event_type": event_type,
            "payload": record,
            "flagged": flagged,   # True when the router failed an event closed
            "prev_hash": prev,
            "entry_hash": entry_hash,
        }
        self._entries.append(entry)
        return dict(entry)
```

The test suite (`test_evidence.py`, 29 tests) is organized as the failures each test prevents: tampered payloads, tampered hashes, keyless forgery attempts, re-attributed tenants, spoofed tenant strings, concurrent emits, truncated tails, unserializable payloads, direct writes, cross-tenant reads, unknown types, dropped events, unfrozen eval snapshots. Run it:

```bash
build-venv/bin/python -m pytest code/ch09/ -q
```

**FIG 9.1** — "The Evidence Routing Pipeline." Full visual spec: `figs/ch09-figspec.md`.

## What this fixes

It makes the system's memory trustworthy: every action emits typed evidence through a single choke point the agent cannot bypass or edit; the audit log is tamper-evident via HMAC chaining against everyone who does not hold the key; misconfigurations fail closed into flagged audit entries instead of silent holes; tenants see only their own evidence; and the three consumers — auditor, debugger, judge — each get the retention and curation their job requires. When the 4:07 PM dispute arrives, the answer is a chain, not a paragraph.

## Exercises

1. **The flood.** An agent emits 10 million `tool_call` events in a loop. What breaks first — the audit log, the trace sink, or the eval dataset — and what is the correct backpressure response for each? Implement per-tenant rate limiting in `emit` (hint: Ch 6's `RateLimiter`) that sheds load by flagging-and-sampling rather than dropping, and argue in three sentences why sampling preserves evidence value better than truncation.
2. **Rotation drill.** Implement `AuditLog.rotate()` that seals the current log (final `verify_chain()`, exports the head hash) and starts a new chain whose genesis commits to the previous head hash. Prove with a test that tampering with a *rotated-out* segment is still detectable from the live chain.
