# Appendix C review brief (ready to send to Gemini once Appendix B is cleared)

## Files to attach
- appendices/app-c-prompts.md (2,916 words; 14 fenced blocks, YAML templates, no Python code)

## Prompt (verbatim)

---
INITIAL REVIEW: Appendix C — "Prompt-Template Reference" (book appendix; production-ready prompt templates in JSON/YAML; all 23 chapters and Appendices A–B cleared review to literal PASS).

SCOPE: Self-contained prompt templates, each with When-to-use / When-NOT-to-use notes and a customization guide (what to change, what to leave alone). Every placeholder must be named, typed, and justified. Section C.0 establishes prompt-as-policy: templates are versioned like code, implement Ch 3's system intent, and are the LAST line of defense, never the first (they never substitute for the Ch 4 contract gate, Ch 6 tenant session, or Ch 10 executor).

REVIEW IT RUTHLESSLY for:
1. TEMPLATE SOUNDNESS: does any template instruct the model to do something the book's machinery forbids or cannot enforce? Flag templates that promise what prompts cannot deliver (e.g., asking the model to "verify" without a verification stage in the loop).
2. PLACEHOLDER INTEGRITY: every value the user must supply must be named, typed, and justified. Flag any unexplained placeholder or any placeholder that is secretly load-bearing (changing it breaks a guarantee the template claims).
3. CUSTOMIZATION GUIDES: "what to change, what to leave alone" — flag any guide that marks a safety-critical line as customizable, or that forbids changing something that must vary per deployment.
4. CROSS-REFERENCES: claims about what Chapters 2, 3, 4, 6, 9, 10, 15 establish — flag any that misrepresent those chapters' contracts. In particular: the claim that Ch 15's frozen-dataset discipline applies to prompt versioning, and that the content hash of the system prompt belongs in the Ch 9 evidence spine.
5. VENDOR HONESTY: the vendor note claims templates are written against no vendor's proprietary fields. Flag any field or parameter that is actually vendor-specific.
6. ANTI-FABRICATION: flag any claim about model behavior (e.g., "the model will...") presented as guaranteed rather than as an instruction the machinery must enforce.

For each defect give a SEVERITY (High/Medium/Low), the exact location, what is wrong, and the precise fix. If you find zero defects, reply with the single word: PASS
---
