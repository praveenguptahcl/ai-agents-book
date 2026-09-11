# Gemini Review — Ch 7: MCP
- **Model:** Pro Extended (Gemini 3.1 Pro class)
- **Date:** 2026-09-11
- **Verdict:** PASS-WITH-FIXES
- **Files reviewed:** ch07-mcp.md, mcp_protocol.py, mcp_server.py, mcp_client.py, test_mcp.py (all attached and cited)
- **Spec verification:** Gemini performed live web searches during the review and confirmed the chapter's spec claims are "razor-accurate against the 2026-07-28 standard" — the stateless `_meta` shift, mandatory `server/discover`, deprecated roots/sampling are all correct. The "What the last edition got wrong" box is fair and precise.

## Full verbatim review

Verdict: PASS-WITH-FIXES

This is a rigorously structured, highly effective draft. It brings the exhaustive scrutiny of design verification directly into protocol engineering—exactly what a production-grade LLM architecture requires. The spec claims are razor-accurate against the 2026-07-28 standard, and the trust analysis correctly anchors the threat model.

### 1. Critical Architecture & Code Findings

**CRITICAL: The CONTRACTS Allowlist Bypass.** Your thesis is "Pydantic gives you the law," but your code violates it. In mcp_client.py -> call_tool, if a tool is in self.allowed_tools but developers omitted it from CONTRACTS, contract evaluates to None. The validation block is skipped entirely, and raw, unvalidated arguments hit the wire. Fix: Fail closed. If an allowed tool lacks a local contract, call_tool must immediately raise a ContractViolation.

**HIGH: The Prompt Injection Pedagogy Contradiction.** §7.4 states tool descriptions are "never interpolated into a prompt. Descriptions are routing labels..." This completely breaks agentic AI tool use. The LLM planner requires a description in its prompt to understand tool semantics and trigger conditions. If you strip it out, the agent is flying blind. Fix: Explain how the agent learns semantics safely. For a closed framework like AlphaForge, the standard defense is client-side overrides: the client discards the untrusted server description and injects a hardcoded, trusted description from the local Pydantic contract's docstring into the system prompt.

### 2. Spec Accuracy & Protocol Compliance

Your core spec claims regarding the stateless _meta shift, the server/discover mandate, and the deprecation of roots/sampling are fully accurate. The "What the last edition got wrong" box is fair and precise. However, two protocol implementation details need fixing:

**MEDIUM: Ignoring the isError Flag.** §7.3 explicitly notes that a tool failure returns isError: true. Your code ignores this. If a server returns isError: true with standard text like "Market closed", get_quote will blindly attempt to parse it as JSON, throwing a misleading JSONDecodeError. Fix: Check for isError explicitly in call_tool and raise a dedicated ToolExecutionError so retry logic doesn't mistake a rejected trade for a protocol crash.

**LOW: JSON-RPC 2.0 Error Codes.** In mcp_server.py, a missing method is rejected with -32602 (INVALID_PARAMS). Per JSON-RPC 2.0 specs, a malformed envelope is -32600 (INVALID_REQUEST). Fix: Use INVALID_REQUEST for envelope structure failures, and only return None (silence) if id is missing and method is a valid string.

### 3. Prose and Cuts

Pacing: "MCP gives you the listing, Pydantic gives you the law" is a brilliant architectural anchor. Keep it exactly as is.

Cut 1 (§7.1): Remove the preamble "The vocabulary survives the 2026-07-28 revision...". Get straight to the Host/Client/Server definitions.

Cut 2 (§7.2): Trim the Streamable HTTP header mapping explanation. It drifts into implementation details that distract from the stdio focus of the chapter code.

How are you planning to structure the transition from this protocol layer into the prompt injection mitigations detailed in Chapter 12?
