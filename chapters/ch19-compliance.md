# Chapter 19: Compliance, Procurement, and the Off-Ramp

*Part VI: Accountability*

The auditor arrives on a Tuesday. She does not ask how clever your agent is. She asks for the list of every action it took last quarter, who authorized each one, and what you would do if you had to turn it off by Friday. She does not want a tour of the architecture. She wants artifacts: logs she can verify, controls she can test, a person whose job it is to answer her questions.

This chapter is the translation layer between everything this book has built and the language that conversation is held in. It introduces no new machinery. Every claim here points at a mechanism from an earlier chapter — because compliance, done honestly, is not a separate activity bolted onto engineering. It is the engineering, seen from the auditor's side of the table.

That is the chapter's first thesis: **compliance is translation, not checkbox.** A control is a promise; a control's *evidence* is what makes the promise checkable. The reason auditors trust mechanisms over assurances is that mechanisms produce evidence as a side effect of doing their job. Chapter 9's evidence spine was not designed for auditors, but it is auditable precisely because it was designed for adversarial conditions — and adversarial conditions are what auditors simulate.

The second thesis: **procurement is the last line of defense for agents you buy instead of build.** Most enterprises will run agent systems they did not write, procured from vendors whose internals they cannot inspect. The questionnaire in this chapter is the instrument for that conversation.

The third thesis: **every system needs an off-ramp.** Decommissioning is the chapter of the agent's life that nobody writes, and it is where the most expensive incidents in enterprise software have historically lived — orphaned credentials, retained data with no owner, a model still serving long after anyone remembers approving it.

This chapter is the one a CISO hands to procurement. Read it as such.

## 19.1 The mapping table: ODAV against the frameworks

There are four frameworks worth mapping, because they are the ones buyers and auditors actually cite: the EU AI Act, the NIST AI Risk Management Framework, ISO/IEC 42001, and SOC 2. Each comes from a different tradition — statute, risk management, management systems, assurance — and each asks a slightly different question. The book's machinery answers the technical half of those questions. The organizational half (leadership accountability, training, documented policies) is explicitly out of scope: no hash chain can attend a governance meeting.

The table below is organized by what the frameworks actually demand, grouped under the ODAV loop, because the loop is the book's native vocabulary and the mapping is cleaner there than under any single framework's headings. Each row names the control, the framework clauses that impose it, the specific book mechanism that satisfies it, and — where the machinery does not reach — an honest gap marker. A mapping that hides its gaps is a liability, not an asset.

**Observe: the agent must act on known, bounded, provenance-labeled state.**

| Demand | Framework clause | Book mechanism | Gap |
|---|---|---|---|
| Inputs carry provenance | EU AI Act Art. 10 (data governance); NIST AI RMF Map 2 | Ch 2 Observe stage: observations labeled REAL vs SYNTHETIC, with age and source | Organizational data-quality processes (bias review, dataset documentation) are not in this book |
| Tenant data is separated at rest and in context | ISO 42001 A.7 (data stewardship); SOC 2 CC6.1 (logical access) | Ch 6: HMAC-bound tenant sessions, per-tenant memory scoping, quota on the tenant record | Key-management operations (rotation ceremony, HSM policy) are assumed, not built |
| Retrieved evidence is access-controlled | SOC 2 CC6.1;  | Ch 15 §: ACL-at-index vs at-query, noted at the Ch 6/9 intersection | No reference implementation of the ACL index itself |

**Decide: the agent's intentions are structured, rejectable, and attributable.**

| Demand | Framework clause | Book mechanism | Gap |
|---|---|---|---|
| Model outputs constrained to declared actions | EU AI Act Art. 14 (human oversight) — technical measures enabling oversight | Ch 4: Pydantic tool contracts; Ch 5: strict JSON-schema provider calls; Ch 8: delegation scope attenuation | None technical — but oversight *staffing* (who watches, with what authority) is organizational |
| System purpose is explicit and versioned | ISO 42001 §6 (planning); NIST AI RMF Map 1 | Ch 3: immutable, hashed SystemIntent; config fail-closed | Change-management *process* (who approves intent changes) is assumed |
| Multi-agent delegation is bounded | EU AI Act Art. 15 (robustness); NIST AI RMF Measure 2 | Ch 8: dual scope attenuation, depth limit, cycle guard, cost budget | None technical |

**Act: effects on the world pass through guarded, reversible, stoppable gates.**

