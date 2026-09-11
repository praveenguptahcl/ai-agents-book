# Glossary

*Book jargon → industry vocabulary. One table per theme. When the book's term has no standard industry equivalent, the mapping column says **book coinage** rather than forcing one.*

> **House coinage.** This book deliberately coins exactly one distinction and carries it everywhere: **capability vs authority** — what an agent *can* do versus what it is *allowed* to do. Everything else maps to industry vocabulary. Where a mapping is uncertain or vendor-dependent, the row says so.

## 1. The loop and intent

| Book term | Industry vocabulary | Definition | Defined |
|---|---|---|---|
| ODAV (Observe–Decide–Act–Verify) | Sense–plan–act loop; MAPE-K (monitor-analyze-plan-execute over knowledge) | The book's operating loop: every agent turn is a four-stage cycle ending in verification, not a fire-and-forget act. | Ch 2 |
| Observe problem | Context management; perception pipeline | The constraint that an agent can never see the whole world — observations arrive budgeted, compacted, and possibly stale, and their provenance must be tracked. | Ch 2 |
| Decide | Planning / policy | The stage that converts observations into a commitment to a course of action — planning without theater: the decision is the thing that can be reviewed. | Ch 2 |
| Act | Effectors; action execution | The stage that changes the world or the agent's state; always through a contracted, authorized tool call. | Ch 2 |
| Verify | Closed-loop verification; test-after-act | A loop *stage*, not a phase: targeted observation that measures whether the act achieved the decided outcome, with error fed back into the next Observe. | Ch 2 |
| Least-agentic ladder | Autonomy levels (cf. SAE levels; "levels of automation") | The discipline of choosing the *least* autonomous system that reliably works: deterministic workflow → single agent → multi-agent → human — in that order. | Ch 2 |
| Intent | Mission / objective function; goal specification | What the principal actually wants, expressed as machine-checkable constraints — not the prompt's vibe. The thesis spine of the whole book. | Ch 3 |
| System intent | System prompt + policy config; alignment specification | The durable, versioned statement of what the agent is for, what it may never do, and what it must do — implemented as config, not prose. | Ch 3 |
| Memory-write policy | Data retention policy (scoped to agent memory) | The system-intent rule for what the agent may persist across turns: what gets written, what gets forgotten, and who can change the rule. | Ch 3 |
| The ritual | Pre-flight checklist; runbook discipline | The Maya pattern: a fixed, reviewable pre-action checklist that must complete before an agent acts on anything consequential. | Ch 1 |

## 2. Identity, authority, capability

| Book term | Industry vocabulary | Definition | Defined |
|---|---|---|---|
| **Capability vs authority** | **House coinage** — nearest neighbors: permissions vs privileges; POSIX capabilities vs ACLs | *Capability*: what the agent can technically do (the tool exists, the key works). *Authority*: what it is permitted to do (the policy allows it). A gap between the two is a vulnerability by definition. | Ch 1, Ch 6 |
| Tenant | Tenant (multi-tenancy); security principal boundary | The isolation unit: one customer's data, sessions, keys, and evidence. Nothing crosses a tenant boundary without an explicit, logged grant. | Ch 6 |
| Tenant session | Authenticated session; security context | The runtime object binding an identity to a tenant for the duration of a task — every tool call, evidence write, and approval is stamped with it. | Ch 6 |
| Scope attenuation | Principle of least privilege; scope reduction (OAuth scopes) | Shrinking a credential's authority as it moves downstream: the orchestrator's broad grant becomes the worker's narrow one. Enforced, not advised. | Ch 8 |
| Dual scope attenuation | (Book coinage) | Attenuation applied on *both* axes: the sub-agent gets a narrower tenant scope *and* a narrower action scope than its parent. | Ch 8 |
| Tool contract | Interface contract; API schema + pre/postconditions | The Pydantic-validated declaration of what a tool accepts, returns, and guarantees — the trust boundary between agent and tool. | Ch 4 |
| Trusted description | Allow-listed metadata; signed manifest (when signed) | The tool description the agent is allowed to see — curated by the platform, not by the tool author. Tool-supplied text is data, never instruction. | Ch 4 |
| Strict schema | Strict JSON Schema / Pydantic `strict=True` | A schema that rejects coercion: `"1.7"` is not `1.7`, `"true"` is not `true`. The erratic-LLM fixture in Lab 2 exists to prove why. | Ch 4, Ch 5 |
| Egress filter | Egress filtering; DLP (data-loss prevention) | The outbound gate on tool results: secrets, private keys, and exfiltration markers are stripped or blocked before they reach the agent or the wire. | Ch 12 |

