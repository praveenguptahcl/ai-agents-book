# REBUILD BLUEPRINT v1 — "AI Agents: Systems, Safety, and Practice" (World-Class Edition)
**Source:** Gemini 3.1 Pro (Extended) — definitive chapter-by-chapter structure, 2026-09-11
**Basis:** Gemini's own exhaustive review of the 205-page Authority Edition (all Critical/High findings addressed)

## Thesis spine
Intent → Authority → Capability → Action → Evidence → Verification → Accountability

## Narrative split
- **Part I:** "Maya" non-technical narrative (directors/operators) — quarantined to Part I
- **Parts II–VII:** Python 3.11 paper-trading engineering track — AlphaForge (signal/research) + WealthForge (multi-portfolio) agent team, executing against an Alpaca-style paper broker via strict tool contracts

## Parts & chapters

### Part I: Intent (The Conceptual Baseline)
- **Ch 1: The Decoupling of Capability and Authority** — thesis via Maya narrative; briefing cards, permission receipts. Code: none. Figs: 2 (Capability vs Authority Venn; Briefing Card lifecycle).
- **Ch 2: The Observe-Decide-Act-Verify (ODAV) Loop** — rigorous loop, verification paramount. Code: none. Figs: 1 (ODAV flowchart).
- **Ch 3: Defining System Intent** — pivot to engineering; AlphaForge team intro; immutable config, .env validation fail-closed. Code: `config_loader.py`. Figs: 1 (Reference Architecture: Control/Execution/Data/Evaluation planes, trading edition). Fixes: .env best practices.

### Part II: Authority (Boundaries & Contracts)
- **Ch 4: Designing the Agent Tool Contract** — tools as strict contracts; Pydantic pre-network validation. Code: `schemas.py` (order create/cancel). Quant: Alpaca `submit_order` tool schema. Figs: 1 (contract validation sequence).
- **Ch 5: Provider Integration & Strict Schemas** — openai>=1.40 real SDK; `client.chat.completions.create` + `response_format={"type":"json_schema"}`; fail-plausible risks. Code: `llm_client.py`. Quant: SignalProposal JSON schema from model. Figs: 0. **Fixes: hallucinated client.responses.create.**
- **Ch 6: State Management and Tenant Isolation** — authority constrained by identity; memory scoping. Code: `tenant_manager.py`. Quant: isolate momentum vs dividend portfolios in WealthForge. Figs: 1 (tenant memory isolation).

### Part III: Capability (The MCP & Evidence)
- **Ch 7: The Model Context Protocol (MCP) Specification** — 2026-07-28 spec: transport, message format, capability discovery. Code: `mcp_types.py`. Quant: MCP resources/prompts for live market-data feed. Figs: 2 (MCP Host/Client/Server; init handshake). **Fixes: missing MCP.**
- **Ch 8: Implementing the MCP Server and Client** — runnable bidirectional MCP over stdio. Code: `mcp_server.py`, `mcp_client.py`. Quant: MCP server exposing fundamental-data APIs to AlphaForge signal agent. Figs: 0.
- **Ch 9: Capability via Evidence: Semantic Routing** — evidence pipelines over vector-DB default; semantic router. Code: `semantic_router.py`. Quant: route query → historical-price SQL vs news-sentiment API. Figs: 1 (semantic routing vs vector RAG).

### Part IV: Action (Execution & Boundaries)
- **Ch 10: The Action Plane and Execution** — validated proposal → external API; idempotency, timeouts. Code: `action_executor.py` (idempotent runner + retries). Quant: batch orders vs Alpaca paper API. Figs: 1 (order lifecycle state machine).
- **Ch 11: Kill Switches and Hard Risk Limits** — independent monitors overriding agent decisions. Code: `circuit_breaker.py`. Quant: 3% daily-drawdown halt revoking API keys. Figs: 1 (circuit breaker architecture).
- **Ch 12: Egress Filters & Prompt Injection Defense** — zero-click exfiltration defense; egress sanitization. Code: `egress_filter.py`. Quant: adversarial SEC filing → block position dump. Figs: 1 (EchoLeak/ShadowLeak sequence).
- **Ch 13: Sandbox Escapes and SSRF Prevention** — network restrictions, SSRF middleware. Code: `network_boundary.py`. Quant: block market-data HTTP tool → AWS metadata endpoints. Figs: 1 (SSRF attack vector). **Fixes: sandbox/SSRF gap.**