| Demand | Framework clause | Book mechanism | Gap |
|---|---|---|---|
| High-risk actions require approval | EU AI Act Art. 14 (human oversight) | Ch 18: payload-bound, single-use approval tickets; Ch 11: two-admin lift for FULL_STOP | None technical — Chapter 19 (§19.3) provides the risk-based approval policy |
| The system can be stopped | EU AI Act Art. 14; ISO 42001 Clause 8.1 (operational control) | Ch 11: kill switches with per-tenant/per-strategy scope, send-time guard, TOCTOU-closed | Physical/business-continuity aspects (what happens to the business while stopped) are out of scope |
| Execution is idempotent and reconciled | SOC 2 PI1 (processing integrity) | Ch 10: idempotent executor, open-state lifecycle, settling window, WAL | None technical |
| Network and execution boundaries hold | SOC 2 CC6.1, CC7 (boundary protection) | Ch 13: SSRF middleware, sandboxed shells, egress allowlist | Cloud-infrastructure controls (VPC design, IAM) are assumed |
| Adversarial inputs are defended | EU AI Act Art. 15 (cybersecurity); NIST AI RMF Manage 2 | Ch 12: injection defense with honest residual; Ch 7: MCP description-override defense | The honest residual (in-mandate homoglyph) must be disclosed to the risk owner — see §19.4 |

**Verify: the world is read back, the record is tamper-evident, and someone can reconstruct what happened.**

| Demand | Framework clause | Book mechanism | Gap |
|---|---|---|---|
| Automatic logging of operations | EU AI Act Art. 12 (record-keeping / logging) | Ch 9: HMAC-chained evidence spine; Ch 14: async TraceWriter with backpressure discipline | Log *retention periods* are a policy decision, not a mechanism |
| Logs are tamper-evident | SOC 2 CC7.1 (system monitoring); ISO 42001 A.6.2.8 (recording of event logs) | Ch 9: HMAC-SHA256 chain with WORM checkpoint anchoring | The WORM store itself (S3 Object Lock or equivalent) is infrastructure, assumed |
| Evaluations are systematic and repeatable | NIST AI RMF Measure 1–3; ISO 42001 §9 (performance evaluation) | Ch 15: frozen golden sets, κ agreement stats, Wilson intervals, CI gates; Ch 16: walk-forward with embargo; Ch 17: PSR/DSR | Eval *dataset curation* (representativeness, bias review) is organizational |
| Incident response exists and is rehearsed | SOC 2 CC7.4; NIST AI RMF Manage 4 | Ch 14: the outcome-unknown on-call script; Ch 11: kill-switch drills | The rehearsal *schedule* and staffing are organizational |
| Risk management is continuous | EU AI Act Art. 9 (risk management system); ISO 42001 §6 | Appendix E: the executable Production Standard gate in CI | The risk register and its review cadence are organizational |

Read the Gap column as carefully as the Mechanism column. The pattern is consistent: the book builds the technical half — the part that runs in code — and names the organizational half explicitly. An auditor who sees a gap named and owned will trust the mechanisms more, not less. A mapping that claims ISO 42001 §5 (leadership) is satisfied by a Pydantic model is a mapping that has never met an auditor.

## 19.2 SLA language with numbers

An SLA is a contract, not a control. It does not make the system reliable; it makes unreliability expensive in a predictable way. That distinction matters because teams routinely confuse the two — they write an SLA and then act as though the failure modes it prices have been prevented. They have not. They have been *budgeted*.

Chapter 14's SLO table is the floor. The SLA is the contractual ceiling built on it. Propose language like this, and adjust the numbers to the desk's actual measurements — an SLA written from aspirations instead of measurements is a promise to be breached:

