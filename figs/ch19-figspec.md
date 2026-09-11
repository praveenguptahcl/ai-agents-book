# Figure 19.1 — ODAV × compliance-framework mapping table (figure specification)

## Figure type
Full-page reference table (landscape if needed). This is the chapter's signature figure: the one a CISO screenshots.

## Layout
A wide table with four columns: **ODAV stage** (Observe / Decide / Act / Verify, as banded row groups) | **Framework demand** (plain-language control) | **Framework clause** (EU AI Act Art. / NIST AI RMF function / ISO 42001 clause / SOC 2 criterion) | **Book mechanism** (chapter + mechanism name).

Band rows by ODAV stage with a tinted stage header row spanning all columns: OBSERVE (state must be known, bounded, provenance-labeled), DECIDE (intentions structured, rejectable, attributable), ACT (effects pass guarded, reversible, stoppable gates), VERIFY (world read back, record tamper-evident, reconstructable).

## Rows (condensed from §19.1)
- OBSERVE: inputs carry provenance → Art. 10 / Map 2 → Ch 2 REAL-vs-SYNTHETIC labeling; tenant separation → ISO 42001 A.7 / CC6.1 → Ch 6 HMAC tenant sessions; retrieval ACLs → CC6.1 / Govern 4 → Ch 15 ACL-at-index-vs-query.
- DECIDE: outputs constrained to declared actions → Art. 14 → Ch 4 contracts, Ch 5 strict schemas, Ch 8 scope attenuation; purpose versioned → ISO 42001 §6 / Map 1 → Ch 3 hashed SystemIntent; delegation bounded → Art. 15 / Measure 2 → Ch 8 depth limit, cycle guard, budget.
- ACT: high-risk approval → Art. 14 → Ch 18 payload-bound approval tickets, Ch 11 two-admin lift; system stoppable → Art. 14 / ISO 42001 A.8 → Ch 11 kill switches; idempotent reconciled execution → SOC 2 PI1 → Ch 10 executor + WAL; boundary protection → CC6.1/CC7 → Ch 13 SSRF middleware + sandbox; adversarial-input defense → Art. 15 / Manage 2 → Ch 12 injection defense, Ch 7 MCP description defense.
- VERIFY: automatic logging → Art. 12 → Ch 9 evidence spine, Ch 14 TraceWriter; tamper-evident logs → CC7.3 / ISO 42001 A.9 → Ch 9 HMAC chain + WORM anchoring; systematic evals → Measure 1–3 / ISO 42001 §9 → Ch 15/16/17; incident response → CC7.4 / Govern 6 → Ch 14 on-call script, Ch 11 drills; continuous risk management → Art. 9 / ISO 42001 §6 → Appendix E production gate.

## Annotations
- A fifth element, not a column: each row carries a small "gap" glyph where the book's machinery does NOT reach (organizational half: leadership, training, change-management process, rehearsal schedules). Legend at the foot: "Glyph marks the organizational half — named and owned, not hidden."
- Footer note: "Mechanisms are technical; the named gaps are organizational. An auditor who sees a gap named and owned trusts the mechanisms more, not less."
- Color: stage bands in the book's Part VI accent; gap glyphs in a contrasting warning tone.

## Caption
Figure 19.1 — Every control the frameworks demand, mapped to the mechanism that satisfies it — and the gaps honestly marked. Compliance as translation.
