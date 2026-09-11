# Appendix D review brief (ready to send to Gemini once Appendix C is cleared)

## Files to attach
- appendices/app-d-failure-semantics.md (3,550 words; prose catalog, no Python code)

## Prompt (verbatim)

---
INITIAL REVIEW: Appendix D — "Failure-Semantics Catalog" (book appendix; reference catalog of execution-boundary failure modes; all 23 chapters and Appendices A–C cleared review to literal PASS).

SCOPE: A reference catalog — every failure mode an agent system meets at its execution boundary, each with a name, a detection signal, and the handling pattern. It extends Ch 10's taxonomy (timeout, partial fill, duplicate submission, stale read, ambiguous commit, accepted-not-yet-filled, read-after-write race, reconcile sweep failure) to modes Ch 10 didn't cover (a tool that lies, auth expiring mid-run, model drift, human intervention mid-transaction) and generalizes two (partial fill → partial completion). Two governing rules: never guess at an unknown (timeouts may retry with the idempotency key; ambiguity may never be resolved by assumption); the broker is the source of truth, the ledger is a cache.

REVIEW IT RUTHLESSLY for:
1. CONSISTENCY WITH CH 10: the appendix's consistency note claims nothing here contradicts Ch 10 and every Ch 10-named entry keeps its Ch 10 meaning and behavior. Flag any entry whose definition, detection signal, or pattern actually contradicts Ch 10's action-plane contracts (idempotency keys, the four outcomes of a submit, reconcile, the ledger as saga log).
2. PATTERN SOUNDNESS: does each entry's handling pattern actually resolve the failure without creating a worse one? Flag any pattern that retries what must not be retried, guesses at an unknown, or contradicts the appendix's own two rules.
3. ANTI-FABRICATION: flag any worked example that invents broker behavior (e.g., a broker dedupe guarantee) presented as universal rather than as the book's assumed broker contract. Flag any "Detect" signal that is not actually observable from the agent's side of the boundary.
4. CROSS-REFERENCES: claims about what Chapters 2, 4, 9, 10, 11, 14, 18 establish — flag any misrepresentation. In particular: the claim that Ch 14's 2:14am OUTCOME-UNKNOWN playbook is the operational face of these entries, and that partial completion's "new proposal" needs fresh authority per Ch 4.
5. COMPLETENESS GAPS: failure modes at the execution boundary that the catalog's own framing implies but no entry covers.

For each defect give a SEVERITY (High/Medium/Low), the exact location, what is wrong, and the precise fix. If you find zero defects, reply with the single word: PASS
---