## 3. Evidence and verification

| Book term | Industry vocabulary | Definition | Defined |
|---|---|---|---|
| Evidence spine | Tamper-evident audit log; append-only ledger | The HMAC-chained, ordered record of every observation, decision, act, and verification — the one artifact the auditor trusts. | Ch 9 |
| Evidence routing | Observability pipeline; log routing | The mechanism that gets every event to the spine in order, with backpressure, exactly-once semantics, and no silent drops. | Ch 9, Ch 14 |
| TraceWriter | Structured logger; span exporter | The Ch 9 component that writes ordered evidence records; backpressure-safe so a flood of events never reorders or loses the trail. | Ch 9 |
| Claim ledger | Citation graph; provenance tracking | The record linking every factual claim in an agent's output to the retrieved span it came from — retrieval without a ledger is hearsay. | Ch 15 |
| PENDING | Unknown / indeterminate state; async acknowledgment | The honest third state of an action: neither success nor failure — the request was sent, the outcome is not yet known. Papered over nowhere. | Ch 2, Ch 10 |
| Outcome-unknown | Ambiguous commit; "I don't know what happened" | The most expensive sentence in production: the ledger says sent, the broker is silent. Handled by the reconciliation script, never by retry-and-hope. | Ch 14 |
| Reconciliation | Settlement; state convergence | The process that converges the agent's ledger with the world's actual state after an outcome-unknown — the desk's settlement discipline. | Ch 2, Ch 10 |
| Write-ahead (WAL) | Write-ahead log (databases) | The rule that the intent is recorded *before* any state mutation — so a crash never leaves an unexplainable world. | Ch 6, Ch 10 |
| Idempotency | Idempotent operations (HTTP PUT semantics; idempotency keys) | Retrying an action produces the same effect as doing it once — the property that makes reconciliation safe. | Ch 10 |

## 4. Action, safety, operations

| Book term | Industry vocabulary | Definition | Defined |
|---|---|---|---|
| Action plane | Execution layer; actuation plane | The machinery that turns decided intentions into world-effects — intents in, verified outcomes out, with the ledger in between. | Ch 10 |
| Intent (trading) | Order intent; signal | A strategy emits *intentions* (symbol, direction, size, confidence) — never orders. The broker turns intentions into orders. | Ch 10 |
| Kill switch | Circuit breaker; emergency stop; kill chain | The mechanism that halts agent action globally (global kill) or per-tenant (scoped kill) — tested, two-admin, and faster than the thing it's stopping. | Ch 11 |
| Scoped kill | Bulkhead (resilience patterns); blast-radius containment | A kill switch that isolates one desk/tenant while the rest keep running — the Ch 6 tenant boundary made operational. | Ch 11 |
| Two-admin rule | Four-eyes principle; dual control | No single person can arm, trip, or lift a kill switch alone — lifting requires two independent admins. | Ch 11 |
| Dead-man's switch | Dead man's switch; watchdog timer | The kill switch's failsafe: if the agent stops proving it's alive, everything halts by default. | Ch 11 |
| Heartbeat / lease | Health check; lease (distributed systems) | The periodic proof-of-life that keeps an agent's authority alive; a missed heartbeat revokes the lease. | Ch 11, Ch 14 |
| Fencing token | Fencing token (distributed locking) | A monotonically increasing token that lets a resource reject commands from a superseded agent — the old leader's orders die at the gate. | Ch 14 |
| Checkpoint | Checkpointing; snapshot | The durable record of an agent's progress, so a restarted agent resumes from evidence instead of re-doing (or re-breaking) the world. | Ch 14 |
| Sandbox | Sandbox; isolated execution environment | The confined process/container where untrusted code runs: no network by default, resource limits, no persistent identity. | Ch 13 |
| Network boundary | Egress proxy; network policy; firewall | The deny-by-default network layer around the sandbox: every destination allow-listed, every redirect re-checked, DNS resolved then verified. | Ch 13 |
| SSRF | Server-side request forgery (OWASP) | The attack the network boundary exists to stop: the agent tricked into making the *platform's* network calls on the attacker's behalf. | Ch 13 |
| TOCTOU | Time-of-check / time-of-use (classic race) | The residual the honest chapter admits: DNS verified at check time can change by use time — named, bounded, not hand-waved. | Ch 13 |
| Patch authority | Code-review gate; commit signing (spirit) | The separation in the sandbox: running bash is not the authority to apply a patch — diffs are applied exactly, reviewed, confined to the worktree. | Ch 13 |
| Prompt injection | Prompt injection (direct) | Attacker instructions smuggled into the agent's input context, treated as data but executed as instruction. | Ch 12 |
| Indirect injection | Indirect prompt injection | The injection arrives through a *tool result* — a webpage, a document, a database row the agent was told to trust. | Ch 12 |
| Output review | Output filtering; response validation | The Ch 12 gate on the way *out*: tool results and agent outputs are scanned for injected instructions and exfiltration before use. | Ch 12 |

