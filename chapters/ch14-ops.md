# Chapter 14 — Operating the Evidence Pipeline

Ch 9 built the spine; this chapter runs it.

The distinction matters more than it sounds. Chapter 9 defined the evidence *contract*: the taxonomy of event types, the HMAC-chained audit log, the routing table, the truncation blindspot and its WORM anchor, the session-bound tenant identity. None of that changes here. What changes is the load. A contract proven correct at ten events per second is a different animal at ten thousand — and the animal that eats evidence pipelines in production is not incorrectness, it is *pressure*. Latency pressure, cost pressure, the 3am pressure of a dead worker, the on-call pressure of a broker that has gone quiet. This chapter is about running the spine under pressure without breaking the properties Ch 9 proved.

The running example is the one the desk actually lives: AlphaForge's nightly paper-trading run. Every night at 01:00, the orchestrator (Ch 8) wakes the signal agent, which evaluates a few hundred candidate signals against the day's bars, stages intentions, reconciles fills from the paper broker, and writes roughly twenty thousand evidence entries before the opening bell. It has been doing this for months. Tonight, three things will go wrong — the broker's fill feed will go quiet at 2:14am, the flagship model provider will have an outage at 2:40am, and the worker holding the run's lease will die at 3:07am — and the run will still be reconcilable by breakfast. That is the standard. Not "nothing breaks." *Breaks, and the record survives.*

## Traces are evidence, not logs

Before the machinery, the mental model — because production teams routinely get this wrong, and the mistake is expensive.

*Monitoring* answers "is the system healthy?" with aggregates: error rates, latencies, queue depths. *Observability* answers "why did this happen?" with the ability to reconstruct a specific decision's full context. For agents, the second question is the load-bearing one, and it has a property that ordinary observability does not: **the trace is evidence**. A log line helps you debug. An evidence entry settles a dispute — with the auditor, with the counterparty, with the agent itself when it confidently explains that it "never issued such an order" (Ch 9's 4:07 PM). That means traces inherit the contract's properties: ordered, attributable, tamper-evident, never silently dropped. A tracing system that drops spans under load is a logging system with ambitions. An *evidence* pipeline that drops entries under load is a safety violation wearing an infrastructure costume.

This is why the writer is async and why the async-ness is disciplined rather than convenient. The agent loop must not block on disk or network for every entry — a trading agent that waits 40ms per evidence write emits 500 entries a second at the cost of its own decision latency. So entries go to a bounded queue drained by a consumer thread. But "async" is where evidence pipelines go to lose things, and every design decision in `TraceWriter` exists to close one specific way of losing them:

- **Ordering under concurrency.** Eight strategy threads emit simultaneously. The audit log's hash chain (Ch 9) is only meaningful if entries arrive in submission order — a chain of out-of-order entries is still tamper-evident, but forensic reconstruction ("what did the agent know at 13:41:24?") becomes guesswork. Sequence numbers are assigned under a lock at submit time, and a *single* consumer preserves FIFO order into the router. One consumer is a throughput ceiling you can measure; out-of-order evidence is a correctness hole you cannot.
- **Backpressure, not drops.** The queue is bounded. When it fills, `submit()` *blocks* — the agent pauses — instead of dropping the entry. Read that twice, because it inverts the usual instinct. The usual instinct says the agent is the important thing and the telemetry is expendable. The evidence discipline says the opposite: **an agent that outruns its evidence is an agent whose actions are unverifiable**, and unverifiable actions are exactly what the kill switches (Ch 11) exist to stop. Pausing the agent under evidence pressure is not a performance bug; it is the system refusing to act without a witness. The pause is observable — `stats()` counts `backpressure_events` — so it shows up on the SLO dashboard instead of hiding in a dropped-spans counter nobody reads.
- **No silent loss, ever.** If the consumer thread dies — the router raises, the disk fills, the process is being OOM-killed — `submit()` raises `EvidenceWriterDown` instead of accepting entries into a void. Evidence loss is a safety event, and safety events are loud. The test suite pins this: a poisoned entry marks the writer failed, and every subsequent submit raises. The agent halts unverified rather than running unwitnessed.
- **Flush on shutdown.** `close()` drains the queue before stopping the consumer, and refuses to exit quietly if the drain fails. The 3am worker death in our running example is a *process* death, not a clean shutdown — which is why checkpoints and the ledger exist (see "Durable runs"). But clean shutdowns must not leak evidence either, and the context-manager protocol makes the disciplined path the default path.

