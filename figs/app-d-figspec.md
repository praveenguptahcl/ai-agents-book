# FIG-spec: Appendix D — Failure-Semantics Catalog decision tree

**Chapter one-line reference:** Appendix D's eight failure modes compressed into a single diagnostic flowchart: *failure mode → detection signal → handling pattern*.

## Figure D.1 — The failure-semantics decision tree

**Type:** vertical flowchart / decision tree, 8 terminal nodes, single entry point.

**Entry point (top):** A rounded box: **"Something went wrong at the execution boundary."**

**Decision diamonds (in order, top to bottom), each with YES/NO branches:**

1. **Diamond:** "Did you get an answer?"
   - **NO → terminal box: TIMEOUT.** Sub-caption: *Detect: response never arrived within the deadline.* Pattern: *same idempotency key, exponential backoff, then hold `timeout` for reconcile.*
   - YES → continue to 2.
2. **Diamond:** "Did the answer claim less than the request?"
   - **YES → terminal box: PARTIAL COMPLETION.** *Detect: terminal response with filled quantity < requested.* Pattern: *record partial as terminal; the remainder is a new proposal with a new key.*
   - NO → continue to 3.
3. **Diamond:** "Do two sources disagree about the same entity?"
   - **YES → sub-diamond:** "Did a human (or another agent) change it out-of-band?"
     - **YES → terminal box: MID-TRANSACTION HUMAN INTERVENTION.** *Detect: ledger-vs-world mismatch; broker audit trail names an operator session, not the agent's key.* Pattern: *adopt broker truth regardless of cause; the kill-switch gate — not ledger edits — is the human's instrument.*
     - **NO → terminal box: STALE READ.** *Detect: two reads of the same entity return different states.* Pattern: *authoritative source wins; caches adopt, never argue; stamp reads with versions.*
   - NO → continue to 4.
4. **Diamond:** "Is the outcome still unknown after the retry budget?"
   - **YES → terminal box: AMBIGUOUS COMMIT.** *Detect: `timeout` row, no distinguishing broker signal.* Pattern: *never guess; reconcile by key; run the 2:14am OUTCOME-UNKNOWN playbook (Ch 14).*
   - NO → continue to 5.
5. **Diamond:** "Does the answer's claim fail independent verification?"
   - **YES → terminal box: TOOL LIES.** *Detect: cross-plane disagreement reconciliation cannot explain — the claim contradicts an independent observation.* Pattern: *terminal records only from independent sources; quarantine the tool; emit the discrepancy as evidence.*
   - NO → continue to 6.
6. **Diamond:** "Did authority die mid-run?"
   - **YES → terminal box: AUTH EXPIRY MID-RUN.** *Detect: 401/403 on calls that previously succeeded.* Pattern: *non-retryable; stop acting, re-verify the tenant session (Ch 6), resume from the ledger — reconcile before any new submit.*
   - NO → continue to 7.
7. **Diamond:** "Did aggregate behavior shift with no system change?"
   - **YES → terminal box: MODEL DRIFT.** *Detect: eval regression on the frozen golden set — κ decay, pass-rate drift (Ch 15).* Pattern: *pin the model, gate changes through evals, shadow before submit, roll back on detection.*
   - NO → terminal box: **UNCLASSIFIED — go back to 1.** *You missed an entry; "I don't know what happened" is never terminal — it points to the reconcile step that will find out.*

**Styling notes:**
- Terminal boxes are color-coded by handling family: **retry-safe** (timeout — amber), **terminal-and-move-on** (partial completion, stale read — blue), **never-guess** (ambiguous commit — red), **distrust-and-verify** (tool lies — purple), **stop-and-reverify** (auth expiry, human intervention — orange), **slow-and-statistical** (model drift — gray), **loop-back** (unclassified — dashed outline).
- Each terminal box shows three lines: the MODE NAME (bold), the detection signal (italic, prefixed "Detect:"), the pattern (prefixed "Pattern:").
- A footer band runs the appendix's thesis: *"Timeouts may retry; ambiguity may never be guessed at. The broker is the source of truth; the ledger is a cache."*
- Cross-references (Ch 10, Ch 14's 2:14am playbook, Ch 6, Ch 15) appear as small superscript tags on the relevant terminal boxes, not in the main text flow.

**Size:** full-page landscape; the tree must be legible at print size — if space is tight, split into two columns (diamonds 1–4 left, 5–8 right) with the entry point spanning the top.