## 5. Evaluation and statistics

| Book term | Industry vocabulary | Definition | Defined |
|---|---|---|---|
| Golden set | Golden dataset; benchmark suite | The frozen, curated set of cases the agent must keep passing — versioned, hash-pinned, and never trained on. | Ch 15 |
| Frozen dataset | Immutable dataset; content-addressed fixture | A dataset whose bytes are pinned by hash; any mutation is detected, not silently absorbed. | Ch 15 |
| Contamination | Train-test contamination; data leakage (ML) | The golden set leaking into training or prompts — the eval then measures memory, not capability. | Ch 15 |
| Deterministic grader | Rule-based scorer; unit test (as eval) | A seeded, reproducible grader: same input, same grade, every time — the part of the eval suite that never argues. | Ch 15 |
| LLM-as-judge | Model-based evaluation; LLM judge | A model scoring outputs against a rubric — powerful, biased, and therefore *measured*, never trusted raw. | Ch 15 |
| Cohen's κ (kappa) | Inter-rater reliability (statistics) | Agreement between two judges *corrected for chance* — the statistic that stops "90% agreement" from meaning nothing. | Ch 15 |
| Wilson interval | Wilson score interval (statistics) | The honest confidence interval on a pass rate: 11/12 is not "91.7%", it is 0.646–0.985. | Ch 15 |
| Human review ticket | Escalation queue; human-in-the-loop ticket | Where judge disagreements go: the ticket scores nothing until a human rules — disagreement is routed, not averaged away. | Ch 15 |
| Cost-per-verified-success | (Book coinage; cf. cost-per-acquisition) | Total eval cost divided by *verified* successes — the metric that grades systems anyone can afford to run. Home base: Ch 15. | Ch 15 |
| Walk-forward | Walk-forward validation; rolling-origin evaluation | Temporal validation with an arrow: train on the past, embargo, test on the future, roll — never the reverse. | Ch 16 |
| Embargo | Purge/embargo (cf. López de Prado's purged k-fold) | The mandatory gap between train and test windows, sized for autocorrelation — no information leaks across the boundary. | Ch 16 |
| Lookahead | Lookahead bias; future leakage | The cardinal sin: a decision on bar *t* that peeked at bar *t+1*. The detector perturbs the smuggled future and watches the verdict change. | Ch 16 |
| t+1 rule | (Book's statement of a standard execution constraint) | A signal decided on bar *t* cannot execute before bar *t+1*'s open — the AlphaForge invariant, enforced in code. | Ch 10, Ch 16 |
| Regime-aware folds | Regime-conditional validation | Walk-forward folds cut at market-regime boundaries, not calendar quarters — the test windows respect the phenomenon. | Ch 16 |
| In-sample / out-of-sample | In-sample vs out-of-sample (standard) | Metrics computed on the data the strategy was built on (lies) versus data it never saw (evidence). | Ch 16 |
| HOLD | No-trade / abstain (decision theory) | The honest verdict of a fold that produces nothing tradeable — reported as HOLD, never as zero, never fabricated. | Ch 16 |
| PSR | Probabilistic Sharpe Ratio (Bailey & López de Prado) | The probability the *true* Sharpe beats a benchmark, corrected for sample length, skew, and kurtosis. | Ch 17 |
| DSR | Deflated Sharpe Ratio (Bailey & López de Prado) | PSR evaluated at the multiplicity-adjusted benchmark — the statistic that deflates "best of 250 tries" into "expected." | Ch 17 |
| minTRL | Minimum track-record length (Bailey & López de Prado) | How long a track record must be before a Sharpe estimate means anything — the chapter works it by hand. | Ch 17 |
| Zero-of-250-survive | (Book coinage for the honest-reporting discipline) | The AlphaForge validation result the book holds up as a *success of method*: 39 raw PASS, zero surviving DSR — the harness is honest, not broken. | Ch 17 |

## 6. Multi-agent, frameworks, lifecycle

| Book term | Industry vocabulary | Definition | Defined |
|---|---|---|---|
| Orchestrator | Orchestrator; supervisor agent | The agent that decomposes work, delegates to sub-agents under attenuated scopes, and adjudicates their results — with a depth limit and a cycle guard. | Ch 8 |
| Adjudication | Consensus / voting; result arbitration | How the orchestrator resolves disagreeing sub-agent results — with veto-wins: a safety veto beats any majority. | Ch 8 |
| Veto-wins | Safety veto; fail-closed arbitration | The adjudication rule that a safety objection overrides any number of approvals — one veto stops the act. | Ch 8 |
| Cycle guard | Cycle detection; recursion limit | The orchestrator's defense against delegation loops: A delegates to B delegates to A is refused, not debugged later. | Ch 8 |
| Evidence quarantine | Quarantine; tainted-data isolation | Sub-agent evidence held aside until verified — unverified claims never enter the spine. | Ch 8 |
| Framework adapter | (Book coinage; nearest neighbors: adapter pattern, strangler-fig wrapper) | The trust boundary wrapped around an off-the-shelf framework (LangChain/LlamaIndex/AG2-style): five ordered checks on every call — registration, authority, contract, approval, output review. | Ch 18 |
| Approval ticket | Capability ticket; single-use authorization | A payload-digest-bound, single-use, expiring grant for one high-risk action — a 100-share approval never covers 10,000 shares. | Ch 18 |
| A2A | Agent-to-Agent protocol (A2A 1.0) | The agent-card / message-envelope / task-lifecycle protocol for agents talking to agents — validated, not assumed. | App A |
| MCP | Model Context Protocol | The client/server transport the book's tools speak — implemented runnable in Ch 7, not described from slides. | Ch 7 |
| Off-ramp / decommissioning | Decommissioning; sunsetting; exit plan | The managed end of an agent's life: key revocation, data retention vs deletion, model sunset, exit criteria — "kill the agent, keep the evidence." | Ch 19 |
| Procurement questionnaire | Vendor security assessment; SIG/CAIQ (spirit) | The 16-question, 0/1/2-scored instrument the buyer sends the vendor — mapped to the book's disciplines, with named red flags. | Ch 19 |
| Rubber-stamping | Automation bias; approval fatigue | The failure mode where human approval becomes a checkbox ritual — countered by escalation UX that demands a one-sentence reason, not a click. | Ch 19 |
| Agent Production Standard | Production readiness checklist; launch gate | The book's thesis as an executable gate: no ship until identity, authority, contracts, threat model, eval thresholds, rollback, logging, escalation, and an incident owner are *demonstrated* — front matter one-pager, Appendix E executable. | Front matter, App E |
| Saga / compensating action | Saga pattern; compensating transaction (microservices) | The failure-semantics answer to partial completion: a long action is a sequence of steps, each with a named undo — the catalog lives in Appendix D. | App D |
| REAL / SYNTHETIC | Data provenance labeling | Every bar, fill, and fixture is stamped with its origin: real-anchored market data is REAL, generated fills are SYNTHETIC — "look real" never means fabricated. | Ch 2, Ch 16 |

