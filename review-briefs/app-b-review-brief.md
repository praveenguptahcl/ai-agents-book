# Appendix B review brief (ready to send to Gemini once Appendix A is cleared)

## Files to attach
- appendices/app-b-answer-keys.md (3,592 words)
- code/app_b/lab1_pipeline.py
- code/app_b/lab2_signal_pipeline.py
- code/app_b/lab3_solution.py
- code/app_b/lab4_solution.py

## Prompt (verbatim)

---
INITIAL REVIEW: Appendix B — "Lab Answer Keys" (book appendix; solutions for Labs 1–4 in Ch 20–23; every chapter and Appendix A cleared your review to literal PASS).

SCOPE: This appendix gives the reference solutions for the four labs, which ship failing-first (RED). A double-run CI harness (scripts/ci_double_run.py) verifies each lab fails as shipped (RED) and passes with the Appendix B key (GREEN). Latest local double-run: Lab 1 RED collection-error as shipped / GREEN 10/10; Lab 2 RED 10/10 / GREEN 10/10; Lab 3 RED 8/8 / GREEN 8/8; Lab 4 RED five expected failures plus one documented trap pass / GREEN 6/6.

REVIEW IT RUTHLESSLY for:
1. KEY CORRECTNESS: does each answer key actually turn its lab GREEN? Trace each key against the lab's test file (code/ch20/test_lab1_data.py, code/ch21/test_lab2_signals.py, code/ch22/test_lab3_execution.py, code/ch23/test_lab4_verify.py) and flag any key that would not satisfy an assertion.
2. PROSE/CODE CONSISTENCY: every code listing in app-b-answer-keys.md must verbatim-match the corresponding solution file in code/app_b/. Flag any drift.
3. PEDAGOGY: do the keys explain WHY, not just give code? Does any key leak a solution into the RED lab's framing (i.e., make the failing-first state impossible to reach)?
4. HONESTY: the Lab 4 key's DSR/Sharpe numbers — verify they match the authoritative computation (canary sharpe_annual = 4.194975314045819, DSR = 0.9764230884853496, grades PASS/PASS/PASS/FAIL/HOLD) established in Ch 23's cleared review. Flag any number that contradicts it.
5. CROSS-REFERENCES: claims about what Ch 17 (PSR/DSR), Ch 20–23 establish — flag misrepresentations.

For each defect give a SEVERITY (High/Medium/Low), the exact location, what is wrong, and the precise fix. If you find zero defects, reply with the single word: PASS
---