### Part V: Evidence & Verification (Tracing & Evals)
- **Ch 14: The Evidence Ledger and Observability** — tamper-proof async trace log. Code: `trace_writer.py` (async JSON logger). Quant: log context window + prompt behind a short-sell decision. Figs: 1 (trace reconstruction timeline).
- **Ch 15: Deterministic Evaluators and LLM-as-a-Judge** — eval as development; rubrics, agreement stats. Code: `evaluator.py` (RAGAS-style multi-metric + pytest). Quant: judge scores trading thesis vs historical conditions. Figs: 1 (judge pipeline). **Fixes: no-evaluator gap.**
- **Ch 16: Continuous Verification and Walk-Forward Testing** — temporal validation, embargoes. Code: `walk_forward.py`. Quant: AlphaForge through 2025 tech correction, no lookahead. Figs: 1 (embargo windows Gantt).
- **Ch 17: Statistical Thresholds: PSR and DSR** — Probabilistic/Deflated Sharpe Ratio. Code: `metrics.py` (NumPy PSR/DSR). Quant: prove alpha not multiple-testing noise. Figs: 0.

### Part VI: Accountability (Compliance & Frameworks)
- **Ch 18: Securing Enterprise Frameworks** — wrappers enforcing ODAV on off-the-shelf frameworks. Code: `framework_adapters.py` (LangChain/LlamaIndex wrappers). Quant: wrap legacy LangChain finance tool + Pydantic egress filter. Figs: 1 (adapter decorator UML). **Fixes: framework-adapter gap.**
- **Ch 19: Enterprise Compliance and SLAs** — trace/tenant/kill-switch → auditor language. Code: none (policy mapping). Quant: ISO 42001 report for WealthForge desk. Figs: 1 (ODAV → FedRAMP/HIPAA/ISO 42001 mapping table). **Fixes: compliance gap.**

### Part VII: Practice (The Live Labs)
- **Ch 20: Lab 1 — Market Data Evidence Pipeline** — TDD: failing tests → routing logic. Code: `test_lab1_data.py`. Quant: Polygon.io/AlphaVantage safe wiring. Figs: 0. **Fixes: empty labs.**
- **Ch 21: Lab 2 — Signal Generator Contract** — strict JSON schema surviving adversarial inputs. Code: `test_lab2_signals.py`. Quant: erratic LLM → buy/sell/hold enum + targets. Figs: 0.
- **Ch 22: Lab 3 — Paper Broker Execution & Risk Constraints** — circuit breaker trips in flash crash. Code: `test_lab3_execution.py`. Quant: halt Alpaca paper trades at 5%/hour drop. Figs: 0.
- **Ch 23: Lab 4 — Walk-Forward Verification** — end-to-end: agent over historical timeline, LLM-judge scored. Code: `test_lab4_verify.py`. Quant: AlphaForge over Q3 2025 earnings, final PSR. Figs: 0.

## Appendices
- **A:** A2A 1.0 Protocol SDK — robust `a2a_validate.py` class (replaces dict checker)
- **B:** Lab answer keys — passing pytest implementations for all 4 labs
- **C:** Formatting guide — copy-edited JSON/YAML prompt-template reference

## Build order (fastest working slice first)
1. **The Engine:** Ch 5 → 4 → 10 (fix OpenAI code; schema → LLM call → execution)
2. **The Protocol:** Ch 7 → 8 (MCP spec + runnable code)
3. **The Guardrails:** Ch 11 → 14 → 15 (TraceWriter, evaluators, kill switches)
4. **The Labs:** Ch 20 → 21 → 22 → 23 (pytest fixtures proving the engine)
5. **The Armor:** Ch 12 → 13 → 18 → 19 (SSRF, egress, wrappers, compliance)
6. **The Narrative:** Ch 1 → 2 → 3 → 6 → 9 → 16 → 17 (Maya opening, stats, routing)

## Execution notes
- Part V canonical name: "Evidence & Verification" (spine consistency)
- Ch 11 example uses 3% daily-drawdown halt; Lab 3 uses 5%/hour — keep each internally consistent
- Every chapter: purpose, live code artifact(s), quant example, figure specs, findings fixed — no orphan captions, no template padding
