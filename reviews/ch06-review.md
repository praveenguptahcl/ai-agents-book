# Gemini Review — Ch 6: Tenant Isolation
- **Model:** Pro Extended (Gemini 3.1 Pro class)
- **Date:** 2026-09-11
- **Verdict:** PASS-WITH-FIXES
- **Files reviewed:** ch06-tenant-isolation.md, tenant.py, test_tenant.py (all attached and cited)

## Full verbatim review

VERDICT: PASS-WITH-FIXES

This draft is structurally excellent. The central premise—that tenant isolation in agent architectures must be explicitly threaded and verified on every call—is dead on. The HMAC-signed token approach is pragmatic, the namespace composite-key design is bulletproof, and the test-as-adversary framing makes for compelling pedagogy.

However, there is a critical missing link at the action-plane binding, a disconnect in the quota logic, and a slight misalignment in how you talk about replay attacks. Here is the ruthless breakdown to get this ready for print.

### Numbered Findings

**1. The Capability-Mapping Seam is Hand-Waved (Critical)**

The Issue: You explicitly establish the danger of the "module-level singleton" broker client. Your solution, submit_as, brilliantly verifies that the session's authority matches the order's intent. But then it just delegates to submit_fn(order). How does submit_fn know which physical API credentials to use? If submit_fn still relies on a singleton client underneath, verifying authority doesn't actually route the execution to the correct tenant's paper account.

The Fix: You must close the loop between authority and capability. The executor (Chapter 10) needs a mechanism to multiplex capabilities (e.g., retrieving the tenant-specific API key from TenantNamespace). Add a sentence or two explaining that submit_fn uses the validated session.tenant_id to retrieve the correct execution credentials, ensuring the capability is scoped to the verified authority.

**2. Token Replay vs. Nonce Validation (High)**

The Issue: The token generation includes a nonce (secrets.token_hex(8)) inside the signed payload. However, TenantStore.verify only checks the signature and expiry; it does not track used nonces. Therefore, this token is a standard bearer token. If stolen, it can be replayed until it expires (up to 1 hour based on ttl_seconds=3600.0).

The Fix: Clarify in the prose that the nonce exists strictly to ensure token uniqueness (so two tokens issued in the same second aren't identical strings), not to prevent replay attacks. Acknowledge that because it's a bearer token, defense relies on short TTLs and TLS in transit.

**3. Rate Limiter / Quota Disconnect (Medium)**

The Issue: The Tenant dataclass explicitly defines a quota_per_minute field. Yet, RateLimiter.check completely ignores this field, requiring the caller to pass a limit: int argument manually.

The Fix: Change the signature of RateLimiter.check so it retrieves the limit from the TenantStore or the TenantSession itself, rather than trusting the caller to provide the correct integer limit.

**4. Trace Logging and Token Leaks (Medium)**

The Issue: You rightly point out that trace logs are a leak vector. But your solution relies on explicit session threading—meaning every tool call takes the token as an argument. If the orchestrator uses standard observability tools that blindly log tool-call arguments, the plaintext bearer tokens will be sprayed across the logs.

The Fix: Add a specific warning in the "Log cross-contamination" section (Vector 4). Emphasize that explicit threading demands strict parameter masking in observability pipelines so tokens are never logged.

**5. Cross-Tenant Reads Returning Absence (Low)**

The Issue: Returning None for cross-tenant reads is absolutely the correct call to prevent key-probing. But developers often fear this will lead to data collisions if they accidentally write to the wrong key.

The Fix: Briefly reiterate why this absence is safe: the underlying dictionary keys are composite tuples (tenant_id, key). There is zero risk of tenant B accidentally overwriting tenant A's data because they both exist in non-overlapping address spaces.

### What I Would Cut / Trim

Trim the "Confused Deputy" preamble: The first paragraph of the Confused Deputy section repeats the core premise of ambient authority already established in the Ambient credentials bullet just above it. Consolidate these. State the problem once, sharply, and move directly to the structural fix.

Cut the FIG-spec detail: If the text is going to layout, you likely don't need the incredibly verbose visual description of the diagram embedded in the main prose file unless your publisher specifically requested it inline. Move the visual direction to an appendix or a separate layout file so the technical reader doesn't hit a wall of styling text.
