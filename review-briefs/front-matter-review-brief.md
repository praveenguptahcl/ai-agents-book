# Front matter / Production Standard one-pager review brief (ready to send to Gemini once the glossary is cleared)

## Files to attach
- front-matter/production-standard.md (238 words; the one-pager)
- code/app_e/production_gate.py (the executable gate it points to)
- appendices/app-e-production-gate.md (prose, for scope cross-check)

## Prompt (verbatim)

---
INITIAL REVIEW: Front matter — "Agent Production Standard v1.0" one-pager (front matter; all 23 chapters, Appendices A–E, and the glossary cleared review to literal PASS).

SCOPE: A 238-word one-pager: nine gates in checklist form (Gate | Demonstrate | Artifact), each naming its chapters. The rule: for each gate, produce the artifact — do not describe it. Certification is a timestamp, not a tattoo: re-certify on every version bump. It points at production_gate.py (Appendix E) as the executable enforcement.

REVIEW IT RUTHLESSLY for:
1. GATE PARITY WITH APPENDIX E: the one-pager's nine gates must be the SAME nine gates production_gate.py enforces — same names, same Demonstrate criteria, same artifacts, same chapter mappings. Flag any drift (a gate renamed, a criterion softened or hardened, an artifact column entry the code doesn't actually check for, chapters misattributed).
2. SCOPE HONESTY: Appendix E's "What the Standard does not do" says the Standard certifies production readiness, NOT quality, taste, profitability, or safety. Flag any one-pager wording that overpromises beyond this (e.g., implying a passing certification means the system is safe).
3. ENFORCEABILITY: "No agent system ships until all nine gates are demonstrated." Flag any gate whose Demonstrate criterion is not actually demonstrable as an artifact (vague verbs, unobservable properties).
4. SELF-CONSISTENCY: "A claim is not a demonstration" vs the Artifact column — flag any artifact that is itself just a claim (a document asserting a property with no checkable content).

For each defect give a SEVERITY (High/Medium/Low), the exact location, what is wrong, and the precise fix. If you find zero defects, reply with the single word: PASS
---
