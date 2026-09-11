# REBUILD BLUEPRINT v2 — "AI Agents: Systems, Safety, and Practice" (World-Class Edition)
**Date:** 2026-09-11
**Status:** 9 of 23 chapters CLEARED via Gemini Pro Extended review loop (Ch 1, 4, 5, 6, 7, 9, 10, 11, 12). This document reconciles what was actually built against blueprint-v1 and the merged council blueprint (`~/workspace/book-review/rebuild-blueprint.md`), assigns every at-risk topic, and briefs the remaining chapters.
**Supersedes:** `blueprint-v1.md` for all forward drafting. Cleared chapters are frozen except where v2 notes an explicit cross-reference addition.

## Thesis spine (unchanged)
Intent → Authority → Capability → Action → Evidence → Verification → Accountability

## 1. Reconciled chapter list — what the cleared chapters ACTUALLY are

| # | Blueprint-v1 title | As built & cleared | Code artifact (green) |
|---|---|---|---|
| 1 | The Decoupling of Capability and Authority | **Ch 1 — The Agent That Moved Money** (Maya narrative; Harbor copilot pays spoofed vendor $62,400 via threshold-splitting; ends on What may it do? / Who said so? / How would we know?) | none — 3,973 words, 8 scenes |
| 2 | ODAV Loop | NOT YET DRAFTED (brief §3) | none (conceptual) |
| 3 | Defining System Intent | NOT YET DRAFTED (brief §3) | `config_loader.py` |
| 4 | Designing the Agent Tool Contract | **as titled** — Pydantic pre-network validation; notional anchored to stop price; stop-limit drift anchored to stop price; trace_id; 24/24 | `schemas.py` |
| 5 | Provider Integration & Strict Schemas | **as titled** — real OpenAI SDK, pinned model, strict JSON-schema subset, refusal fail-fast, warm-up; 11/11 | `llm_client.py` |
| 6 | State Management and Tenant Isolation | **Ch 6 — Tenant Isolation** (retitled) — HMAC tenant-bound sessions, `submit_as` binds verified session → tenant-scoped credentials, quota from tenant record, token masking; 27/27 | `tenant.py` |
| 7 | MCP Specification | **Ch 7 — MCP: The Protocol, Specified Correctly** — 2026-07-28 spec verified razor-accurate; runnable stdio client+server; fail-closed contracts; trusted-description overrides; isError→ToolExecutionError; 22/22. **Fully absorbs blueprint-v1's Ch 8.** | `mcp_protocol.py`, `mcp_server.py`, `mcp_client.py` |
| 8 | Implementing the MCP Server and Client | **REDEFINED — see verdict below** | `team.py` (new) |
| 9 | Capability via Evidence: Semantic Routing | **Ch 9 — Evidence Routing** (retitled) — evidence taxonomy, 3-consumer routing, HMAC-SHA256 chain + lock, truncation/WORM anchoring, verified-session emit, dual clocks, deepcopy freeze; 29/29 | `evidence.py` |
| 10 | The Action Plane and Execution | **as titled** — idempotency, WAL ledger, open-state + 60s settling, reconciliation, failure taxonomy, anti-corruption BrokerAdapter; 16/16 | `action_executor.py` |
| 11 | Kill Switches and Hard Risk Limits | **as titled** — 4 levels, scoped kills, two-person crypto-bound control, re-arm needs 2 admins for L4, GuardedBroker kills TOCTOU, real-ledger chaos drills; 47/47 | `killswitch.py` |
| 12 | Egress Filters & Prompt Injection Defense | **Ch 12 — Prompt Injection & Untrusted Input** (retitled; egress-filter material folded into 12.5 output review + Ch 13) — randomized per-turn delimiters, planner/executor split, honest residual (mandate = invariant, not intent-reader; data-plane attacks named); 27/27 | `injection.py` |
| 13–23 | — | NOT YET DRAFTED (briefs §3) | — |

### Ch 8 verdict: REDEFINE (do not fold, do not drop, do not renumber)
Blueprint-v1's Ch 8 ("Implementing the MCP Server and Client") is **fully absorbed** by the cleared Ch 7 — the runnable client/server, poisoned-registry tests, and description-override defense all live there with 22 green tests. Deleting the slot would renumber nothing (cleared chapters reference each other by number: Ch 6→Ch 10, Ch 7→Ch 12, Ch 9→Ch 10 — renumbering is forbidden). Leaving it as a stub invites padding.
**Decision:** Ch 8 becomes **"Multi-Agent Systems: Orchestration over MCP"** — the single biggest coverage gap in blueprint-v1 (see §2). It sits naturally in Part III (Capability): agents composed as capabilities of other agents, orchestrated over the protocol Ch 7 just proved. A "production MCP" section (auth, reconnection/backoff, multi-server multiplexing) opens the chapter as the substrate, then the chapter earns its number with orchestration.