The core of the module — the producer's contract with the agent loop, and the consumer that keeps it:

<!-- listing: trace_writer.py -->
```python
    def submit(self, session, event_type: str, payload: dict) -> int:
        """Queue one evidence entry. Returns the submission sequence number.

        Blocks (pauses the caller) when the queue is full — backpressure.
        Raises EvidenceWriterDown if the consumer thread has died: we refuse
        to accept evidence we cannot emit.
        """
        if self._failed is not None:
            raise EvidenceWriterDown(
                f"consumer thread died: {self._failed!r}")
        with self._seq_lock:
            seq = self._next_seq
            self._next_seq += 1
            # The put is INSIDE the sequence lock: insertion order matches
            # sequence-acquisition order, so the single consumer's FIFO
            # read is the submission order. Outside the lock, a thread
            # holding an earlier sequence could be preempted and lose the
            # queue race to a later one — out-of-order evidence, recorded
            # permanently. (The cost: a full queue holds this lock for up
            # to put_timeout. That is the backpressure working as designed:
            # nobody submits while the agent is paused.)
            try:
                self._queue.put((seq, session, event_type, dict(payload or {})),
                                block=True, timeout=self._put_timeout)
            except queue.Full:
                # A full queue past put_timeout means the consumer is
                # wedged; the agent must not proceed unverified. Loud
                # failure, not silent loss.
                with self._stats_lock:
                    self._backpressure_events += 1
                raise EvidenceWriterDown(
                    f"evidence queue full for {self._put_timeout}s; refusing to "
                    f"run unverified")
        with self._stats_lock:
            self._submitted += 1
        return seq
```

<!-- listing: trace_writer.py -->
```python
    def _drain(self) -> None:
        """Single consumer: preserves submission order into the router."""
        while True:
            item = self._queue.get()
            if item is None:  # the shutdown sentinel
                self._queue.task_done()
                return
            seq, session, event_type, payload = item
            try:
                self._router.emit(session, event_type, payload)
            except BaseException as exc:  # noqa: BLE001 — must not kill the loop silently
                # A poisoned entry (or a dead router) is a safety event.
                # Mark the writer failed so future submits raise loudly;
                # the entries already queued stay queued for inspection.
                self._failed = exc
                self._queue.task_done()
                return
            with self._stats_lock:
                self._emitted += 1
            self._queue.task_done()
```

<!-- listing: trace_writer.py -->
```python
    def close(self) -> None:
        """Flush, then stop the consumer. Evidence is never abandoned."""
        if not self.flush():
            raise EvidenceWriterDown(
                "could not drain the evidence queue on shutdown; "
                "refusing to exit with unverified actions outstanding")
        self._queue.put(None)  # shutdown sentinel
        self._consumer.join(timeout=10.0)
```

Note what the writer does *not* do: it does not retry a failed emit. A poisoned entry that raises in the router is not retried, not skipped, and not dropped — the writer halts and the entries already queued stay queued for inspection. Retrying evidence writes is how you get duplicate entries in an HMAC chain (each retry appends a *new* seq — the chain stays valid but the forensic timeline now contains a lie about how many times the event happened). The correct response to a broken evidence path is the same as the correct response to a broken brake line: stop the vehicle, don't pump harder.

## The model gateway: verification has a budget

Chapter 5 made a single provider call disciplined: strict schemas, refusal handling, attempt accounting. Production makes thousands of calls a night across models, providers, and task classes — and every one of them costs money, takes time, and can fail. The gateway is where the *economics* of the operation live, and the economics are a safety property, because **an agent with unbounded token spend has unbounded authority**. A runaway agent that can call the flagship model in a loop is not a cost incident; it is an agent that has escaped every budget the intent (Ch 3) declared. Cost controls belong in the architecture, not in the finance review.