- **Availability:** the agent service will accept and process delegation requests 99.9% of measured minutes per calendar month, excluding scheduled maintenance windows and kill-switch activations (a kill-switch trip is the system working, not an outage — write that exclusion explicitly, or the first correct halt becomes a breach).
- **Evidence lag:** 99% of evidence entries will be durably written within 5 seconds of the event they describe, measured at the TraceWriter's flush boundary (Ch 14). Breach of this SLA is a safety event, not just a contractual one — evidence loss is the one failure this book never permits silently.
- **Verification completeness:** 100% of external actions will reach a terminal verification state (confirmed, failed, or reconciled) within the settling window; zero actions may remain in PENDING past the window without an open incident (Ch 10's open-state lifecycle, Ch 14's outcome-unknown script).
- **Incident response:** acknowledgement of a kill-switch trip or evidence-integrity alert within 15 minutes; a human decision on outcome-unknown incidents within 4 hours (the Ch 14 playbook's escalation timers).
- **Evaluation freshness:** the CI eval gate (Ch 15) will run on every merge to main; no deployment ships with a red gate; golden sets are re-validated against production drift quarterly.

And the honest caveat, which belongs in the contract's recitals, not buried in an appendix: the SLA prices *detectable* failures. A failure the evidence spine cannot see — the honest residual in Chapter 12, a novel exfiltration path outside the allowlist — is not covered by any SLA, because no contract can price what neither party can measure. The SLA's job is to make the known failure modes expensive enough to keep investing in the unknown ones.

## 19.3 Human oversight: the ritual problem

Chapter 1 named the failure mode: Priya, watching Harbor's payments, her attention degrading into ritual — the human checker who approves what the agent does because the agent is usually right, until the one time it is catastrophically wrong. Chapter 11 built the two-admin lift as the structural answer. This section is the design discipline for the humans in the loop: when to require them, how to keep them effective, and what to show them.

**Risk-based escalation.** Not every action deserves a human. The escalation rule is a product of three factors: expected loss (what does this cost if it is wrong?), confidence (how sure is the system — the model's calibrated confidence, not its asserted confidence), and reversibility (can we undo it?). High expected loss × low confidence × irreversible = human approval, mandatory, with context. Low expected loss × high confidence × reversible = let it run, log it, review in aggregate. The dangerous quadrant is high expected loss × high confidence — the agent is sure and the stakes are real — because that is exactly where rubber-stamping lives: the human sees a confident agent, a long streak of correct decisions, and clicks approve without reading. Design for that quadrant explicitly: in high-stakes approvals, show the *dissenting* evidence first, require the approver to state the reason in their own words (a checkbox is a ritual; a sentence is a thought), and rotate approvers so no one builds a streak.

**Approval fatigue is a security vulnerability.** Every unnecessary approval spends the approver's attention budget and teaches them that approvals are theater. The fix is not more approvals — it is fewer, better-placed ones. The Ch 18 approval ticket exists precisely so that approvals are rare, payload-bound, and meaningful: when the ticket appears, something genuinely irreversible is about to happen, and the approver knows it because the system does not cry wolf on reversible steps.

**Escalation UX.** What the approver sees, in order: (1) what is being asked, in plain language, with the exact payload digest; (2) why the system escalated — which risk factor tripped, with the numbers; (3) the dissenting evidence — what argues against approval; (4) the blast radius — what happens if this is wrong, and whether it is reversible; (5) the evidence trail so far — the Ch 9 spine excerpt for this decision chain, so the approver can verify rather than trust. Appendix C carries the copy templates for these screens. The design principle: the approver's job is *verification*, not *permission* — they are the Verify stage of the loop, embodied.

## 19.4 Procurement: the questionnaire

You will buy agent systems you did not build. The vendor's sales deck will show you the happy path. The questionnaire is how you see the rest. Send it before the pilot, score it before the contract, and treat evasive answers as answers.

Map each question to the book's disciplines — identity, authority, contracts, threat model, eval thresholds, rollback, logging, escalation, incident ownership:

**Identity & authority**
1. How is a tenant's identity established and bound to its authority? (You are listening for: cryptographic binding, not string IDs — the Ch 6 standard. "The tenant ID is passed in the request header" is a failing answer.)
2. Can one tenant's agent act with another tenant's authority under any code path, including error paths and retries? Show the test that proves it cannot.
3. What is the blast radius of a compromised agent credential? Walk us through revocation: how long until it stops working everywhere?

**Contracts & capabilities**
4. Are tool inputs validated against strict schemas before any network call? What happens on validation failure — fail closed or fail open? (Ch 4/Ch 5.)
5. If you integrate third-party capability servers (MCP or equivalent), whose tool descriptions does the planner see — yours or the server's? How do you handle a poisoned tool description? (Ch 7.)
6. When your agents delegate to sub-agents, how is authority attenuated at each hop? Is there a delegation depth limit? (Ch 8.)

**Threat model & boundaries**
7. Show us your threat model for prompt injection. What is your *honest residual* — the attack class you do not defend against — and how is it disclosed to the risk owner? (Ch 12. A vendor with no named residual has not thought about it.)
8. How are outbound network calls constrained? Is there an egress allowlist, and what happens when the agent tries to reach something off it? (Ch 13.)
9. Can the agent execute code or shell commands? Under what permission model, and what is confined to what? (Ch 13.)

**Evidence & verification**
10. Is every external action recorded in a tamper-evident log? What cryptographic construction protects the chain, and where are the checkpoints anchored? (Ch 9.)
11. What is your verification discipline — how do you confirm the world changed as intended, including for slow-settling actions? (Ch 2/Ch 10.)
12. What are your eval gates? Show us a golden set, an agreement statistic, and the last time the gate blocked a release. (Ch 15.)

**Operations & accountability**
13. What are your SLOs — with numbers — for evidence lag, verification completeness, and incident response? (Ch 14.)
14. What is your kill-switch story? Who can stop the system, how fast, and what does "stopped" mean for in-flight actions? (Ch 11.)
15. What does it cost to run — per verified success, not per API call? (Ch 15's cost metric.)
16. Name the incident owner. Not the team — the person. What is their escalation path at 3am? (Ch 14's on-call script.)

**Scoring.** Score each answer 0 (absent), 1 (claimed, unevidenced), or 2 (demonstrated — test, log, or artifact shown). Weight identity, evidence, and kill-switch answers double; a vendor can improve its eval story over time, but it cannot retrofit tenant isolation or tamper-evident logging after the architecture is set. Red flags, any one of which should pause the deal: no named residual in the threat model; "our model is aligned" offered as a control; logging described as "we keep logs" with no integrity story; no human who can stop the system; cost quoted only per token with no per-outcome figure; the incident owner is "the team."

**Vendor assessment beyond the questionnaire.** Run the pilot against your own adversarial fixtures, not the vendor's demo script: feed it the Ch 12 injection fixtures, the Ch 13 SSRF probes, a cross-tenant confusion attempt. A vendor that passes your fixtures has a system; a vendor that asks you not to run them has a demo.

## 19.5 The off-ramp: decommissioning

Every agent system ends. Strategies are retired, vendors are replaced, desks are reorganized, companies are acquired. The off-ramp is the phase nobody designs, and it is where the quiet disasters live: the API key that still works two years after the project died, the tenant data nobody owns, the model endpoint still serving because no one filed the ticket to turn it off.

**Key revocation.** Maintain a registry of every credential the system ever held — broker API keys, provider keys, MCP server credentials, tenant session signing keys. Decommissioning walks the registry and revokes each one, then *verifies* revocation by attempting authentication and confirming failure. A revocation that is not verified is a hope, and this book has a position on hopes. Tenant signing keys deserve special care: rotate-then-revoke, so in-flight sessions drain gracefully instead of dying mid-action.

**Data: retention vs deletion.** These pull in opposite directions and both are legitimate. The audit spine must be retained — regulators, contracts, and the EU AI Act's record-keeping obligations do not expire when the system does. Tenant operational data (prompts, retrieved documents, intermediate state) should be deleted on a defined schedule, per-tenant, with deletion itself recorded as an evidence entry (the spine records its own pruning — the one write permitted to the decommissioned system). The rule: **kill the agent, keep the evidence.** The audit spine outlives the system it watched; that is its job.

**Model sunset.** If the system used fine-tuned or dedicated models, sunset them: remove from serving, revoke inference credentials, archive the weights and training lineage per retention policy. A model that nobody maintains but everybody can still call is an unowned capability — the exact thing Chapter 8's authority discipline exists to prevent.

**Exit criteria.** Decommissioning is done when: all credentials revoked and verified; tenant data deleted per schedule with evidence entries; the audit spine exported to the retention store and its chain verified end-to-end; positions flat and confirmed (for trading systems — the desk's money is not a rounding error); no scheduled job, cron, or heartbeat still references the system; the incident owner signs the closure, and the signature is itself an evidence entry.

**The desk's retired strategy.** WealthForge retired its dividend-capture strategy last quarter — a worked example of the off-ramp done right. Keys revoked and revocation verified against the paper broker; tenant sessions for the strategy's portfolios invalidated; eleven months of evidence retained in the WORM store with the chain verified; operational state deleted per the tenant schedule; positions confirmed flat before the kill switch was even touched (flat first, *then* dark — you do not decommission a system holding risk); the closure signed by the desk head as the final entry in the strategy's evidence chain. The strategy is gone. Its record is complete. That is what a clean ending looks like.

## 19.6 What this part established

Accountability is the loop closed at the organizational level. Part VI took the machinery — contracts, sessions, ledgers, kill switches, sandboxes, evaluators — and showed it answering the questions that people with authority over budgets and liability actually ask: *prove it, price it, stop it, buy it safely, end it cleanly.* Chapter 18 wrapped the frameworks enterprises already run; this chapter translated the discipline into the language of auditors, buyers, and the off-ramp.

But accountability described is not accountability demonstrated. The labs are where the reader stops reading about the loop and starts running it — failing first, as engineers do, then making it pass. Part VII: Practice.

---
*Figure 19.1 — the ODAV × framework mapping table (see `figs/ch19-figspec.md` for the full specification).*