## 2. Coverage audit — every at-risk topic assigned

| Topic | Status | Home |
|---|---|---|
| Multi-agent systems | **GAP in v1 — now assigned** | **Ch 8 (redefined):** orchestrator-worker, supervisor vs peer graphs, handoff protocol (ties to App. A A2A), cost model of the second call, skeptical single-vs-team benchmark |
| Computer-use agents | GAP in v1 | **Ch 13 §:** action-space design for GUI agents (click/type/a11y), screenshot vs a11y tree, stale-DOM recovery — the canonical hard case for the sandbox chapter |
| Coding agents | GAP in v1 | **Ch 13 worked example** (the strategy-code-editing research agent: sandboxed shells, permission model for bash vs apply-patch, diff review) + **Ch 15 §** (SWE-bench-style eval for code tasks) |
| Long-running agents | Partial (Ch 11 heartbeat) | **Ch 14 § "Durable runs":** leases, heartbeats, checkpoints, resume-from-ledger (consumes Ch 9's evidence spine; does not re-derive it) |
| Operations (SLOs, on-call, OTel, capacity) | **GAP in v1** | **Ch 14** expanded: SLO table with numbers, OTel GenAI attributes, on-call script for outcome-unknown, model-gateway routing/fallback/caching, capacity plan |
| Failure semantics | Partial (Ch 10 taxonomy section) | **Ch 10 stays frozen** (cleared); full catalog → **new Appendix D:** timeout/partial/stale-read/ambiguous-commit/tool-lies/auth-expiry/model-drift/mid-transaction-intervention → sagas, compensating actions, transactional outbox, durable execution |
| Cost / latency | Scattered | Home base **Ch 15** (cost-per-verified-success as an eval metric) + **Ch 8** (when a 2nd agent call pays) + **Ch 14** (cost SLOs, gateway caching). Small-vs-large routing and prompt caching → Ch 14 model-gateway § (Ch 5 is frozen) |
| Human oversight | Partial (Ch 1 ritual, Ch 11 two-person) | **Ch 19 §:** risk-based escalation (expected loss × confidence × reversibility), approval fatigue/rubber-stamping, escalation UX design |
| Procurement | GAP in v1 | **Ch 19 §:** procurement questionnaire + vendor assessment |
| Decommissioning | GAP in v1 | **Ch 19 §:** the off-ramp — key revocation, data retention/deletion, model sunset, exit criteria |
| Agent Production Standard (executable) | GAP in v1 | **Front matter:** one-page Standard v1.0 as the thesis artifact + **new Appendix E:** executable certification gate (`production_gate.py` — no ship until identity, authority, contracts, threat model, eval thresholds, rollback, logging, escalation, incident owner demonstrated) |
| Context / memory engineering | GAP in v1 | **Ch 2 §** (the Observe problem: context budgets with numbers, compaction algorithms, scratchpad vs summary vs structured state, provenance of observations) + **Ch 3 §** (memory-write policy as system intent: what the agent may persist, forgetting) |
| Retrieval as evidence | Partial (Ch 9 taxonomy) | **Ch 15 §:** recall@k vs groundedness, hybrid search eval, the claim ledger; ACL-at-index vs at-query noted as the Ch 6/9 intersection (no new code) |
| Least-agentic ladder / workflows-before-autonomy | GAP in v1 | **Ch 2 §:** the ladder; deterministic workflow × single agent × multi-agent × human comparison (first instance of the recurring comparative table) |
| Incidents as design reviews | Partial (Ch 1 Maya) | **Ch 12 §** carries one: a real injection incident (e.g. EchoLeak-class) worked as design review — system of record → missing receipt → patch → fixture |
| Egress filtering (v1 Ch 12 remnant) | Folded | Ch 12 §12.5 (output review) + **Ch 13** (network boundary is the egress enforcement point) |
| Framework adapters | v1 as planned | Ch 18 (unchanged) |
| A2A protocol | Appendix A (v1) | Unchanged; Ch 8 handoff protocol section cross-references it |

**Comparative-table rule (from merged blueprint, now standing):** Ch 2, Ch 8, Ch 14, Ch 18 each carry a deterministic-workflow × single-agent × multi-agent × human table across reliability/cost/latency/flexibility/security/debuggability/human burden. Recurring lesson: the least autonomous system that reliably works.
**Glossary rule:** one glossary table mapping book jargon → industry vocabulary; keep only "capability vs authority" as house coinage. New **Glossary** appendix.

## 3. Remaining-chapter briefs

### Ch 2 — The Observe-Decide-Act-Verify (ODAV) Loop (Part I: Intent; no code)
- **Scope:** The book's operating loop, rigorous: Observe (the context-budget problem — compaction, provenance of observations), Decide (planning without theater), Act (least-agentic ladder), Verify (verification is a loop stage, not a phase). Answers Gemini's Ch-1-review question directly: Ch 2 stays conceptual — directors finish Part I able to *direct*; engineers get code from Ch 3 on.
- **Non-overlap:** No Pydantic, no HMAC, no broker. May name the mechanisms the loop will demand (contracts, receipts, ledgers) but implements none. Ends with the loop diagram + the ladder table.
- **Figs:** 1 (ODAV flowchart, FIG-spec → `figs/ch02-figspec.md`).

### Ch 3 — Defining System Intent (Part I→II pivot; `config_loader.py`)
- **Scope:** The pivot to engineering: AlphaForge/WealthForge team intro; immutable config; `.env` validation fail-closed (the merged blueprint's ".env never loaded" defect must not recur — `python-dotenv` actually wired, test proves a missing key fails closed); memory-write policy as intent (what persists, forgetting).
- **Tests:** missing-key fail-closed, unknown-key rejection, frozen-config mutation attempt, dotenv actually loaded (assert env value present).
- **Non-overlap:** No tools, no LLM calls, no broker. Reference architecture figure (Control/Execution/Data/Evaluation planes, trading edition); FIG-spec → `figs/ch03-figspec.md`.

### Ch 8 — Multi-Agent Systems: Orchestration over MCP (Part III: Capability; `team.py`)
- **Scope:** (a) Production MCP substrate: auth, reconnect/backoff, multi-server multiplexing, namespace collisions — short, consumes Ch 7 (no re-derivation). (b) Orchestration: orchestrator-worker, supervisor vs peer graphs, handoff protocol over A2A (App. A), the cost model of the second call, skeptical benchmark: team vs single agent on one task.
- **Tests:** handoff preserves tenant+authority (cross-ref Ch 6), second-call cost worksheet as an executable assertion, peer-graph deadlock guard, malicious-subagent output quarantined (cross-ref Ch 12).
- **Non-overlap:** Does not re-teach MCP wire format (Ch 7) or session tokens (Ch 6); imports both.

### Ch 13 — Sandboxes, SSRF, and the Agent That Writes Code (Part IV: Action; `network_boundary.py` + `sandbox.py`)
- **Scope:** Network boundary: SSRF middleware, metadata-endpoint block, egress allowlist (the egress-filter home). Sandbox: the strategy-code-editing research agent as worked example — sandboxed shells, permission model (bash vs apply-patch), diff review, worktrees. Computer-use §: GUI action-space design, stale-DOM recovery.
- **Tests:** metadata-IP blocked, allowlist deny-by-default, shell escape attempt contained, patch outside worktree refused.
- **Non-overlap:** Prompt-injection *content* defense stays Ch 12; Ch 13 is the *execution/network* boundary.

### Ch 14 — Operating the Evidence Pipeline (Part V: Evidence & Verification; `trace_writer.py`)
- **Scope:** THE NON-OVERLAP CONTRACT WITH CH 9: Ch 9 defined the evidence *contract* (taxonomy, HMAC chain, truncation, sessions). Ch 14 operates it: async TraceWriter, trace reconstruction for incidents, SLO table with numbers, OTel GenAI attributes, cost-per-verified-success worksheet, on-call script for outcome-unknown, model gateway (routing/fallback/caching), durable runs (leases/checkpoints/resume-from-ledger). Imports `evidence.py`; re-derives nothing.
- **Tests:** async writer ordering under load, SLO-breach alert fires, resume-from-checkpoint reproduces state, gateway fallback on provider outage.
- **Non-overlap:** No hash-chain re-derivation, no taxonomy repeat. Explicit "Ch 9 built the spine; this chapter runs it" bridge paragraph required.

### Ch 15 — Evaluators: Deterministic Grades and LLM Judges (Part V; `evaluator.py`)
- **Scope:** Eval-as-development: golden sets, deterministic graders, LLM-as-judge with agreement stats (Cohen's κ), Wilson intervals worked, frozen-dataset discipline (cross-ref Ch 9's EvalDataset), cost-per-verified-success as a metric, SWE-bench-style code-task eval, retrieval evals (recall@k vs groundedness, claim ledger), eval-vs-everything regression in CI.
- **Tests:** grader determinism (seeded), κ computation on a fixture, frozen dataset tamper detected, judge disagreement routed to human.
- **Non-overlap:** Walk-forward *methodology* is Ch 16; Ch 15 is the *grading machinery*.

### Ch 16 — Walk-Forward Verification (Part V; `walk_forward.py`)
- **Scope:** Temporal validation done honestly: embargo gaps, no-lookahead proofs (the Meridian invariant: signal on bar t executes ≥ t+1 open), regime-aware folds, the AlphaForge 2025-correction worked example with honest flat HOLDs where nothing survives.
- **Tests:** lookahead detector (strategy seeing future bar fails), embargo enforcement, fold-boundary leakage test.
- **Non-overlap:** PSR/DSR *math* is Ch 17; Ch 16 is the *protocol*. Imports Ch 15's graders for fold scoring.

### Ch 17 — PSR and DSR: Statistics Against Self-Deception (Part V; `metrics.py`)
- **Scope:** Probabilistic Sharpe Ratio and Deflated Sharpe Ratio as multiplicity control: the math, worked by hand on one walk-forward result, then NumPy implementation; "zero of 250 survive" honest-reporting discipline; minTRL (minimum track-record length).
- **Tests:** PSR on synthetic SR=0 returns ~0.5, DSR deflates under 250 trials, closed-form vs bootstrap agreement.
- **Non-overlap:** No walk-forward mechanics (Ch 16); consumes its folds.

### Ch 18 — Securing Enterprise Frameworks (Part VI: Accountability; `framework_adapters.py`)
- **Scope:** Wrappers enforcing ODAV on LangChain/LlamaIndex/AG2-style tools: the adapter interface (Agent, Model, Tool, Policy, State, Run, Trace, Approval, Evidence), legacy-tool wrapping with Pydantic egress filter, runtime mapping of the same loop across OpenAI Agents SDK / Anthropic / LangGraph (concepts, verified against docs — no hallucinated APIs).
- **Tests:** unwrapped legacy tool call refused, adapter injects tenant session (cross-ref Ch 6), approval gate enforced.
- **Non-overlap:** Does not re-teach contracts (Ch 4) or injection (Ch 12); it *applies* them.

### Ch 19 — Compliance, Procurement, and the Off-Ramp (Part VI; no code — policy mappings)
- **Scope:** Trace/tenant/kill-switch → auditor language: ODAV × EU AI Act / NIST AI RMF / ISO 42001 / SOC 2 mapping table; SLA numbers; human-oversight design (risk-based escalation, anti-rubber-stamping); procurement questionnaire; vendor assessment; decommissioning (key revocation, retention, sunset, exit criteria).
- **Non-overlap:** No new mechanisms; translates cleared machinery into buyer/auditor vocabulary. The chapter a CISO hands to procurement.

### Ch 20–23 — The Live Labs (Part VII: Practice; TDD, each must FAIL then PASS in CI)
- **Lab 1 (Ch 20) — Market-data evidence pipeline** (`test_lab1_data.py`): failing fixture → MCP quote server (Ch 7) → evidence routing (Ch 9). Proves the Ch 7+9 composition.
- **Lab 2 (Ch 21) — Signal generator contract** (`test_lab2_signals.py`): erratic-LLM fixture → strict SignalProposal schema (Ch 5) → Pydantic gate (Ch 4). Adversarial inputs included.
- **Lab 3 (Ch 22) — Execution under fire** (`test_lab3_execution.py`): flash-crash fixture → action executor (Ch 10) + kill switch trips at 5%/hour (Ch 11) + scoped kill isolates the desk. Ledger consistent afterwards.
- **Lab 4 (Ch 23) — Walk-forward verdict** (`test_lab4_verify.py`): Q3-2025 timeline fixture → walk-forward (Ch 16) + PSR/DSR (Ch 17) + LLM-judge thesis scoring (Ch 15). Honest HOLD allowed; fabrication fails the lab.
- **Lab rule (standing):** every lab ships a failing-first fixture; answer keys live ONLY in Appendix B, never in the lab chapter.

### Appendices
- **A — A2A 1.0 Protocol SDK** (`a2a_validate.py`): robust validator class; cross-referenced by Ch 8 handoffs. Spec claims verified against the A2A spec before drafting (same bar as Ch 7's MCP verification).
- **B — Lab answer keys:** passing implementations for Labs 1–4, each green in CI order.
- **C — Prompt-template reference:** copy-edited JSON/YAML templates (system prompts, contract docstrings for trusted descriptions, escalation UX copy).
- **D — Failure-semantics catalog (NEW):** the full taxonomy → saga/compensating-action/outbox patterns, worked against Ch 10's executor. Reference, not narrative.
- **E — Agent Production Standard v1.0, executable (NEW):** `production_gate.py` — the front-matter one-pager made executable; CI fails if any gate (identity, authority, contracts, threat model, eval thresholds, rollback, logging, escalation, incident owner) is undemonstrated.
- **Glossary (NEW):** book jargon → industry vocabulary.

## 4. Naming reconciliation — DECISION: keep the teaching fiction
**AlphaForge / WealthForge stay. Meridian never appears in the book.** Reasons: (1) 9 cleared chapters, all tests, and all prose use these names — a rename means re-review of cleared chapters; (2) Meridian is the user's private production platform — a public book must not couple to it by name or leak its internals; (3) the invariants are identical (intent→authority→capability→action→evidence→verification→accountability; t+1 execution; embargo+PSR/DSR; tenant-bound tokens; WAL-before-mutation; REAL/SYNTHETIC labeling; paper-only), so the book teaches exactly the discipline Meridian runs; (4) teaching fictions are standard practice. **Rule:** a preface note states the fiction once ("AlphaForge/WealthForge are a teaching team; their invariants mirror production practice"); no chapter ever winks at a real system.

## 5. Thesis-spine check
| Ch | Spine stage | Verdict |
|---|---|---|
| 1 | Intent (thesis incident) | ✓ |
| 2 | Intent→Verify (the loop itself) | ✓ — frame ODAV as the spine's operating rhythm |
| 3 | Intent (system intent, config, memory policy) | ✓ |
| 4 | Authority (contract = authority boundary) | ✓ |
| 5 | Authority→Capability (provider capability, schema authority) | ✓ |
| 6 | Authority (identity constrains authority) | ✓ |
| 7 | Capability (protocol surface) | ✓ |
| 8 | Capability (composition: agents as capabilities) | ✓ |
| 9 | Evidence (the contract) | ✓ |
| 10 | Action | ✓ |
| 11 | Action (the stop — boundary of action) | ✓ |
| 12 | Authority (untrusted input must never become authority) | ✓ — spans Authority/Capability by design; the boundary chapter |
| 13 | Action (execution/network boundary) | ✓ |
| 14 | Evidence (the operation) | ✓ |
| 15 | Verification (grading machinery) | ✓ |
| 16 | Verification (temporal protocol) | ✓ |
| 17 | Verification (statistical control) | ✓ |
| 18 | Accountability (frameworks under the standard) | ✓ |
| 19 | Accountability (auditor/buyer vocabulary) | ✓ |
| 20–23 | Practice (the spine, proved) | ✓ |

No chapter is off-spine. Ch 12's dual Authority/Capability mapping is intentional and must be named in its intro.

## Standing production rules (carried forward)
1. Every embedded listing verbatim-mirrors its `.py` source; scripted diff check in the same pass (adopted after Ch 4).
2. FIG-specs live in `figs/<ch>-figspec.md`; chapters carry one-line references (adopted after Ch 6).
3. Spec claims verified against primary sources before drafting (Ch 7 bar: A2A, JSON-RPC, OpenAI strict subset).
4. Synthetic data labeled SYNTHETIC; failed validation reported honestly (HOLD, never fabricated).
5. Meridian invariants hold in all trading examples: intentions not orders; t+1 execution; embargo + PSR/DSR; tenant-bound tokens; WAL-before-mutation; REAL/SYNTHETIC bars; paper only.
6. No orphan captions; headers match chapters (automated check); no repeated boilerplate (the v1 "No single plane owns…" ×4 defect must not recur).
7. All code executes: every chapter suite green, labs fail-then-pass, in CI order.

## Revised build order
1. **The Narrative:** Ch 2 → Ch 3 (closes Part I; unblocks the front-matter standard)
2. **The Composition:** Ch 8 (multi-agent; needs Ch 6+7+12 as imports — all cleared)
3. **The Armor:** Ch 13 (sandbox/SSRF/computer-use/coding-agent)
4. **The Operation:** Ch 14 (evidence ops; needs Ch 9 — cleared)
5. **The Verdict:** Ch 15 → Ch 16 → Ch 17 (evaluators → walk-forward → PSR/DSR)
6. **The Enterprise:** Ch 18 → Ch 19 (frameworks → compliance/procurement/off-ramp)
7. **The Proof:** Labs Ch 20 → 21 → 22 → 23 (each consumes cleared chapters)
8. **The Reference:** Appendices A → B → C → D → E + Glossary + front matter (Standard v1.0)