The gateway does four things, in the order the night demands them:

**Routing: the right model for the task class.** Summarizing an earnings call does not need the flagship model; grading a trading thesis against historical conditions does. The route table is data — `{"summarize": "small-1", "grade": "large-1"}` — and unknown task classes fail closed rather than guessing which model should answer. This is the least-agentic ladder (Ch 2) applied to model selection: the smallest capability that reliably does the job. There is a security dividend too: fewer capabilities invoked per task means less to verify at the Verify stage.

**Fallback: providers have outages.** At 2:40am the flagship provider returns errors. The gateway walks an ordered fallback list — grade on `large-1`, degrade to `small-1` — and records which calls were degraded in the ledger. The rule is absolute: *an agent that cannot reach its model degrades to a weaker model or halts; it never degrades to an unverified guess.* The fallback chain is bounded and explicit; "try a different provider" is not a license to try every provider until something answers, because each fallback is a weaker judge of the same question and the ledger must show the degradation.

**Caching: don't pay twice for the same question.** The nightly run asks the same summarization question about the same filing more than once. The cache key is the SHA-256 of the canonical request — and it is namespaced by Ch 3's intent hash. That namespacing is the subtle part: rotate the system's intent (new risk limits, new universe) and every cached answer becomes suspect, because the question was asked by a *different system*. `rotate_intent()` clears the cache; the ledger survives rotation, because money spent is money spent.

**Accounting: every call lands in a ledger.** Providers report usage (as real LLM APIs do); a provider that will not report usage cannot be cost-accounted, and a call that cannot be accounted is refused. Model prices are configuration, and an unpriced model is a fail-closed event, not a zero-cost one. The desk's unit economics — cost per verified signal, cost per evaluated candidate — come out of this ledger, and they are the numbers the capacity plan is built on.

<!-- listing: model_gateway.py -->
```python
    def complete(self, task_class: str, request: dict) -> GatewayResult:
        """One accounted, cached, fallback-capable model call."""
        model = self.route(task_class)
        key = (self._intent_hash, hashlib.sha256(
            _canonical_request(request).encode("utf-8")).hexdigest())
        if key in self._cache:
            hit = self._cache[key]
            return GatewayResult(text=hit.text, model=hit.model,
                                 cached=True, cost_usd=0.0)
        candidates = [model] + self._fallbacks.get(model, [])
        last_outage: ProviderOutage | None = None
        for candidate in candidates:
            provider = self._providers.get(candidate)
            if provider is None:
                continue  # misconfigured fallback entry: skip, don't die
            try:
                result = provider(copy.deepcopy(request))
            except ProviderOutage as exc:
                last_outage = exc
                continue  # try the next fallback
            result = self._check_contract(candidate, result)
            cost = self._price(candidate, result)
            self._ledger.append({
                "task_class": task_class, "model": candidate,
                "tokens_in": result.tokens_in, "tokens_out": result.tokens_out,
                "cost_usd": cost, "fallback": candidate != model,
            })
            answer = GatewayResult(text=result.text, model=candidate,
                                   cached=False, cost_usd=cost)
            self._cache[key] = answer
            return answer
        raise ProviderOutage(
            f"all providers for {model!r} are down: {last_outage!r}")
```

<!-- listing: model_gateway.py -->
```python
    def rotate_intent(self, new_intent_hash: str) -> None:
        """A new system intent invalidates every cached answer.

        The old answers were produced for a different system's questions.
        The ledger survives rotation — money spent is money spent.
        """
        self._intent_hash = new_intent_hash
        self._cache.clear()
```

A note on where this lives: small-vs-large routing and prompt caching are gateway concerns, not provider concerns. Ch 5 is frozen — its `llm_client.py` teaches one disciplined call — and the gateway *consumes* that discipline at fleet scale without re-deriving it. If you are tempted to add retry-with-backoff inside the provider client and fallback inside the gateway, notice the division: the client retries the *same* call against transient faults; the gateway changes *which* model answers. Different decisions, different layers, different ledger entries.

## Durable runs: the 3am death

At 3:07am the worker holding the nightly run's lease dies — kernel panic, OOM-kill, a cloud instance preemption. It had evaluated 120 signals and staged nothing yet. At 3:08am the supervisor notices the missed heartbeat and starts a replacement. The question that decides whether breakfast is calm or catastrophic: **what does the replacement find when it wakes up?**

The naive answer — "it starts over" — is wrong twice. Starting over re-executes the 120 evaluations (wasteful but tolerable) and, worse, risks re-executing the *actions*: if the dead worker had staged orders before dying, a fresh run that cannot tell "staged" from "never attempted" will stage them twice. The correct answer has three parts, and they compose in a strict order: lease, fence, checkpoint.

**The lease: exactly one owner.** A run is owned by exactly one worker at a time, and ownership expires. The lease lives on a monotonic clock — wall clocks lie (Ch 9's dual-clock lesson), and a lease measured in wall time can be extended by an NTP step into immortality. Heartbeats renew; missed heartbeats expire. A second worker may take over an *expired* lease, and only an expired one: taking over a live lease is `LeaseConflict`, not failover, because "helpfully" seizing a run from a worker that is merely slow is how you get two writers.

**The fence: the token is the truth.** Every mutation carries the lease token, and the store rejects any token that is not current. This is the mechanism that makes failover safe rather than merely fast. Consider the race: worker-1's lease expires at 3:07:30; the supervisor starts worker-2 at 3:08:00; but worker-1 wasn't dead, only partitioned — at 3:08:15 it wakes and tries to write its results. Without fencing, you now have two writers and a corrupted run. With fencing, worker-1's token died the moment worker-2 took over, and its writes raise `StaleFenceError`. *The fence token is the only thing standing between "failover" and "two writers."* Note the direction of the safety: it is not that the new worker is trusted — it is that the old worker is *distrusted by default* the instant it is no longer the owner.

<!-- listing: durable.py -->
```python
    def take_over(self, run_id: str, new_owner: str, ttl_s: float) -> str:
        """Seize an EXPIRED lease. The old token dies here — that is the
        fence. Taking over a live lease is LeaseConflict, not failover."""
        now = self._clock()
        current = self._leases.get(run_id)
        if current is not None and current["expires_at"] > now:
            raise LeaseConflict(
                f"run {run_id!r} is still live under {current['owner']!r}; "
                f"refusing to steal it")
        return self.acquire(run_id, new_owner, ttl_s)
```

<!-- listing: durable.py -->
```python
    def _guard(self, run_id: str, token: str) -> dict:
        """The fence: only the current token-holder may mutate."""
        current = self._leases.get(run_id)
        if current is None:
            raise StaleFenceError(f"no lease exists for run {run_id!r}")
        if current["token"] != token:
            raise StaleFenceError(
                f"stale fence token for run {run_id!r}: owned by "
                f"{current['owner']!r}")
        if current["expires_at"] <= self._clock():
            raise StaleFenceError(
                f"lease for run {run_id!r} expired: heartbeat or take over")
        return current
```

**The checkpoint: resume from the ledger, not from scratch.** The worker periodically snapshots its state — *stamped with the evidence-log sequence it had consumed*. That stamp is the elegant part: the checkpoint says "I am current through audit seq 412," and the replacement loads the snapshot, then replays the audit entries after seq 412. It replays the *evidence*, not the *actions* — it learns what the dead worker saw and decided, without re-executing what it did. The ledger (Ch 9's spine) is what makes this possible: resume-from-ledger is the operational payoff of every property Ch 9 proved. A system whose evidence is unordered, unattributed, or silently dropped cannot resume; it can only restart and hope.

<!-- listing: durable.py -->
```python
    def resume(self, new_owner: str, ttl_s: float = 60.0
               ) -> tuple[dict, list[dict]]:
        """Take over (expired lease only) and return (state, new entries).

        ``state`` is the last checkpoint; ``new entries`` are the audit-log
        entries for this tenant with seq > checkpoint seq — the decisions
        the dead worker saw but never checkpointed. The replacement replays
        the *evidence*, not the *actions*.
        """
        self._token = self._leases.take_over(self.run_id, new_owner, ttl_s)
        cp = self._checkpoints.get(self.run_id)
        if cp is None:
            cp = {"state": {}, "through_seq": -1}
        state = copy.deepcopy(cp["state"])
        through = cp["through_seq"]
        entries = [e for e in self._router.audit.read(self._tenant_id)
                   if e["seq"] > through]
        return state, entries
```

One honest limitation, stated plainly: the lease store and checkpoint store in this chapter are in-memory. The *semantics* — expiry on a monotonic clock, fencing on token mismatch, resume keyed to audit seq — are identical over a WAL-backed store, and production keeps them there (Ch 10/Ch 11's SQLite discipline: write-ahead before mutation, so a crashed writer's lease state is itself recoverable). The teaching module isolates the protocol from the persistence; do not mistake the isolation for permission to run leases in process memory in production. A lease that dies with the process is a lease that cannot fence a zombie.

## Production ops: SLOs, attributes, and the 2:14am playbook

With the machinery in place, the operation needs numbers. SLOs for an agent system look different from SLOs for a web service, because the thing being served is *decisions*, and a decision has a verification completeness that a web request does not. The table below is the desk's actual SLO set — example numbers, stated as examples, because your numbers depend on your latency budget and your auditor, but the *rows* are the point: every row is a property from an earlier chapter, made measurable.

| SLO | Target (desk example) | Measures (Ch) |
|---|---|---|
| Evidence lag: submit → audit-log durable | p99 < 250ms | Ch 14 writer |
| Evidence completeness | 100%; any gap is a safety event | Ch 9 + Ch 14 |
| Tool-call latency | p99 < 2s per call | Ch 4/Ch 10 |
| Fill reconciliation lag (broker silent → flagged) | < 60s | Ch 10 sweep |
| Verification completeness: acts with matching verify | 100% before next act on same entity | Ch 2 loop |
| Kill-switch trip → all sends halted | < 5s, desk-wide | Ch 11 |
| Checkpoint interval (durable runs) | ≤ 60s of work lost | Ch 14 durable |
| Cost per verified signal | ≤ $0.40 | Ch 14 gateway |
| Judge agreement (LLM-judge vs goldens) | Cohen's κ ≥ 0.7 | Ch 15 |

Two rows deserve commentary. *Evidence completeness at 100%* looks unmeasurable — how do you count the entries that never arrived? You count them structurally: every act-stage emission is paired with its contract (Ch 4) and its executor record (Ch 10), so a missing evidence entry shows up as an act without a witness, which the reconciliation sweep flags. Completeness is verified by cross-referencing planes, not by trusting one. And *verification completeness* is the ODAV loop (Ch 2) as an SLO: no second act on the same entity until the first act's verify has landed. The loop is not philosophy; it is the row the on-call watches.

**Trace attributes: the OTel contract.** When traces leave the process — to the collector, the dashboard, the auditor's export — they speak OpenTelemetry's GenAI semantic conventions, because the auditor's tools already do. The mapping is mechanical: `gen_ai.system` (provider), `gen_ai.request.model`, `gen_ai.usage.input_tokens` / `gen_ai.usage.output_tokens` (from the gateway ledger), `gen_ai.response.finish_reasons`, plus the book's own attributes the conventions don't cover — `agent.tenant_id` (from the verified session, never the caller's word), `agent.intent_hash` (Ch 3's version stamp, so a trace is attributable to the system that produced it), `agent.evidence_seq` (the Ch 9 seq, so the trace and the audit log join). Convention where the industry has one; house attributes where the book's properties need naming. The glossary rule (blueprint-v2 §2) applies: only "capability vs authority" stays house coinage; everything else maps to industry vocabulary.

**The 2:14am playbook: OUTCOME-UNKNOWN.** This is the incident the whole book has been building toward. The ledger says the order was *sent*; the broker's fill feed has been silent for ninety seconds. Not "failed" — *unknown*. The executor (Ch 10) holds the order in `open` state; the sweep will reconcile it; but the on-call human is awake and needs the exact playbook, because the failure mode that kills desks is not the outage — it is the human doing something creative during the outage. The playbook:

1. **Read, don't act.** Open the trace for the order's evidence seq. Confirm: `tool_call` emitted, `broker_response` absent, sweep status `open`. If the ledger shows no `tool_call`, this is a different incident (the agent never acted — check the writer's `failed` flag).
2. **Check the sweep, not the broker.** The broker's status page is entertainment; the sweep's state machine is ground truth. If the sweep shows the order `open` and retrying within policy, there is nothing to do. *Doing nothing is the playbook's most important step and the hardest one to follow.*
3. **Bounded escalation only.** If the sweep has exhausted its policy (retries spent, still unknown), the playbook authorizes exactly one action: trip the desk-scoped kill switch (Ch 11) to halt *new* sends, and page the broker's support with the order's idempotency key. It does not authorize: resubmitting the order (that is how duplicates are born), editing the ledger (that is how fraud is born), or restarting the agent (that is how the 3am death becomes a 3:05am second death).
4. **Reconcile before resume.** When the feed returns, the sweep reconciles every `open` order against the broker's authoritative state, the evidence log records the resolutions, and only then does the kill switch lift — by two verified operators (Ch 11), not by the on-call alone at 2:47am.

**Capacity planning** is the gateway ledger projected forward: tokens per nightly run, p99 provider latency, cache hit rate, fallback frequency. The desk's capacity plan is one page: last month's ledger totals, this month's projected runs, headroom at 2×. The discipline from Ch 3 applies — the plan is data, versioned with the intent hash, and a run that would exceed planned capacity fails closed at scheduling time rather than discovering the limit at 2:40am during a provider outage.

## The comparative table: the least autonomous system that reliably works

The standing comparative frame (Ch 2, Ch 8, this chapter, Ch 18): for the nightly reconciliation workload, how do the architectures compare?

| Dimension | Deterministic workflow | Single agent | Multi-agent team | Human |
|---|---|---|---|---|
| Reliability | Highest: no model in the loop | High, bounded by one model's judgment | Medium: coordination failure modes (Ch 8) | Medium: fatigue, inconsistency |
| Cost | Lowest: compute only | Moderate: one model's tokens | Highest: N models + coordination | Highest: salary × hours |
| Latency | Lowest: no inference | Moderate: inference per decision | Higher: sequential delegations | Slowest by far |
| Flexibility | Lowest: code changes for new cases | High: new situations handled | Highest: specialization | Highest, with judgment |
| Security | Smallest attack surface | Model-judgment risk, one boundary | Delegation + confused deputy (Ch 8) | Social engineering, error |
| Debuggability | Trivial: replay the code | Trace one model's reasoning | Hardest: cross-agent causality | "Ask them" (unreliable) |
| Human burden | Build once | Supervise + on-call | Supervise + coordinate + on-call | Do the work |

The recurring lesson, now with operating numbers behind it: the deterministic workflow reconciles fills cheaper and more reliably than any agent — so the desk's reconciliation *sweep* is a deterministic workflow (Ch 10), the *signal evaluation* is a single agent (judgment where judgment pays), and the multi-agent team (Ch 8) is reserved for the research pipeline where specialization earns its coordination cost. The least autonomous system that reliably works — and the evidence pipeline is what lets you *prove* which one that is, because every architecture's decisions land in the same audit log, scored by the same graders (Ch 15).

## Handoff

The operation runs: evidence flows under pressure, models are routed and accounted, dead workers are replaced without double-spend, the on-call has a playbook for the unknown. But an operation without grading drifts — costs creep, fallbacks become the norm, the judge that was strict in January is lenient by June because nobody re-ran the goldens. The next chapter builds the graders: deterministic evaluators and LLM judges, agreement statistics, frozen datasets, and the discipline of scoring every change against the same bar. The operation runs; now we score it.

---
*Figure 14.1 — The operating pipeline: agent loop → TraceWriter (bounded queue, backpressure) → EvidenceRouter → audit log / trace sink / eval set; the model gateway (route/fallback/cache/ledger) beside the provider calls; leases, heartbeats, and the checkpoint store under the durable runs. Full specification in `figs/ch14-figspec.md`.*
